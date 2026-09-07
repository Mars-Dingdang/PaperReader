"""Persistent, structure-preserving alignment between source and translation.

The translation pipeline translates structured IR strings in-place and keeps
their order.  Capturing those strings before and after translation gives us an
exact bilingual index.  Older documents are upgraded lazily from their saved
MinerU structure and the already persisted translated Markdown.
"""

from __future__ import annotations

import json
import re
import threading
from difflib import SequenceMatcher
from pathlib import Path

from app.core.config import settings
from app.models.store import DocumentRecord
from app.services.mineru_layout import (
    Image,
    InlineMath,
    ListBlock,
    Paragraph,
    Table,
    TextRun,
    Title,
    blocks_to_ir,
)


_ALIGNMENT_FILENAME = "alignment.json"
_LOCK = threading.RLock()


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", (text or "").lower())


def _plain_target(text: str) -> str:
    value = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text or "")
    value = re.sub(r"\$\$.*?\$\$|\$[^$]*\$", " ", value, flags=re.DOTALL)
    value = re.sub(r"\\(?:label|ref|cite)\{[^{}]*\}", " ", value)
    value = re.sub(r"\\[a-zA-Z]+\*?", "", value)
    value = value.replace("\\_", "_").replace("\\%", "%").replace("\\&", "&")
    value = re.sub(r"[#*_`{}]+", " ", value)
    return " ".join(value.split()).strip()


def _text_from_runs(runs: list) -> str:
    parts: list[str] = []
    for run in runs:
        if isinstance(run, TextRun):
            parts.append(run.text)
        elif isinstance(run, InlineMath) and run.latex:
            parts.append(f"${run.latex}$")
    return "".join(parts).strip()


def ir_to_markdown_blocks(ir: list) -> list[str]:
    """Render the same visible block sequence used by translated_text."""
    blocks: list[str] = []
    for block in ir:
        if isinstance(block, Title):
            hashes = "#" * max(1, min(block.level, 6))
            blocks.append(f"{hashes} {block.text}")
        elif isinstance(block, Paragraph):
            text = _text_from_runs(block.runs)
            if text:
                blocks.append(text)
        elif isinstance(block, ListBlock):
            for item in block.items:
                text = _text_from_runs(item)
                if text:
                    blocks.append(text)
        elif isinstance(block, Image):
            # translated_text stores the image path, but images cannot be
            # selected from the PDF text layer, so they do not enter the map.
            continue
        else:
            latex = getattr(block, "latex", "")
            if latex:
                blocks.append(f"$$\n{latex}\n$$")
    return blocks


def split_markdown_blocks(text: str) -> list[str]:
    return [
        " ".join(part.split())
        for part in re.split(r"\n\s*\n+", text or "")
        if len(part.strip()) >= 2 and not part.lstrip().startswith("![](")
    ]


def save_alignment_entries(record: DocumentRecord, entries: list[dict]) -> Path:
    path = settings.output_dir / record.document_id / _ALIGNMENT_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": 2, "entries": entries}
    temporary = path.with_suffix(".tmp")
    with _LOCK:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
    return path


def save_exact_alignment(
    record: DocumentRecord, source_segments: list[str], translated_segments: list[str]
) -> Path | None:
    if not source_segments or len(source_segments) != len(translated_segments):
        return None
    total = max(1, len(source_segments) - 1)
    entries = [
        {
            "index": index,
            "position": index / total,
            "original": source,
            "translated": translated,
            "kind": "translation_segment",
        }
        for index, (source, translated) in enumerate(zip(source_segments, translated_segments))
        if source.strip() and translated.strip()
    ]
    return save_alignment_entries(record, entries) if entries else None


def _read_alignment(path: Path) -> list[dict]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        entries = payload.get("entries") if isinstance(payload, dict) else None
        if isinstance(entries, list):
            return [
                item
                for item in entries
                if isinstance(item, dict) and item.get("original") and item.get("translated")
            ]
    except Exception:
        pass
    return []


def _content_list_path(record: DocumentRecord) -> Path | None:
    for artifact in reversed(record.artifacts):
        if "content_list_v2" in artifact.name:
            candidate = Path(artifact.path)
            if candidate.is_file():
                return candidate
    mineru_dir = settings.output_dir / record.document_id / "mineru"
    candidates = sorted(mineru_dir.glob("*_content_list_v2.json")) if mineru_dir.is_dir() else []
    return candidates[-1] if candidates else None


def _latex_caption_arguments(tex: str) -> list[str]:
    """Extract balanced ``\\caption{}``/``\\caption*{}`` arguments."""
    results: list[str] = []
    pattern = re.compile(r"\\caption\*?\s*\{")
    for match in pattern.finditer(tex or ""):
        depth = 1
        cursor = match.end()
        start = cursor
        while cursor < len(tex) and depth:
            char = tex[cursor]
            if char == "\\":
                cursor += 2
                continue
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
            cursor += 1
        if depth == 0:
            value = _plain_target(tex[start : cursor - 1])
            if value:
                results.append(value)
    return results


def _caption_label(text: str) -> tuple[str, int] | None:
    match = re.search(r"(?i)\b(?:figure|fig\.?)[\s~]*(\d+)", text or "")
    if match:
        return "figure", int(match.group(1))
    match = re.search(r"(?i)\btable[\s~]*(\d+)", text or "")
    if match:
        return "table", int(match.group(1))
    match = re.search(r"图\s*(\d+)", text or "")
    if match:
        return "figure", int(match.group(1))
    match = re.search(r"表\s*(\d+)", text or "")
    if match:
        return "table", int(match.group(1))
    return None


def _caption_alignment_entries(record: DocumentRecord, ir: list) -> list[dict]:
    tex_path = record.translated_tex_path or (
        settings.output_dir / record.document_id / "translated.tex"
    )
    if not tex_path.is_file():
        return []
    try:
        translated_captions = _latex_caption_arguments(tex_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    translated_by_label = {
        label: caption
        for caption in translated_captions
        if (label := _caption_label(caption)) is not None
    }
    total = max(1, len(ir) - 1)
    entries: list[dict] = []
    for block_index, block in enumerate(ir):
        if not isinstance(block, (Image, Table)):
            continue
        source_caption = (getattr(block, "caption", "") or "").strip()
        label = _caption_label(source_caption)
        translated_caption = translated_by_label.get(label) if label else None
        if source_caption and translated_caption:
            # If a grouped MinerU caption includes a sub-caption before the
            # main Figure/Table label, use only the labelled suffix for this
            # entry.  The full caption remains available as a lower-priority
            # match through its neighbouring structured block.
            label_match = re.search(
                r"(?i)(?:figure|fig\.?|table)[\s~]*\d+.*$", source_caption
            )
            labelled_source = label_match.group(0) if label_match else source_caption
            entries.append(
                {
                    "index": len(entries),
                    "position": block_index / total,
                    "original": labelled_source,
                    "translated": translated_caption,
                    "kind": "caption_label",
                }
            )
    return entries


def _rebuild_legacy_alignment(record: DocumentRecord) -> list[dict]:
    content_path = _content_list_path(record)
    if not content_path or not record.translated_text.strip():
        return []
    try:
        content = json.loads(content_path.read_text(encoding="utf-8"))
        ir = blocks_to_ir(content)
        source_blocks = ir_to_markdown_blocks(ir)
    except Exception:
        return []
    translated_blocks = split_markdown_blocks(record.translated_text)
    if not source_blocks or len(source_blocks) != len(translated_blocks):
        return []
    total = max(1, len(source_blocks) - 1)
    entries = [
        {
            "index": index,
            "position": index / total,
            "original": source,
            "translated": translated,
            "kind": "structured_block",
        }
        for index, (source, translated) in enumerate(zip(source_blocks, translated_blocks))
        if source.strip() and translated.strip()
    ]
    entries.extend(_caption_alignment_entries(record, ir))
    return entries


def load_alignment_entries(record: DocumentRecord) -> tuple[list[dict], str]:
    path = settings.output_dir / record.document_id / _ALIGNMENT_FILENAME
    entries = _read_alignment(path) if path.is_file() else []
    if entries and not (
        all(item.get("kind") == "structured_block" for item in entries)
        and _content_list_path(record)
    ):
        return entries, "exact_index"
    rebuilt = _rebuild_legacy_alignment(record)
    if rebuilt:
        save_alignment_entries(record, rebuilt)
        return rebuilt, "reconstructed_structure"
    if entries:
        return entries, "reconstructed_structure"
    return [], "legacy_ratio"


def _entry_score(candidate: str, needle: str) -> float:
    if not candidate or not needle:
        return 0.0
    if needle in candidate:
        return 1.0
    if candidate in needle and len(candidate) >= 8:
        return min(0.98, 0.72 + len(candidate) / max(1, len(needle)) * 0.25)
    match = SequenceMatcher(None, needle[:1600], candidate[:4000]).find_longest_match()
    coverage = match.size / max(1, len(needle))
    return coverage * 0.92


def locate_in_alignment(
    entries: list[dict], *, source_side: str, selected_text: str, page_ratio: float
) -> tuple[str, float, float, int]:
    source_key = "original" if source_side == "original" else "translated"
    target_key = "translated" if source_side == "original" else "original"
    needle = _normalize(selected_text)[:1600]
    if not entries:
        return "", page_ratio, 0.0, 0

    scored: list[tuple[float, int]] = []
    for index, entry in enumerate(entries):
        candidate = _normalize(str(entry.get(source_key) or ""))
        lexical = _entry_score(candidate, needle)
        position = float(entry.get("position", index / max(1, len(entries) - 1)))
        # Page position is only a tie-breaker.  It must never choose the target
        # by itself once selected text was matched.
        score = lexical - abs(position - page_ratio) * 0.015
        scored.append((score, index))
    best_score, best_index = max(scored, key=lambda item: item[0])
    confidence = max(0.0, min(1.0, best_score))
    if confidence < 0.55:
        best_index = min(
            range(len(entries)),
            key=lambda idx: abs(float(entries[idx].get("position", 0.0)) - page_ratio),
        )
        confidence = 0.0
    best = entries[best_index]
    position = float(best.get("position", best_index / max(1, len(entries) - 1)))
    target = _plain_target(str(best.get(target_key) or ""))
    return target[:1600], max(0.0, min(1.0, position)), confidence, best_index
