import re
import shutil
import uuid
from pathlib import Path

from app.core.config import settings
from app.models.store import ArtifactEntry, DocumentRecord, ReferenceEntry, save_document
from app.services.latex_service import (
    compile_tex_project,
    compile_tex_project_with_fallback,
    copy_pdf_to_output,
    create_translated_tex,
    create_translated_tex_from_ir,
)
from app.services.mineru_layout import (
    Image as IRImage,
    Paragraph as IRParagraph,
    TextRun as IRTextRun,
    Title as IRTitle,
    blocks_to_ir,
)
from app.services.mineru_service import (
    extract_structured_from_pdf,
    extract_text_from_pdf,  # noqa: F401  (kept for test monkeypatching compatibility)
    extract_text_from_pdf_text_layer,
)
from app.services.stage_tracker import init_stages, with_stage
from app.services.translate_service import (
    translate_ir,
    translate_latex_document,
    translate_text,
)
from app.services.vision_check_service import run_vision_check_on_markdown

_REFERENCE_SPLIT_PATTERN = re.compile(r"(?im)^\s*(references|bibliography)\s*$")
_REFERENCE_ITEM_PATTERN = re.compile(r"^\s*(\[\d+\]|\d+\.|\d+\))\s+(.+)")
_NOUGAT_MISSING_PAGE_PATTERN = re.compile(r"^\s*\[MISSING_PAGE[^\]]*\]\s*$", re.MULTILINE)
_ABSTRACT_AT_START_PATTERN = re.compile(r"^\s*\*\*Abstract\*\*\s*", re.IGNORECASE)
_PROBLEM1_HEADING_PATTERN = re.compile(r"(?im)^\s*##\s*Problem\s*1\b")
_PROBLEM2_HEADING_PATTERN = re.compile(r"(?im)^\s*##\s*Problem\s*2\b")
_FIRST_PROBLEM_HEADING_PATTERN = re.compile(r"(?im)^\s*##\s*Problem\s*(\d+)\b")
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


def _clean_nougat_text_with_metadata(text: str, leading_fallback_text: str = "") -> tuple[str, int, int, bool]:
    missing_page_count = len(_NOUGAT_MISSING_PAGE_PATTERN.findall(text))
    cleaned = _NOUGAT_MISSING_PAGE_PATTERN.sub("", text)
    cleaned, recovered_leading = _recover_missing_leading_text(cleaned, leading_fallback_text)
    repaired_up_to = 0

    first_problem_match = _FIRST_PROBLEM_HEADING_PATTERN.search(cleaned)
    first_problem_no = int(first_problem_match.group(1)) if first_problem_match else 0

    if (
        first_problem_no == 2
        and _ABSTRACT_AT_START_PATTERN.match(cleaned)
        and _PROBLEM2_HEADING_PATTERN.search(cleaned)
        and not _PROBLEM1_HEADING_PATTERN.search(cleaned)
    ):
        lines = cleaned.splitlines()
        for idx, line in enumerate(lines):
            if line.strip():
                if line.strip().lower() == "**abstract**":
                    lines.pop(idx)
                break
        cleaned = "\n".join(lines)
        cleaned = f"## Problem 1\n\n{cleaned.lstrip()}"
        repaired_up_to = 1
    elif first_problem_no > 1 and not _PROBLEM1_HEADING_PATTERN.search(cleaned):
        first_start = first_problem_match.start()
        preamble = cleaned[:first_start].strip()
        rest = cleaned[first_start:]
        if first_problem_no == 2 and preamble:
            cleaned = f"## Problem 1\n\n{preamble}\n\n{rest.lstrip()}"
        else:
            stubs = "\n\n".join(
                f"## Problem {n}\n\n[Content not extracted by Nougat]"
                for n in range(1, first_problem_no)
            )
            cleaned = f"{stubs}\n\n{rest.lstrip()}"
        repaired_up_to = first_problem_no - 1

    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip(), repaired_up_to, missing_page_count, recovered_leading


def _clean_nougat_text(text: str) -> tuple[str, int, int]:
    cleaned, repaired_up_to, missing_page_count, _ = _clean_nougat_text_with_metadata(text)
    return cleaned, repaired_up_to, missing_page_count


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
    record.artifacts.append(
        ArtifactEntry(
            name=name,
            kind=kind,
            path=str(path),
            url=_to_data_url(path),
        )
    )


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
) -> DocumentRecord:
    record.status = "processing"
    record.logs.append("Processing started")
    init_stages(record, vision_check_enabled=record.vision_check_enabled)
    save_document(record)
    try:
        record.size_bytes = record.source_path.stat().st_size
    except OSError:
        record.size_bytes = 0

    output_dir = settings.output_dir / record.document_id
    output_dir.mkdir(parents=True, exist_ok=True)
    record.logs.append(f"Output dir: {output_dir}")

    try:
        with with_stage(record, "upload"):
            pass

        if record.source_type in ("tex", "tex_project"):
            with with_stage(record, "compile_original"):
                record.logs.append("Compiling source TEX")
                original_pdf = compile_tex_project(record.source_path, output_dir)
                original_out = output_dir / "original.pdf"
                copy_pdf_to_output(original_pdf, original_out)
                record.original_pdf_url = f"/data/outputs/{record.document_id}/original.pdf"
                _append_artifact(record, "original.pdf", "original_pdf", original_out)

                tex_content = record.source_path.read_text(encoding="utf-8", errors="ignore")
                record.extracted_text = tex_content
                _append_artifact(record, record.source_path.name, "source_tex", record.source_path)

                display_title, used_title_fallback = _derive_display_title(record.source_filename, tex_content)
                if used_title_fallback:
                    record.logs.append("Title fallback applied from source filename")

                record.references = _extract_references_from_text(tex_content)
                record.logs.append(f"References extracted: {len(record.references)}")

            with with_stage(record, "translate"):
                record.logs.append("Translating LaTeX source")
                translated = translate_latex_document(
                    tex_content,
                    override_api_key=override_api_key,
                    override_base_url=override_base_url,
                    override_model=override_model,
                )
                if "\\begin{document}" not in translated or "\\end{document}" not in translated:
                    raise RuntimeError("LLM did not return a complete LaTeX document")
                record.translated_text = translated

            if record.vision_check_enabled:
                with with_stage(record, "vision_check"):
                    try:
                        record.translated_text = run_vision_check_on_markdown(
                            record,
                            pdf_path=output_dir / "original.pdf",
                            text=record.translated_text,
                            output_dir=output_dir,
                        )
                    except Exception as exc:  # never block the pipeline on vision check
                        record.logs.append(f"Vision check skipped: {exc}")

            with with_stage(record, "compile_translated"):
                # Write translated tex next to the source so \\includegraphics resolves
                translated_tex_in_project = record.source_path.parent / "__translated.tex"
                translated_tex_in_project.write_text(record.translated_text, encoding="utf-8")
                compile_result = compile_tex_project_with_fallback(translated_tex_in_project, output_dir)
                translated_pdf = compile_result.pdf_path
                if compile_result.warning:
                    record.last_compile_warning = compile_result.warning
                    record.logs.append(f"LaTeX warning: {compile_result.warning}")

                translated_tex = output_dir / "translated.tex"
                translated_tex.write_text(record.translated_text, encoding="utf-8")
                record.translated_tex_path = translated_tex
                _append_artifact(record, "translated.tex", "translated_tex", translated_tex)
                record.logs.append(f"Translated TEX: {translated_tex}")

                translated_out = output_dir / "translated.pdf"
                copy_pdf_to_output(translated_pdf, translated_out)
                record.translated_pdf_url = f"/data/outputs/{record.document_id}/translated.pdf"
                _append_artifact(record, "translated.pdf", "translated_pdf", translated_out)

            record.status = "done"
            record.logs.append("Processing done")
            return save_document(record)
        else:
            with with_stage(record, "mineru"):
                record.logs.append("Handling source PDF")
                original_out = output_dir / "original.pdf"
                shutil.copyfile(record.source_path, original_out)
                record.original_pdf_url = f"/data/outputs/{record.document_id}/original.pdf"
                _append_artifact(record, "original.pdf", "original_pdf", original_out)
                _append_artifact(record, record.source_path.name, "source_pdf", record.source_path)

                nougat_dir = output_dir / "mineru"
                record.logs.append("Submitting PDF to MinerU")
                mineru_result = extract_structured_from_pdf(
                    str(record.source_path), nougat_dir, log_sink=record.logs
                )

            with with_stage(record, "clean"):
                extracted_text = mineru_result.markdown
                device_or_mode = mineru_result.mode_label
                nougat_files = mineru_result.extracted_files
                fallback_text = extract_text_from_pdf_text_layer(str(record.source_path), max_pages=3)
                record.extracted_text, repaired_up_to, missing_page_count, recovered_leading = _clean_nougat_text_with_metadata(
                    extracted_text,
                    leading_fallback_text=fallback_text,
                )
                if not record.extracted_text:
                    raise RuntimeError("MinerU output became empty after cleaning missing-page markers")
                if missing_page_count:
                    record.logs.append(
                        f"MinerU warning: {missing_page_count} missing-page marker(s) stripped; content may be incomplete"
                    )
                if recovered_leading:
                    record.logs.append("Recovered leading PDF content from embedded text layer")
                record.logs.append("MinerU output cleaned")
                if repaired_up_to == 1:
                    record.logs.append("Heading repaired: inserted Problem 1")
                elif repaired_up_to > 1:
                    record.logs.append(f"Heading repaired: inserted Problems 1-{repaired_up_to}")
                record.logs.append(f"MinerU model: {device_or_mode}")
                record.logs.append(f"MinerU output dir: {nougat_dir}")
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

                if ir_blocks is not None:
                    record.logs.append("Translating structured blocks")
                    translate_ir(
                        ir_blocks,
                        override_api_key=override_api_key,
                        override_base_url=override_base_url,
                        override_model=override_model,
                    )
                    record.translated_text = _ir_to_translated_markdown(ir_blocks)
                    create_translated_tex_from_ir(
                        ir_blocks,
                        translated_tex,
                        images_src_dir=mineru_result.images_dir,
                        title=display_title,
                    )
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
                    )
                    record.translated_text = translated
                    create_translated_tex(translated, translated_tex, title=display_title)

                _append_artifact(record, "translated.tex", "translated_tex", translated_tex)
                record.logs.append(f"Translated TEX: {translated_tex}")

            with with_stage(record, "latex_build"):
                compile_result = compile_tex_project_with_fallback(translated_tex, output_dir)
                translated_pdf = compile_result.pdf_path
                if compile_result.warning:
                    record.last_compile_warning = compile_result.warning
                    record.logs.append(f"LaTeX warning: {compile_result.warning}")
                record.translated_tex_path = translated_tex
                translated_out = output_dir / "translated.pdf"
                copy_pdf_to_output(translated_pdf, translated_out)
                record.translated_pdf_url = f"/data/outputs/{record.document_id}/translated.pdf"
                _append_artifact(record, "translated.pdf", "translated_pdf", translated_out)

        record.status = "done"
        record.logs.append("Processing done")
    except Exception as exc:
        record.status = "failed"
        record.logs.append(f"Error: {exc}")
    return save_document(record)
