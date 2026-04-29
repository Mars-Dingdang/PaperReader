"""Intermediate representation (IR) for MinerU's structured output.

MinerU returns `content_list_v2.json` as a list of pages, each page being a
list of typed blocks (title, paragraph, equation_interline, image, table…).
This module parses that into a flat list of typed IR nodes that downstream
translation and LaTeX rendering can consume independently.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Union


@dataclass
class TextRun:
    text: str


@dataclass
class InlineMath:
    latex: str


Run = Union[TextRun, InlineMath]


@dataclass
class Title:
    level: int
    text: str


@dataclass
class Paragraph:
    runs: list[Run] = field(default_factory=list)


@dataclass
class DisplayMath:
    latex: str


@dataclass
class Image:
    rel_path: str
    caption: str = ""


@dataclass
class Table:
    rel_path: str = ""
    html: str = ""
    caption: str = ""


Block = Union[Title, Paragraph, DisplayMath, Image, Table]


def _flatten_pages(content_blocks: Iterable) -> list[dict]:
    """`content_list_v2.json` may be a list of pages (list[list[dict]]) or a
    flat list of blocks. Normalize to a flat list of block dicts."""
    flat: list[dict] = []
    for entry in content_blocks:
        if isinstance(entry, list):
            for block in entry:
                if isinstance(block, dict):
                    flat.append(block)
        elif isinstance(entry, dict):
            flat.append(entry)
    return flat


def _runs_from_paragraph_content(items: Iterable) -> list[Run]:
    runs: list[Run] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        kind = item.get("type")
        content = item.get("content")
        if kind == "text" and isinstance(content, str):
            # MinerU sometimes returns an entire sentence (including `$…$`
            # inline math) as a single "text" item instead of splitting it into
            # alternating "text"/"equation_inline" items.  Split here so that
            # inline math never reaches the translation layer as plain text.
            for run in _split_text_at_math(content):
                runs.append(run)
        elif kind == "equation_inline" and isinstance(content, str):
            latex = content.strip()
            if latex:
                runs.append(InlineMath(latex=latex))
    return runs


# Matches $...$ (no nested $), \[...\] or \(...\) display/inline math.
_INLINE_MATH_SPLIT = re.compile(
    r"(\$[^$\n]+?\$"           # $...$
    r"|\\\[[^\]]*?\\\]"        # \[...\]
    r"|\\\([^\)]*?\\\))"       # \(…\)
)


def _split_text_at_math(text: str) -> list[Run]:
    """Split a raw text string at math-delimiter boundaries.

    Returns a list of alternating TextRun / InlineMath nodes so that formula
    content is never sent to the translation layer as translatable prose.
    """
    parts = _INLINE_MATH_SPLIT.split(text)
    runs: list[Run] = []
    for i, part in enumerate(parts):
        if not part:
            continue
        if i % 2 == 1:
            # Odd indices are the captured math groups.
            latex = part
            # Strip outer delimiters to store bare LaTeX.
            if latex.startswith("$") and latex.endswith("$"):
                latex = latex[1:-1]
            elif latex.startswith("\\[") and latex.endswith("\\]"):
                latex = latex[2:-2]
            elif latex.startswith("\\(") and latex.endswith("\\)"):
                latex = latex[2:-2]
            runs.append(InlineMath(latex=latex.strip()))
        else:
            if part.strip():
                runs.append(TextRun(text=part))
    return runs


def _title_text(content: dict) -> str:
    parts: list[str] = []
    for item in content.get("title_content") or []:
        if isinstance(item, dict) and item.get("type") == "text":
            value = item.get("content")
            if isinstance(value, str):
                parts.append(value)
    return " ".join(part.strip() for part in parts if part.strip()).strip()


def blocks_to_ir(content_blocks: Iterable) -> list[Block]:
    """Convert MinerU `content_list_v2.json` into a flat list of IR blocks."""
    ir: list[Block] = []
    for block in _flatten_pages(content_blocks):
        kind = block.get("type")
        content = block.get("content") or {}

        if kind == "title":
            text = _title_text(content) if isinstance(content, dict) else ""
            if not text:
                continue
            level = content.get("level") if isinstance(content, dict) else None
            try:
                level_int = int(level) if level is not None else 1
            except (TypeError, ValueError):
                level_int = 1
            ir.append(Title(level=max(1, level_int), text=text))

        elif kind == "paragraph":
            items = content.get("paragraph_content") if isinstance(content, dict) else None
            runs = _runs_from_paragraph_content(items or [])
            if runs:
                ir.append(Paragraph(runs=runs))

        elif kind == "equation_interline":
            latex = ""
            if isinstance(content, dict):
                latex = (content.get("math_content") or "").strip()
            if latex:
                ir.append(DisplayMath(latex=latex))

        elif kind == "image":
            rel_path = ""
            caption = ""
            if isinstance(content, dict):
                source = content.get("image_source") or {}
                if isinstance(source, dict):
                    rel_path = (source.get("path") or "").strip()
                cap_items = content.get("image_caption") or content.get("caption") or []
                if isinstance(cap_items, list):
                    caption = " ".join(
                        item.get("content", "")
                        for item in cap_items
                        if isinstance(item, dict) and item.get("type") == "text"
                    ).strip()
                elif isinstance(cap_items, str):
                    caption = cap_items.strip()
            if rel_path:
                ir.append(Image(rel_path=rel_path, caption=caption))

        elif kind == "table":
            rel_path = ""
            html = ""
            caption = ""
            if isinstance(content, dict):
                source = content.get("image_source") or {}
                if isinstance(source, dict):
                    rel_path = (source.get("path") or "").strip()
                html = (content.get("html") or content.get("table_body") or "").strip()
                cap_items = content.get("table_caption") or content.get("caption") or []
                if isinstance(cap_items, list):
                    caption = " ".join(
                        item.get("content", "")
                        for item in cap_items
                        if isinstance(item, dict) and item.get("type") == "text"
                    ).strip()
                elif isinstance(cap_items, str):
                    caption = cap_items.strip()
            if rel_path or html:
                ir.append(Table(rel_path=rel_path, html=html, caption=caption))

        # Other block kinds (page_footer, header, etc.) are intentionally skipped.

    return ir


def collect_translatable_strings(ir: list[Block]) -> list[str]:
    """Return all human-readable strings in `ir`, in document order.

    Used together with `apply_translations` to translate IR text in a single
    batch without disturbing math/image content.
    """
    out: list[str] = []
    for block in ir:
        if isinstance(block, Title):
            out.append(block.text)
        elif isinstance(block, Paragraph):
            for run in block.runs:
                if isinstance(run, TextRun):
                    out.append(run.text)
        elif isinstance(block, Image) and block.caption:
            out.append(block.caption)
        elif isinstance(block, Table) and block.caption:
            out.append(block.caption)
    return out


def apply_translations(ir: list[Block], translations: list[str]) -> None:
    """Write `translations` back into `ir` in the same order produced by
    `collect_translatable_strings`. Lengths must match."""
    if len(translations) != len(collect_translatable_strings(ir)):
        raise ValueError(
            f"Translation count mismatch: got {len(translations)}, expected "
            f"{len(collect_translatable_strings(ir))}"
        )
    cursor = 0
    for block in ir:
        if isinstance(block, Title):
            block.text = translations[cursor]
            cursor += 1
        elif isinstance(block, Paragraph):
            for run in block.runs:
                if isinstance(run, TextRun):
                    run.text = translations[cursor]
                    cursor += 1
        elif isinstance(block, Image) and block.caption:
            block.caption = translations[cursor]
            cursor += 1
        elif isinstance(block, Table) and block.caption:
            block.caption = translations[cursor]
            cursor += 1
