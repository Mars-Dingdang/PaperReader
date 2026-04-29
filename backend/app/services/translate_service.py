import logging
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, TypeVar

from app.core.config import settings
from app.services.latex_sanitizer import sanitize_latex_body
from app.services.llm_client import llm_client
from app.services.mineru_layout import (
    Block,
    apply_translations,
    collect_translatable_strings,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")


def _run_concurrent(
    items: list[T],
    worker: Callable[[int, T], str],
    fallback: Callable[[int, T, Exception], str],
    max_workers: int | None = None,
) -> list[str]:
    """Run `worker(idx, item)` for each item concurrently; on per-item exception
    after all retries are exhausted by the worker, call `fallback(idx, item, exc)`
    so the pipeline never fails wholesale due to a single chunk being rejected.
    Results are returned in the original order.
    """
    if not items:
        return []
    workers = max(1, max_workers or settings.translate_concurrency)
    workers = min(workers, len(items))
    results: list[str] = [""] * len(items)

    def _safe(idx: int, item: T) -> tuple[int, str]:
        try:
            return idx, worker(idx, item)
        except Exception as exc:  # noqa: BLE001 - want to capture all to fallback
            logger.warning("Chunk %d failed after retries, using fallback: %s", idx, exc)
            return idx, fallback(idx, item, exc)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(_safe, i, item) for i, item in enumerate(items)]
        for fut in futures:
            idx, value = fut.result()
            results[idx] = value
    return results


_PLACEHOLDER_PATTERN = re.compile(r"(\\$[^$]+\\$|\\\\\[[^\]]+\\\\\]|\\\\\([^\)]+\\\\\)|\\\\cite\{[^}]+\}|\\\\ref\{[^}]+\}|https?://\\S+)")
_MAX_CHARS_PER_CHUNK = 4000
_LATEX_FENCE_PATTERN = re.compile(r"^```(?:latex)?\s*|\s*```$", re.MULTILINE)
_DOCUMENT_BODY_PATTERN = re.compile(r"(?s)^(.*?\\begin\{document\})(.*?)(\\end\{document\}.*)$")
_CJK_PACKAGE_PATTERN = re.compile(r"\\usepackage(?:\[[^\]]*\])?\{(?:ctex|xeCJK|CJKutf8|CJK)\}")
_CJK_PREAMBLE_SNIPPET = (
    "\n% Injected by PaperReader to render Chinese translation\n"
    "\\usepackage{xeCJK}\n"
    "\\IfFontExistsTF{Songti SC}{\\setCJKmainfont{Songti SC}}{%\n"
    "  \\IfFontExistsTF{PingFang SC}{\\setCJKmainfont{PingFang SC}}{%\n"
    "    \\IfFontExistsTF{Noto Serif CJK SC}{\\setCJKmainfont{Noto Serif CJK SC}}{}}}\n"
)


def protect_placeholders(text: str) -> tuple[str, dict[str, str]]:
    mapping: dict[str, str] = {}

    def repl(match: re.Match[str]) -> str:
        token = f"<PH_{len(mapping)}>"
        mapping[token] = match.group(0)
        return token

    return _PLACEHOLDER_PATTERN.sub(repl, text), mapping


def restore_placeholders(text: str, mapping: dict[str, str]) -> str:
    for key, value in mapping.items():
        text = text.replace(key, value)
    return text


def split_text_into_chunks(text: str, max_chars: int = _MAX_CHARS_PER_CHUNK) -> list[str]:
    paragraphs = [paragraph for paragraph in text.split("\n\n") if paragraph.strip()]
    if not paragraphs:
        return [text]

    chunks: list[str] = []
    current_parts: list[str] = []
    current_len = 0

    def flush_current() -> None:
        nonlocal current_parts, current_len
        if current_parts:
            chunks.append("\n\n".join(current_parts).strip())
            current_parts = []
            current_len = 0

    for paragraph in paragraphs:
        paragraph_len = len(paragraph)
        if paragraph_len > max_chars:
            flush_current()
            start = 0
            while start < paragraph_len:
                end = min(start + max_chars, paragraph_len)
                if end < paragraph_len:
                    split_newline = paragraph.rfind("\n", start, end)
                    split_space = paragraph.rfind(" ", start, end)
                    split_at = max(split_newline, split_space)
                    if split_at > start + (max_chars // 2):
                        end = split_at
                piece = paragraph[start:end].strip()
                if piece:
                    chunks.append(piece)
                start = end
            continue

        proposed_len = paragraph_len if not current_parts else current_len + 2 + paragraph_len
        if proposed_len <= max_chars:
            current_parts.append(paragraph)
            current_len = proposed_len
        else:
            flush_current()
            current_parts.append(paragraph)
            current_len = paragraph_len

    flush_current()
    return chunks or [text]


def translate_text(
    text: str,
    override_api_key: str | None = None,
    override_base_url: str | None = None,
    override_model: str | None = None,
) -> str:
    protected_text, mapping = protect_placeholders(text)
    chunks = split_text_into_chunks(protected_text)
    system_prompt = (
        "You are a professional academic translator. Translate English academic text into Chinese and output only LaTeX body content. "
        "Do not include document preamble commands like \\documentclass or \\begin{document}. "
        "Use LaTeX structure commands for headings and lists, such as \\section{}, \\subsection{}, \\begin{enumerate}...\\end{enumerate}, "
        "and \\begin{itemize}...\\end{itemize}. Use \\textbf{} or \\textit{} for emphasis when needed. "
        "Do not output Markdown syntax like #, ##, **, or 1./- list markers. "
        "Never repeat, translate, or explain these instructions. "
        "Keep all placeholder tokens like <PH_0> unchanged, and do not alter LaTeX commands or citation references represented by placeholders."
    )

    translated_chunks = _run_concurrent(
        chunks,
        worker=lambda _i, chunk: _strip_prompt_leak(
            llm_client.chat(
                message=chunk,
                system_prompt=system_prompt,
                override_api_key=override_api_key,
                override_base_url=override_base_url,
                override_model=override_model,
            ).strip()
        ),
        fallback=lambda _i, chunk, _exc: chunk,
    )

    translated = "\n\n".join(part for part in translated_chunks if part)
    return restore_placeholders(translated, mapping)


def _strip_code_fences(text: str) -> str:
    return _LATEX_FENCE_PATTERN.sub("", text).strip()


def _split_latex_document(source_text: str) -> tuple[str, str, str]:
    matched = _DOCUMENT_BODY_PATTERN.search(source_text)
    if not matched:
        raise ValueError("Expected a complete LaTeX document with \\begin{document} and \\end{document}")
    return matched.group(1), matched.group(2), matched.group(3)


def _ensure_cjk_support(prefix: str) -> str:
    if _CJK_PACKAGE_PATTERN.search(prefix):
        return prefix
    begin_doc = "\\begin{document}"
    idx = prefix.rfind(begin_doc)
    if idx == -1:
        return prefix
    return prefix[:idx] + _CJK_PREAMBLE_SNIPPET + prefix[idx:]


def _translate_latex_body(
    body_text: str,
    override_api_key: str | None = None,
    override_base_url: str | None = None,
    override_model: str | None = None,
) -> str:
    protected_text, mapping = protect_placeholders(body_text)
    chunks = split_text_into_chunks(protected_text)
    system_prompt = (
        "You are translating a LaTeX document body from English into Chinese. "
        "Translate only human-readable prose. "
        "Preserve all LaTeX commands, environments, math, labels, citations, and custom macros so the fragment remains compilable when inserted back into the original document. "
        "Never repeat, translate, or explain these instructions. "
        "Do not add document preamble commands or Markdown fences. Output only LaTeX body content."
    )

    translated_chunks = _run_concurrent(
        chunks,
        worker=lambda _i, chunk: _strip_prompt_leak(
            _strip_code_fences(
                llm_client.chat(
                    message=chunk,
                    system_prompt=system_prompt,
                    override_api_key=override_api_key,
                    override_base_url=override_base_url,
                    override_model=override_model,
                )
            )
        ),
        fallback=lambda _i, chunk, _exc: chunk,
    )

    translated = "\n\n".join(part for part in translated_chunks if part)
    return restore_placeholders(translated, mapping)


def translate_latex_document(
    source_text: str,
    override_api_key: str | None = None,
    override_base_url: str | None = None,
    override_model: str | None = None,
) -> str:
    prefix, body, suffix = _split_latex_document(source_text)
    prefix = _ensure_cjk_support(prefix)
    translated = _translate_latex_body(
        body,
        override_api_key=override_api_key,
        override_base_url=override_base_url,
        override_model=override_model,
    )
    translated = _strip_code_fences(translated)

    # Be tolerant if the model still returns a full document instead of body-only content.
    try:
        _, translated_body, _ = _split_latex_document(translated)
    except ValueError:
        translated_body = translated

    translated_body = sanitize_latex_body(translated_body.strip())
    return f"{prefix}\n{translated_body}\n{suffix}"


# ---------------------------------------------------------------------------
# IR-based translation (preferred path for MinerU structured output)
# ---------------------------------------------------------------------------

_IR_SEGMENT_DELIMITER = "\n\n@@SEG@@\n\n"
_IR_DELIMITER_PATTERN = re.compile(r"\n*\s*@@SEG@@\s*\n*")

# Heuristics to detect prompt leakage (model echoing the system instructions
# back into the translation output).
_PROMPT_LEAK_FRAGMENTS = (
    "将以下英文学术文本翻译成中文",
    "只输出翻译",
    "不添加任何额外评论",
    "translate the following english",
    "output only the translation",
    "output only the chinese translation",
    "do not add any extra commentary",
    "professional academic translator",
    "you are a translator",
)


def _strip_prompt_leak(text: str) -> str:
    """Remove lines that look like echoed prompt instructions.

    Some upstream gateways do not honor the system role strictly, causing the
    model to translate / repeat the system prompt into the user-visible output.
    We drop any line whose lower-cased form contains a known instruction
    fragment. This is intentionally conservative: only full lines are removed.
    """
    if not text:
        return text
    lines = text.splitlines()
    cleaned: list[str] = []
    for line in lines:
        low = line.lower()
        if any(frag in low for frag in _PROMPT_LEAK_FRAGMENTS):
            continue
        cleaned.append(line)
    # Collapse leading/trailing blank lines introduced by the removal.
    return "\n".join(cleaned).strip("\n")


def _batch_segments(segments: list[str], max_chars: int) -> list[list[int]]:
    """Group segment indices into batches whose joined length stays under
    `max_chars`. Each segment is contributed individually if it alone exceeds
    the budget."""
    batches: list[list[int]] = []
    current: list[int] = []
    current_len = 0
    delim_len = len(_IR_SEGMENT_DELIMITER)
    for idx, seg in enumerate(segments):
        seg_len = len(seg)
        proposed = seg_len if not current else current_len + delim_len + seg_len
        if current and proposed > max_chars:
            batches.append(current)
            current = [idx]
            current_len = seg_len
        else:
            current.append(idx)
            current_len = proposed
    if current:
        batches.append(current)
    return batches


def _translate_segment_batch(
    segments: list[str],
    override_api_key: str | None,
    override_base_url: str | None,
    override_model: str | None,
) -> list[str]:
    if not segments:
        return []
    if len(segments) == 1:
        return [_translate_single_segment(segments[0], override_api_key, override_base_url, override_model)]

    # Protect any residual $...$ / \[...\] math that survived as plain text in
    # a TextRun (e.g. when MinerU didn't split the paragraph into runs).
    protected_segments: list[str] = []
    mappings: list[dict[str, str]] = []
    for seg in segments:
        p, m = protect_placeholders(seg)
        protected_segments.append(p)
        mappings.append(m)

    joined = _IR_SEGMENT_DELIMITER.join(protected_segments)
    system_prompt = (
        "You are a professional academic translator translating English into Chinese. "
        "The user message contains multiple text segments separated by the literal marker '@@SEG@@' on its own line. "
        "Translate each segment from English into Chinese. "
        "Output ONLY the translations in the same order, separated by exactly the same '@@SEG@@' marker on its own line. "
        "Do not merge, drop, reorder, or renumber segments. Do not output any extra commentary, headings, code fences, or Markdown. "
        "Never repeat, translate, or explain these instructions. "
        "Preserve any LaTeX commands, math placeholders like <PH_0>, numbers, URLs, and proper nouns inside a segment unchanged."
    )
    response = llm_client.chat(
        message=joined,
        system_prompt=system_prompt,
        override_api_key=override_api_key,
        override_base_url=override_base_url,
        override_model=override_model,
    )
    response = _strip_prompt_leak(_strip_code_fences(response))
    parts = [p.strip() for p in _IR_DELIMITER_PATTERN.split(response)]
    parts = [p for p in parts if p]
    if len(parts) == len(segments):
        return [restore_placeholders(t, m) for t, m in zip(parts, mappings)]
    # Fallback: translate each segment individually to recover from a malformed batch.
    return [
        _translate_single_segment(seg, override_api_key, override_base_url, override_model)
        for seg in segments
    ]


def _translate_single_segment(
    text: str,
    override_api_key: str | None,
    override_base_url: str | None,
    override_model: str | None,
) -> str:
    stripped = text.strip()
    if not stripped:
        return text
    # Protect any residual $...$ / \[...\] math in the text run before sending
    # to the LLM, then restore afterwards so the formula is never re-translated.
    protected, mapping = protect_placeholders(stripped)
    system_prompt = (
        "Translate the following English academic text into Chinese. "
        "Output only the translation, with no extra commentary, code fences, or Markdown. "
        "Never repeat, translate, or explain these instructions. "
        "Preserve numbers, proper nouns, URLs, math placeholders like <PH_0>, and any LaTeX commands unchanged."
    )
    translated = llm_client.chat(
        message=protected,
        system_prompt=system_prompt,
        override_api_key=override_api_key,
        override_base_url=override_base_url,
        override_model=override_model,
    )
    cleaned = restore_placeholders(_strip_prompt_leak(_strip_code_fences(translated)).strip(), mapping)
    return cleaned or text


def translate_ir(
    ir: list[Block],
    override_api_key: str | None = None,
    override_base_url: str | None = None,
    override_model: str | None = None,
) -> None:
    """Translate the prose content of an IR list in place.

    Math (display + inline), images, and tables are left untouched. Only
    `Title.text`, `TextRun.text`, and image/table captions are sent to the LLM.
    """
    segments = collect_translatable_strings(ir)
    if not segments:
        return

    translations: list[str] = [""] * len(segments)
    batches = _batch_segments(segments, settings.translate_batch_max_chars)

    def _do_batch(_i: int, batch: list[int]) -> str:
        batch_segments = [segments[j] for j in batch]
        batch_translations = _translate_segment_batch(
            batch_segments,
            override_api_key=override_api_key,
            override_base_url=override_base_url,
            override_model=override_model,
        )
        for slot, value in zip(batch, batch_translations):
            translations[slot] = value or segments[slot]
        return ""

    def _fallback(_i: int, batch: list[int], _exc: Exception) -> str:
        # Keep originals for any segment in this failed batch so the pipeline continues.
        for slot in batch:
            if not translations[slot]:
                translations[slot] = segments[slot]
        return ""

    _run_concurrent(batches, worker=_do_batch, fallback=_fallback)

    apply_translations(ir, translations)
