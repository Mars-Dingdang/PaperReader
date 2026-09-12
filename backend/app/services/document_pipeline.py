import hashlib
import json
import re
import shutil
import uuid
from pathlib import Path

from app.core.config import settings
from app.models.store import (
    ArtifactEntry,
    DocumentRecord,
    FailureEntry,
    LatexRecoveryEntry,
    ReferenceEntry,
    save_document,
    translated_pdf_filename,
)
from app.services.latex_service import (
    TRANSLATED_LATEX_COMPILER,
    compile_tex_project,
    compile_tex_project_with_fallback,
    copy_pdf_to_output,
    create_translated_tex,
    create_translated_tex_from_ir,
    ensure_portable_cjk_font_config,
    extract_tex_title,
    flatten_tex_project,
)
from app.services.mineru_layout import (
    Image as IRImage,
    ListBlock as IRListBlock,
    Paragraph as IRParagraph,
    TextRun as IRTextRun,
    Title as IRTitle,
    blocks_to_ir,
    collect_translatable_strings,
)
from app.services.alignment_service import save_exact_alignment
from app.services.latex_recovery import recover_latex_document
from app.services.latex_sanitizer import (
    sanitize_and_repair,
    validate_latex_structure,
    validate_math_structure,
)
from app.services.mineru_service import (
    MinerUConfig,
    MinerUResult,
    extract_structured_from_pdf,
    extract_structured_from_pdf_local,
    extract_text_from_pdf,  # noqa: F401  (kept for test monkeypatching compatibility)
    extract_text_from_pdf_text_layer,
)
from app.services.stage_tracker import (
    ensure_stage,
    init_stages,
    prepare_stages_for_retry,
    set_stage_progress,
    with_stage,
)
from app.services.translate_service import (
    build_translation_context,
    translate_ir,
    translate_latex_document,
    translate_text,
)
from app.services.vision_check_service import run_vision_check_on_markdown
from app.services.auth_service import UserSettings

_REFERENCE_SPLIT_PATTERN = re.compile(r"(?im)^\s*(references|bibliography)\s*$")
_REFERENCE_ITEM_PATTERN = re.compile(r"^\s*(\[\d+\]|\d+\.|\d+\))\s+(.+)")
_NOUGAT_MISSING_PAGE_PATTERN = re.compile(r"^\s*\[MISSING_PAGE[^\]]*\]\s*$", re.MULTILINE)
_TITLE_H1_PATTERN = re.compile(r"(?m)^#\s+(.+)$")


def _normalize_for_alignment(text: str) -> tuple[str, list[int]]:
    normalized_chars: list[str] = []
    index_map: list[int] = []
    previous_was_space = True

    for idx, char in enumerate(text):
        if char.isalnum():
            normalized_chars.append(char.lower())
            index_map.append(idx)
            previous_was_space = False
            continue

        if char.isspace() and not previous_was_space and normalized_chars:
            normalized_chars.append(" ")
            index_map.append(idx)
            previous_was_space = True

    if normalized_chars and normalized_chars[-1] == " ":
        normalized_chars.pop()
        index_map.pop()

    return "".join(normalized_chars), index_map


def _recover_missing_leading_text(primary_text: str, fallback_text: str) -> tuple[str, bool]:
    if not primary_text.strip() or not fallback_text.strip():
        return primary_text, False

    normalized_primary, primary_map = _normalize_for_alignment(primary_text)
    normalized_fallback, fallback_map = _normalize_for_alignment(fallback_text)
    anchor_len = min(80, len(normalized_primary) // 2, len(normalized_fallback) // 2)
    anchor_len = max(anchor_len, 24)
    min_leading_chars = max(24, anchor_len // 2)
    if len(normalized_primary) < anchor_len or len(normalized_fallback) < anchor_len:
        return primary_text, False

    search_limit = min(len(normalized_primary) - anchor_len, 1200)
    for primary_offset in range(0, search_limit + 1, 60):
        anchor = normalized_primary[primary_offset : primary_offset + anchor_len].strip()
        if len(anchor) < anchor_len // 2:
            continue

        fallback_offset = normalized_fallback.find(anchor)
        if fallback_offset == -1:
            continue
        if fallback_offset < min_leading_chars:
            return primary_text, False

        raw_primary_start = primary_map[primary_offset]
        raw_fallback_end = fallback_map[fallback_offset]
        leading_prefix = fallback_text[:raw_fallback_end].strip()
        if len(leading_prefix) < min_leading_chars:
            return primary_text, False

        merged = f"{leading_prefix}\n\n{primary_text[raw_primary_start:].lstrip()}"
        return merged.strip(), True

    return primary_text, False


def _clean_nougat_text_with_metadata(text: str, leading_fallback_text: str = "") -> tuple[str, int, bool]:
    """Strip extraction artifacts that would corrupt downstream stages.

    Removes missing-page markers, recovers a leading section the primary text
    lost (matched against the PDF's embedded text layer), and collapses
    blank-line runs.
    """
    missing_page_count = len(_NOUGAT_MISSING_PAGE_PATTERN.findall(text))
    cleaned = _NOUGAT_MISSING_PAGE_PATTERN.sub("", text)
    cleaned, recovered_leading = _recover_missing_leading_text(cleaned, leading_fallback_text)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip(), missing_page_count, recovered_leading


def _derive_display_title(source_filename: str, extracted_text: str) -> tuple[str, bool]:
    matched = _TITLE_H1_PATTERN.search(extracted_text)
    if matched:
        return matched.group(1).strip(), False
    return Path(source_filename).stem.strip(), True


def _ir_to_translated_markdown(ir_blocks: list) -> str:
    """Render a (translated) IR list back into a lightweight Markdown string
    so it can be used by chat / preview surfaces that expect plain text."""
    parts: list[str] = []
    for block in ir_blocks:
        if isinstance(block, IRTitle):
            hashes = "#" * max(1, min(block.level, 6))
            parts.append(f"{hashes} {block.text}")
        elif isinstance(block, IRParagraph):
            text_runs: list[str] = []
            for run in block.runs:
                if isinstance(run, IRTextRun):
                    text_runs.append(run.text)
                else:
                    latex = getattr(run, "latex", "")
                    if latex:
                        text_runs.append(f"${latex}$")
            joined = "".join(text_runs).strip()
            if joined:
                parts.append(joined)
        elif isinstance(block, IRListBlock):
            for item in block.items:
                item_parts: list[str] = []
                for run in item:
                    if isinstance(run, IRTextRun):
                        item_parts.append(run.text)
                    else:
                        latex = getattr(run, "latex", "")
                        if latex:
                            item_parts.append(f"${latex}$")
                joined = "".join(item_parts).strip()
                if joined:
                    parts.append(joined)
        elif isinstance(block, IRImage):
            parts.append(f"![]({block.rel_path})")
        else:
            latex = getattr(block, "latex", "")
            if latex:
                parts.append(f"$$\n{latex}\n$$")
    return "\n\n".join(parts).strip()




def _to_data_url(path: Path) -> str | None:
    try:
        rel = path.resolve().relative_to(settings.data_dir.resolve())
    except ValueError:
        return None
    return "/data/" + str(rel).replace("\\", "/")


def _append_artifact(record: DocumentRecord, name: str, kind: str, path: Path) -> None:
    for artifact in record.artifacts:
        if artifact.kind == kind and Path(artifact.path) == path:
            artifact.name = name
            artifact.url = _to_data_url(path)
            return
    record.artifacts.append(
        ArtifactEntry(
            name=name,
            kind=kind,
            path=str(path),
            url=_to_data_url(path),
        )
    )


def _publish_translated_pdf(
    record: DocumentRecord, compiled_pdf: Path, output_dir: Path
) -> Path:
    """Publish a translated PDF using the source-derived download name."""
    name = translated_pdf_filename(record.source_filename)
    output = output_dir / name
    copy_pdf_to_output(compiled_pdf, output)
    if compiled_pdf.resolve() != output.resolve():
        compiled_pdf.unlink(missing_ok=True)
    record.translated_pdf_url = _to_data_url(output)
    _append_artifact(record, name, "translated_pdf", output)
    return output


def _extract_references_from_text(text: str) -> list[ReferenceEntry]:
    lines = text.splitlines()
    start = None
    for idx, line in enumerate(lines):
        if _REFERENCE_SPLIT_PATTERN.match(line.strip()):
            start = idx + 1
            break
    if start is None:
        return []

    refs: list[ReferenceEntry] = []
    current: list[str] = []
    ref_idx = 0

    for raw in lines[start:]:
        line = raw.strip()
        if not line:
            if current:
                ref_idx += 1
                refs.append(ReferenceEntry(index=ref_idx, text=" ".join(current).strip()))
                current = []
            continue

        matched = _REFERENCE_ITEM_PATTERN.match(line)
        if matched:
            if current:
                ref_idx += 1
                refs.append(ReferenceEntry(index=ref_idx, text=" ".join(current).strip()))
            current = [matched.group(2).strip()]
        elif current:
            current.append(line)
        elif len(line) > 20:
            current = [line]

    if current:
        ref_idx += 1
        refs.append(ReferenceEntry(index=ref_idx, text=" ".join(current).strip()))

    return refs


_EXTRACTION_CHECKPOINT_VERSION = "pdf-extraction-v1"


def _source_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _save_extraction_checkpoint(
    path: Path, source_path: Path, result: MinerUResult
) -> None:
    payload = {
        "version": _EXTRACTION_CHECKPOINT_VERSION,
        "source_sha256": _source_digest(source_path),
        "markdown": result.markdown,
        "mode_label": result.mode_label,
        "extracted_files": [str(item) for item in result.extracted_files],
        "content_blocks": result.content_blocks,
        "images_dir": str(result.images_dir) if result.images_dir else None,
        "two_column": result.two_column,
    }
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def _load_extraction_checkpoint(path: Path, source_path: Path) -> MinerUResult | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return None
        if payload.get("version") != _EXTRACTION_CHECKPOINT_VERSION:
            return None
        if payload.get("source_sha256") != _source_digest(source_path):
            return None
        return MinerUResult(
            markdown=str(payload.get("markdown") or ""),
            mode_label=str(payload.get("mode_label") or "checkpoint"),
            extracted_files=[Path(item) for item in payload.get("extracted_files") or []],
            content_blocks=payload.get("content_blocks"),
            images_dir=Path(payload["images_dir"]) if payload.get("images_dir") else None,
            two_column=bool(payload.get("two_column")),
        )
    except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError):
        return None


def _persist_latex_recovery(record: DocumentRecord, report: LatexRecoveryEntry) -> None:
    record.status = "recovering"
    record.latex_recovery = report
    stage_map = {
        "analyzing": ("latex_diagnose", "分析 LaTeX 错误"),
        "repairing": ("latex_repair", "安全修复 LaTeX"),
        "recompiling": ("latex_rebuild", "重新编译 LaTeX"),
    }
    if report.status in stage_map:
        key, label = stage_map[report.status]
        entry = ensure_stage(record, key, label)
        for stage in record.stages:
            if stage.key.startswith("latex_") and stage.key != key and stage.status == "running":
                stage.status = "done"
        entry.status = "running"
        record.current_stage = key
        record.current_stage_label = label
    elif report.status in {"succeeded", "failed"}:
        for stage in record.stages:
            if stage.key.startswith("latex_") and stage.status == "running":
                stage.status = "done" if report.status == "succeeded" else "failed"
    save_document(record)


def _compile_result_problem(result) -> str | None:
    if result.errors:
        return "; ".join(
            f"L{item.get('line')}: {item.get('message')}" for item in result.errors[:8]
        )
    if result.used_fallback:
        return result.warning or "LaTeX strict compile failed; PDF required the lenient fallback"
    return None


def _mark_clean_latex_recovery(record: DocumentRecord, warning: str | None = None) -> None:
    record.last_compile_warning = warning
    if record.latex_recovery and record.latex_recovery.status == "failed":
        record.latex_recovery.status = "succeeded"
        record.latex_recovery.last_error = None


def _compile_translated_tex(
    record: DocumentRecord,
    translated_tex: Path,
    output_dir: Path,
    provider_settings: UserSettings | None,
):
    stored_text = translated_tex.read_text(encoding="utf-8", errors="replace")
    current_text = ensure_portable_cjk_font_config(stored_text)
    sanitized_text, deterministic_repairs = sanitize_and_repair(current_text)
    if sanitized_text != stored_text:
        translated_tex.write_text(sanitized_text, encoding="utf-8")
        for repair in deterministic_repairs:
            record.logs.append(f"LaTeX preflight repair: {repair}")
    record.translated_tex_path = translated_tex
    _append_artifact(record, "translated.tex", "translated_tex", translated_tex)
    save_document(record)
    preflight = validate_latex_structure(translated_tex.read_text(encoding="utf-8", errors="replace"))
    if preflight:
        digest = "; ".join(f"L{line}: {message}" for line, message in preflight[:8])
        record.logs.append(f"LaTeX preflight advisory: {digest}")
    compile_result = None
    initial_error: Exception | None = None
    try:
        compile_result = compile_tex_project_with_fallback(
            translated_tex, output_dir, compiler=TRANSLATED_LATEX_COMPILER
        )
        compile_problem = _compile_result_problem(compile_result)
        if compile_problem:
            initial_error = RuntimeError(compile_problem)
            compile_result = None
    except Exception as exc:
        initial_error = exc

    if compile_result is None:
        record.logs.append(f"LaTeX compile requires recovery: {initial_error}")
        outcome = recover_latex_document(
            translated_tex,
            output_dir / f"{translated_tex.stem}.log",
            provider_settings=provider_settings,
            on_update=lambda report: _persist_latex_recovery(record, report),
        )
        record.latex_recovery = outcome.report
        if outcome.result is None:
            raise RuntimeError(
                f"Automatic LaTeX recovery failed: {outcome.report.last_error or initial_error}"
            )
        compile_result = outcome.result
        record.status = "processing"
        record.last_compile_warning = compile_result.warning
    else:
        _mark_clean_latex_recovery(record, compile_result.warning)
    return compile_result


def _compile_translated_tex_project(
    record: DocumentRecord,
    translated_tex: Path,
    output_dir: Path,
    provider_settings: UserSettings | None,
):
    """Compile a translated TeX project while keeping its retry checkpoint durable."""
    stored_text = translated_tex.read_text(encoding="utf-8", errors="replace")
    current_text = ensure_portable_cjk_font_config(stored_text)
    sanitized_text, deterministic_repairs = sanitize_and_repair(current_text)
    if sanitized_text != stored_text:
        translated_tex.write_text(sanitized_text, encoding="utf-8")
        for repair in deterministic_repairs:
            record.logs.append(f"LaTeX preflight repair: {repair}")
    record.translated_text = sanitized_text
    record.translated_tex_path = translated_tex
    _append_artifact(record, "translated.tex", "translated_tex", translated_tex)
    save_document(record)

    # Compile beside the source so relative includes and images keep resolving.
    project_tex = record.source_path.parent / "__translated.tex"
    project_tex.write_text(sanitized_text, encoding="utf-8")
    preflight = validate_latex_structure(sanitized_text)
    if preflight:
        digest = "; ".join(f"L{line}: {message}" for line, message in preflight[:8])
        record.logs.append(f"LaTeX preflight advisory: {digest}")
    compile_result = None
    initial_error: Exception | None = None
    try:
        compile_result = compile_tex_project_with_fallback(
            project_tex, output_dir, compiler=TRANSLATED_LATEX_COMPILER
        )
        compile_problem = _compile_result_problem(compile_result)
        if compile_problem:
            initial_error = RuntimeError(compile_problem)
            compile_result = None
    except Exception as exc:
        initial_error = exc

    if compile_result is None:
        record.logs.append(f"LaTeX compile requires recovery: {initial_error}")
        outcome = recover_latex_document(
            project_tex,
            output_dir / f"{project_tex.stem}.log",
            provider_settings=provider_settings,
            compile_output_dir=output_dir,
            backup_dir=output_dir,
            on_update=lambda report: _persist_latex_recovery(record, report),
        )
        record.latex_recovery = outcome.report
        repaired_text = project_tex.read_text(encoding="utf-8", errors="replace")
        translated_tex.write_text(repaired_text, encoding="utf-8")
        record.translated_text = repaired_text
        save_document(record)
        if outcome.result is None:
            raise RuntimeError(
                f"Automatic LaTeX recovery failed: {outcome.report.last_error or initial_error}"
            )
        compile_result = outcome.result
        record.status = "processing"
        record.last_compile_warning = compile_result.warning
    else:
        _mark_clean_latex_recovery(record, compile_result.warning)
    return compile_result


def _resume_pdf_translation(
    record: DocumentRecord,
    mineru_result: MinerUResult,
    output_dir: Path,
    *,
    override_api_key: str | None,
    override_base_url: str | None,
    override_model: str | None,
    provider_settings: UserSettings | None,
) -> None:
    display_title, _ = _derive_display_title(record.source_filename, record.extracted_text)
    translation_context = build_translation_context(
        display_title,
        record.extracted_text,
        override_api_key=override_api_key,
        override_base_url=override_base_url,
        override_model=override_model,
    )
    translated_tex = output_dir / "translated.tex"
    with with_stage(record, "translate"):
        ir_blocks = (
            blocks_to_ir(mineru_result.content_blocks)
            if mineru_result.content_blocks is not None
            else None
        )
        if ir_blocks:
            source_segments = collect_translatable_strings(ir_blocks)
            translate_ir(
                ir_blocks,
                override_api_key=override_api_key,
                override_base_url=override_base_url,
                override_model=override_model,
                checkpoint_path=output_dir / "translation-checkpoint.json",
                progress_callback=lambda done, total: set_stage_progress(
                    record,
                    "translate",
                    done / max(1, total),
                    f"翻译 {done}/{total} 个片段",
                ),
                translation_context=translation_context,
            )
            translated_segments = collect_translatable_strings(ir_blocks)
            alignment_path = save_exact_alignment(record, source_segments, translated_segments)
            if alignment_path:
                _append_artifact(record, alignment_path.name, "alignment_index", alignment_path)
            record.translated_text = _ir_to_translated_markdown(ir_blocks)
            create_translated_tex_from_ir(
                ir_blocks,
                translated_tex,
                images_src_dir=mineru_result.images_dir,
                title=display_title,
                two_column=mineru_result.two_column,
            )
        else:
            translated = translate_text(
                record.extracted_text,
                override_api_key=override_api_key,
                override_base_url=override_base_url,
                override_model=override_model,
                checkpoint_path=output_dir / "translation-checkpoint.json",
                progress_callback=lambda done, total: set_stage_progress(
                    record, "translate", done / max(1, total), f"翻译 {done}/{total} 个片段"
                ),
                translation_context=translation_context,
            )
            record.translated_text = translated
            create_translated_tex(translated, translated_tex, title=display_title)
        record.translated_tex_path = translated_tex
        _append_artifact(record, "translated.tex", "translated_tex", translated_tex)
        save_document(record)

    with with_stage(record, "latex_build"):
        compile_result = _compile_translated_tex(
            record, translated_tex, output_dir, provider_settings
        )
        if compile_result.warning:
            record.last_compile_warning = compile_result.warning
            record.logs.append(f"LaTeX warning: {compile_result.warning}")
        _publish_translated_pdf(record, compile_result.pdf_path, output_dir)


def _finish_tex_translation(
    record: DocumentRecord,
    output_dir: Path,
    *,
    provider_settings: UserSettings | None,
    vision_model: str | None,
    override_api_key: str | None,
    override_base_url: str | None,
) -> None:
    """Vision check + translated compile after a fresh or resumed translation."""
    if record.vision_check_enabled:
        with with_stage(record, "vision_check"):
            try:
                record.translated_text = run_vision_check_on_markdown(
                    record,
                    pdf_path=output_dir / "original.pdf",
                    text=record.translated_text,
                    output_dir=output_dir,
                    api_key=override_api_key,
                    base_url=override_base_url,
                    model=vision_model,
                )
            except Exception as exc:  # never block the pipeline on vision check
                record.logs.append(f"Vision check skipped: {exc}")

    with with_stage(record, "compile_translated"):
        translated_tex = output_dir / "translated.tex"
        translated_tex.write_text(record.translated_text, encoding="utf-8")
        record.translated_tex_path = translated_tex
        _append_artifact(record, "translated.tex", "translated_tex", translated_tex)
        record.logs.append(f"Translated TEX: {translated_tex}")
        save_document(record)

        structure_issues = validate_math_structure(record.translated_text)
        if structure_issues:
            digest = "; ".join(f"L{line}: {msg}" for line, msg in structure_issues[:5])
            record.logs.append(
                f"LaTeX structure check found {len(structure_issues)} issue(s): {digest}"
            )
        compile_result = _compile_translated_tex_project(
            record, translated_tex, output_dir, provider_settings
        )
        if compile_result.warning:
            record.last_compile_warning = compile_result.warning
            record.logs.append(f"LaTeX warning: {compile_result.warning}")

        _publish_translated_pdf(record, compile_result.pdf_path, output_dir)


def _resume_tex_translation(
    record: DocumentRecord,
    output_dir: Path,
    *,
    override_api_key: str | None,
    override_base_url: str | None,
    override_model: str | None,
    provider_settings: UserSettings | None,
    vision_model: str | None,
) -> None:
    """Continue a failed TeX translation from its chunk checkpoint.

    ``compile_original`` was completed by the interrupted run and its stage is
    still marked done, so only the chunks missing from the checkpoint are
    re-translated.
    """
    tex_content = record.extracted_text or ""
    with with_stage(record, "translate"):
        record.logs.append("Resuming LaTeX translation from checkpoint")
        translation_context = build_translation_context(
            extract_tex_title(tex_content),
            tex_content,
            override_api_key=override_api_key,
            override_base_url=override_base_url,
            override_model=override_model,
        )
        translated = translate_latex_document(
            tex_content,
            override_api_key=override_api_key,
            override_base_url=override_base_url,
            override_model=override_model,
            checkpoint_path=output_dir / "translation-checkpoint.json",
            progress_callback=lambda done, total: set_stage_progress(
                record, "translate", done / max(1, total), f"翻译 {done}/{total} 个片段"
            ),
            translation_context=translation_context,
        )
        if "\\begin{document}" not in translated or "\\end{document}" not in translated:
            raise RuntimeError("LLM did not return a complete LaTeX document")
        record.translated_text = translated

    _finish_tex_translation(
        record,
        output_dir,
        provider_settings=provider_settings,
        vision_model=vision_model,
        override_api_key=override_api_key,
        override_base_url=override_base_url,
    )


def create_document_record(source_path: Path, source_type: str, owner_user_id: int = 0) -> DocumentRecord:
    document_id = str(uuid.uuid4())
    source_filename = source_path.name.split("_", 1)[-1] if "_" in source_path.name else source_path.name
    record = DocumentRecord(
        document_id=document_id,
        owner_user_id=owner_user_id,
        source_type=source_type,
        source_path=source_path,
        source_filename=source_filename,
    )
    return save_document(record)


def process_document(
    record: DocumentRecord,
    override_api_key: str | None = None,
    override_base_url: str | None = None,
    override_model: str | None = None,
    provider_settings: UserSettings | None = None,
    resume_from: str | None = None,
) -> DocumentRecord:
    if provider_settings is not None:
        override_api_key = provider_settings.api_key
        override_base_url = provider_settings.base_url
        override_model = provider_settings.model
    parser = provider_settings.pdf_parser if provider_settings else settings.pdf_parser
    mineru_config = (
        MinerUConfig(
            api_key=provider_settings.mineru_api_key,
            base_url=provider_settings.mineru_base_url,
            model_version=provider_settings.mineru_model_version,
            language=provider_settings.mineru_language,
            enable_formula=provider_settings.mineru_enable_formula,
            enable_table=provider_settings.mineru_enable_table,
            is_ocr=provider_settings.mineru_is_ocr,
            poll_interval=settings.mineru_poll_interval,
            timeout=settings.mineru_timeout,
        )
        if provider_settings
        else None
    )
    vision_model = provider_settings.vision_model if provider_settings else settings.vision_model
    record.status = "processing"
    record.logs.append(
        f"Retry processing started from {resume_from}" if resume_from else "Processing started"
    )
    if not record.stages:
        init_stages(record, vision_check_enabled=record.vision_check_enabled)
    elif resume_from:
        prepare_stages_for_retry(record, resume_from)
    else:
        init_stages(record, vision_check_enabled=record.vision_check_enabled)
    save_document(record)
    try:
        record.size_bytes = record.source_path.stat().st_size
    except OSError:
        record.size_bytes = 0

    output_dir = settings.output_dir / record.document_id
    output_dir.mkdir(parents=True, exist_ok=True)
    record.logs.append(f"Output dir: {output_dir}")
    resumed_extraction: MinerUResult | None = None

    try:
        if not resume_from:
            with with_stage(record, "upload"):
                pass

        if record.source_type in {"tex", "tex_project"} and resume_from in {
            "compile_translated", "latex_build", "latex_diagnose", "latex_repair", "latex_rebuild"
        }:
            translated_tex = record.translated_tex_path or (output_dir / "translated.tex")
            if translated_tex.is_file():
                with with_stage(record, "compile_translated"):
                    compile_result = _compile_translated_tex_project(
                        record, translated_tex, output_dir, provider_settings
                    )
                    if compile_result.warning:
                        record.last_compile_warning = compile_result.warning
                    _publish_translated_pdf(record, compile_result.pdf_path, output_dir)
                record.status = "done"
                record.failure = None
                record.logs.append("Processing done")
                return save_document(record)
            record.logs.append("Translated TeX checkpoint missing; falling back to translation")
            resume_from = "translate"

        if record.source_type == "pdf" and resume_from in {
            "latex_build", "latex_diagnose", "latex_repair", "latex_rebuild"
        }:
            translated_tex = record.translated_tex_path or (output_dir / "translated.tex")
            if translated_tex.is_file():
                with with_stage(record, "latex_build"):
                    compile_result = _compile_translated_tex(
                        record, translated_tex, output_dir, provider_settings
                    )
                    if compile_result.warning:
                        record.last_compile_warning = compile_result.warning
                    _publish_translated_pdf(record, compile_result.pdf_path, output_dir)
                record.status = "done"
                record.failure = None
                record.logs.append("Processing done")
                return save_document(record)
            record.logs.append("Translated TeX checkpoint missing; falling back to translation")
            resume_from = "translate"

        if record.source_type == "pdf" and resume_from == "translate":
            mineru_checkpoint = _load_extraction_checkpoint(
                output_dir / "extraction-checkpoint.json", record.source_path
            )
            if mineru_checkpoint is not None and record.extracted_text:
                _resume_pdf_translation(
                    record,
                    mineru_checkpoint,
                    output_dir,
                    override_api_key=override_api_key,
                    override_base_url=override_base_url,
                    override_model=override_model,
                    provider_settings=provider_settings,
                )
                record.status = "done"
                record.failure = None
                record.logs.append("Processing done")
                return save_document(record)
            if mineru_checkpoint is not None:
                resumed_extraction = mineru_checkpoint
                resume_from = "clean"
                record.logs.append("Extracted-text state missing; rebuilding it from checkpoint")
            else:
                record.logs.append("Extraction checkpoint missing or invalid; falling back to parse")

        if record.source_type == "pdf" and resume_from == "clean" and resumed_extraction is None:
            resumed_extraction = _load_extraction_checkpoint(
                output_dir / "extraction-checkpoint.json", record.source_path
            )
            if resumed_extraction is not None:
                record.logs.append("Reusing completed extraction checkpoint")
            else:
                record.logs.append("Extraction checkpoint missing or invalid; falling back to parse")

        if record.source_type in ("tex", "tex_project"):
            if resume_from == "translate":
                tex_checkpoint = output_dir / "translation-checkpoint.json"
                if record.extracted_text and tex_checkpoint.is_file():
                    _resume_tex_translation(
                        record,
                        output_dir,
                        override_api_key=override_api_key,
                        override_base_url=override_base_url,
                        override_model=override_model,
                        provider_settings=provider_settings,
                        vision_model=vision_model,
                    )
                    record.status = "done"
                    record.failure = None
                    record.logs.append("Processing done")
                    return save_document(record)
                record.logs.append("Translation checkpoint missing; restarting from compile")

            with with_stage(record, "compile_original"):
                record.logs.append("Compiling source TEX")
                original_pdf = compile_tex_project(record.source_path, output_dir)
                original_out = output_dir / "original.pdf"
                copy_pdf_to_output(original_pdf, original_out)
                record.original_pdf_url = f"/data/outputs/{record.document_id}/original.pdf"
                _append_artifact(record, "original.pdf", "original_pdf", original_out)

                tex_content = flatten_tex_project(record.source_path)
                record.extracted_text = tex_content
                _append_artifact(record, record.source_path.name, "source_tex", record.source_path)

                display_title, used_title_fallback = _derive_display_title(record.source_filename, tex_content)
                if used_title_fallback:
                    record.logs.append("Title fallback applied from source filename")

                record.references = _extract_references_from_text(tex_content)
                record.logs.append(f"References extracted: {len(record.references)}")

            with with_stage(record, "translate"):
                record.logs.append("Translating LaTeX source")
                translation_context = build_translation_context(
                    extract_tex_title(tex_content) or display_title,
                    tex_content,
                    override_api_key=override_api_key,
                    override_base_url=override_base_url,
                    override_model=override_model,
                )
                translated = translate_latex_document(
                    tex_content,
                    override_api_key=override_api_key,
                    override_base_url=override_base_url,
                    override_model=override_model,
                    checkpoint_path=output_dir / "translation-checkpoint.json",
                    progress_callback=lambda done, total: set_stage_progress(
                        record, "translate", done / max(1, total), f"翻译 {done}/{total} 个片段"
                    ),
                    translation_context=translation_context,
                )
                if "\\begin{document}" not in translated or "\\end{document}" not in translated:
                    raise RuntimeError("LLM did not return a complete LaTeX document")
                record.translated_text = translated

            _finish_tex_translation(
                record,
                output_dir,
                provider_settings=provider_settings,
                vision_model=vision_model,
                override_api_key=override_api_key,
                override_base_url=override_base_url,
            )

            record.status = "done"
            record.logs.append("Processing done")
            return save_document(record)
        else:
            if resumed_extraction is not None:
                mineru_result = resumed_extraction
                extract_dir = (
                    mineru_result.images_dir.parent
                    if mineru_result.images_dir is not None
                    else output_dir
                )
            else:
                with with_stage(record, "parse"):
                    record.logs.append("Handling source PDF")
                    original_out = output_dir / "original.pdf"
                    shutil.copyfile(record.source_path, original_out)
                    record.original_pdf_url = f"/data/outputs/{record.document_id}/original.pdf"
                    _append_artifact(record, "original.pdf", "original_pdf", original_out)
                    _append_artifact(record, record.source_path.name, "source_pdf", record.source_path)

                    if parser == "mineru":
                        extract_dir = output_dir / "mineru"
                        record.logs.append("Submitting PDF to MinerU")
                        try:
                            mineru_result = extract_structured_from_pdf(
                                str(record.source_path),
                                extract_dir,
                                log_sink=record.logs,
                                progress_cb=lambda frac, label: set_stage_progress(
                                    record, "parse", frac, label
                                ),
                                config=mineru_config,
                            )
                        except Exception as mineru_exc:
                            # MinerU's result CDN can fail after cloud parsing has
                            # completed. Keep the website usable for text-layer PDFs
                            # by falling back locally instead of failing the task.
                            record.logs.append(
                                f"MinerU unavailable ({mineru_exc}); falling back to local PDF parsing"
                            )
                            extract_dir = output_dir / "local"
                            try:
                                mineru_result = extract_structured_from_pdf_local(
                                    str(record.source_path), extract_dir, log_sink=record.logs
                                )
                            except Exception as local_exc:
                                raise RuntimeError(
                                    f"MinerU parsing failed: {mineru_exc}; local fallback also failed: {local_exc}"
                                ) from local_exc
                    else:
                        extract_dir = output_dir
                        record.logs.append("Extracting PDF locally (text layer + images)")
                        mineru_result = extract_structured_from_pdf_local(
                            str(record.source_path), extract_dir, log_sink=record.logs
                        )

                _save_extraction_checkpoint(
                    output_dir / "extraction-checkpoint.json", record.source_path, mineru_result
                )

            with with_stage(record, "clean"):
                extracted_text = mineru_result.markdown
                device_or_mode = mineru_result.mode_label
                nougat_files = mineru_result.extracted_files
                fallback_text = extract_text_from_pdf_text_layer(str(record.source_path), max_pages=3)
                record.extracted_text, missing_page_count, recovered_leading = _clean_nougat_text_with_metadata(
                    extracted_text,
                    leading_fallback_text=fallback_text,
                )
                if not record.extracted_text:
                    raise RuntimeError(
                        "No readable text could be extracted from this PDF. "
                        "It may be a scanned / image-only PDF with no embedded text layer "
                        "(the local parser has no OCR; set PDF_PARSER=mineru to use cloud OCR)."
                    )
                if missing_page_count:
                    record.logs.append(
                        f"MinerU warning: {missing_page_count} missing-page marker(s) stripped; content may be incomplete"
                    )
                if recovered_leading:
                    record.logs.append("Recovered leading PDF content from embedded text layer")
                record.logs.append("MinerU output cleaned")
                record.logs.append(f"Extraction model: {device_or_mode}")
                record.logs.append(f"Extraction dir: {extract_dir}")
                for generated in nougat_files:
                    _append_artifact(record, generated.name, "mineru_output", generated)

                display_title, used_title_fallback = _derive_display_title(record.source_filename, record.extracted_text)
                if used_title_fallback:
                    record.logs.append("Title fallback applied from source filename")

                record.references = _extract_references_from_text(record.extracted_text)
                record.logs.append(f"References extracted: {len(record.references)}")

            if record.vision_check_enabled:
                with with_stage(record, "vision_check"):
                    try:
                        record.extracted_text = run_vision_check_on_markdown(
                            record,
                            pdf_path=output_dir / "original.pdf",
                            text=record.extracted_text,
                            output_dir=output_dir,
                            api_key=override_api_key,
                            base_url=override_base_url,
                            model=vision_model,
                        )
                    except Exception as exc:
                        record.logs.append(f"Vision check skipped: {exc}")

            with with_stage(record, "translate"):
                ir_blocks = None
                if mineru_result.content_blocks is not None:
                    ir_blocks = blocks_to_ir(mineru_result.content_blocks)
                    if not ir_blocks:
                        ir_blocks = None
                    else:
                        record.logs.append(
                            f"Parsed {len(ir_blocks)} structured blocks from MinerU"
                        )

                translated_tex = output_dir / "translated.tex"
                translation_context = build_translation_context(
                    display_title,
                    record.extracted_text,
                    override_api_key=override_api_key,
                    override_base_url=override_base_url,
                    override_model=override_model,
                )

                if ir_blocks is not None:
                    record.logs.append("Translating structured blocks")
                    source_alignment_segments = collect_translatable_strings(ir_blocks)
                    translate_ir(
                        ir_blocks,
                        override_api_key=override_api_key,
                        override_base_url=override_base_url,
                        override_model=override_model,
                        checkpoint_path=output_dir / "translation-checkpoint.json",
                        progress_callback=lambda done, total: set_stage_progress(
                            record,
                            "translate",
                            done / max(1, total),
                            f"翻译 {done}/{total} 个片段",
                        ),
                        translation_context=translation_context,
                    )
                    translated_alignment_segments = collect_translatable_strings(ir_blocks)
                    alignment_path = save_exact_alignment(
                        record, source_alignment_segments, translated_alignment_segments
                    )
                    if alignment_path:
                        _append_artifact(record, alignment_path.name, "alignment_index", alignment_path)
                        record.logs.append(
                            f"Saved {len(source_alignment_segments)} exact bilingual alignment segments"
                        )
                    record.translated_text = _ir_to_translated_markdown(ir_blocks)
                    repairs = create_translated_tex_from_ir(
                        ir_blocks,
                        translated_tex,
                        images_src_dir=mineru_result.images_dir,
                        title=display_title,
                        two_column=mineru_result.two_column,
                    )
                    for note in repairs:
                        record.logs.append(f"Repaired OCR math fault at {note}")
                    if mineru_result.images_dir and mineru_result.images_dir.is_dir():
                        copied = sum(1 for _ in mineru_result.images_dir.iterdir())
                        record.logs.append(f"Copied {copied} image(s) into translated project")
                else:
                    record.logs.append("Falling back to markdown rendering")
                    translated = translate_text(
                        record.extracted_text,
                        override_api_key=override_api_key,
                        override_base_url=override_base_url,
                        override_model=override_model,
                        checkpoint_path=output_dir / "translation-checkpoint.json",
                        progress_callback=lambda done, total: set_stage_progress(
                            record,
                            "translate",
                            done / max(1, total),
                            f"翻译 {done}/{total} 个片段",
                        ),
                        translation_context=translation_context,
                    )
                    record.translated_text = translated
                    repairs = create_translated_tex(translated, translated_tex, title=display_title)
                    for note in repairs:
                        record.logs.append(f"Repaired OCR math fault at {note}")

                _append_artifact(record, "translated.tex", "translated_tex", translated_tex)
                record.translated_tex_path = translated_tex
                record.logs.append(f"Translated TEX: {translated_tex}")
                tex_content = translated_tex.read_text(encoding="utf-8", errors="ignore")
                structure_issues = validate_math_structure(tex_content)
                if structure_issues:
                    digest = "; ".join(f"L{line}: {msg}" for line, msg in structure_issues[:5])
                    record.logs.append(
                        f"LaTeX structure check found {len(structure_issues)} issue(s): {digest}"
                    )

            with with_stage(record, "latex_build"):
                compile_result = _compile_translated_tex(
                    record, translated_tex, output_dir, provider_settings
                )
                translated_pdf = compile_result.pdf_path
                if compile_result.warning:
                    record.last_compile_warning = compile_result.warning
                    record.logs.append(f"LaTeX warning: {compile_result.warning}")
                record.translated_tex_path = translated_tex
                _publish_translated_pdf(record, translated_pdf, output_dir)

        record.status = "done"
        record.failure = None
        record.logs.append("Processing done")
    except Exception as exc:
        record.status = "failed"
        failure_stage = record.current_stage or resume_from or "upload"
        chunk_match = re.search(r"chunk\s+(\d+)", str(exc), re.IGNORECASE)
        record.failure = FailureEntry(
            stage=failure_stage,
            message=str(exc),
            retryable=record.source_path.is_file(),
            chunk=int(chunk_match.group(1)) if chunk_match else None,
            retry_count=record.retry_count,
        )
        record.logs.append(f"Error: {exc}")
    return save_document(record)
