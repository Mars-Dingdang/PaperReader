"""Backend-generated document outline and figure gallery.

Sources, in priority order: MinerU's ``content_list_v2.json`` (page-nested
blocks with captions), the extraction checkpoint's ``content_blocks`` (local
parser, same shape), and for LaTeX projects the image files in the project
directory.  The outline shape matches the frontend's ``OutlineItem``.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.core.config import settings
from app.models.store import DocumentRecord
from app.services.alignment_service import _content_list_path

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}
_FIGURE_LIMIT = 200


def _caption_text(parts) -> str:
    texts: list[str] = []
    for part in parts or []:
        value = str(part.get("content") or "") if isinstance(part, dict) else str(part)
        value = value.strip()
        if value and value not in texts:
            texts.append(value)
    return " ".join(texts)


def _url_for(path: Path) -> str | None:
    try:
        relative = path.resolve().relative_to(settings.data_dir.resolve())
    except ValueError:
        return None
    return "/data/" + relative.as_posix()


def _figure_entry(block: dict, page_number: int, base_dir: Path) -> dict | None:
    content = block.get("content") or {}
    rel_path = str((content.get("image_source") or {}).get("path") or "")
    if not rel_path:
        return None
    url = _url_for((base_dir / rel_path).resolve())
    if not url:
        return None
    return {
        "kind": "table" if block.get("type") == "table" else "figure",
        "caption": _caption_text(content.get("table_caption") or content.get("image_caption")),
        "page": page_number,
        "url": url,
    }


def _structure_from_blocks(pages, base_dir: Path) -> dict:
    outline: list[dict] = []
    stack: list[tuple[int, dict]] = []
    figures: list[dict] = []
    for page_index, blocks in enumerate(pages):
        if not isinstance(blocks, list):
            continue
        for block in blocks:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")
            content = block.get("content") or {}
            if block_type == "title":
                title = _caption_text(content.get("title_content"))
                if not title:
                    continue
                try:
                    level = max(1, int(content.get("level") or 1))
                except (TypeError, ValueError):
                    level = 1
                item = {"title": title, "page_index": page_index, "items": []}
                while stack and stack[-1][0] >= level:
                    stack.pop()
                if stack:
                    stack[-1][1]["items"].append(item)
                else:
                    outline.append(item)
                stack.append((level, item))
            elif block_type in ("image", "chart", "table"):
                if len(figures) >= _FIGURE_LIMIT:
                    continue
                entry = _figure_entry(block, page_index + 1, base_dir)
                if entry:
                    figures.append(entry)
    return {"outline": outline, "figures": figures}


def _tex_project_figures(record: DocumentRecord) -> list[dict]:
    project_dir = record.source_path.parent
    if not project_dir.is_dir():
        return []
    figures: list[dict] = []
    for path in sorted(project_dir.rglob("*")):
        if len(figures) >= _FIGURE_LIMIT:
            break
        if not path.is_file() or path.suffix.lower() not in _IMAGE_EXTS:
            continue
        url = _url_for(path)
        if url:
            figures.append({"kind": "figure", "caption": path.stem, "page": None, "url": url})
    return figures


def build_document_structure(record: DocumentRecord) -> dict:
    content_path = _content_list_path(record)
    if content_path:
        try:
            pages = json.loads(content_path.read_text(encoding="utf-8"))
            structure = _structure_from_blocks(pages, content_path.parent)
            if structure["outline"] or structure["figures"]:
                return structure
        except Exception:
            pass
    checkpoint = settings.output_dir / record.document_id / "extraction-checkpoint.json"
    if checkpoint.is_file():
        try:
            payload = json.loads(checkpoint.read_text(encoding="utf-8"))
            pages = payload.get("content_blocks")
            if pages:
                structure = _structure_from_blocks(pages, checkpoint.parent)
                if structure["outline"] or structure["figures"]:
                    return structure
        except Exception:
            pass
    if record.source_type in {"tex", "tex_project"}:
        return {"outline": [], "figures": _tex_project_figures(record)}
    return {"outline": [], "figures": []}
