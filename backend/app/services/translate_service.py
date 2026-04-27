import re

from app.services.llm_client import llm_client
from app.services.mineru_layout import (
    Block,
    apply_translations,
    collect_translatable_strings,
)


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
        "Keep all placeholder tokens like <PH_0> unchanged, and do not alter LaTeX commands or citation references represented by placeholders."
    )

    translated_chunks: list[str] = []
    for chunk in chunks:
        translated_chunk = llm_client.chat(
            message=chunk,
            system_prompt=system_prompt,
            override_api_key=override_api_key,
            override_base_url=override_base_url,
            override_model=override_model,
        )
        translated_chunks.append(translated_chunk.strip())

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
        "Do not add document preamble commands or Markdown fences. Output only LaTeX body content."
    )

    translated_chunks: list[str] = []
    for chunk in chunks:
        translated_chunk = llm_client.chat(
            message=chunk,
            system_prompt=system_prompt,
            override_api_key=override_api_key,
            override_base_url=override_base_url,
            override_model=override_model,
        )
        translated_chunks.append(_strip_code_fences(translated_chunk))

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

    return f"{prefix}\n{translated_body.strip()}\n{suffix}"


# ---------------------------------------------------------------------------
# IR-based translation (preferred path for MinerU structured output)
# ---------------------------------------------------------------------------

_IR_SEGMENT_DELIMITER = "\n\n@@SEG@@\n\n"
_IR_DELIMITER_PATTERN = re.compile(r"\n*\s*@@SEG@@\s*\n*")
_IR_BATCH_MAX_CHARS = 3500


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

    joined = _IR_SEGMENT_DELIMITER.join(segments)
    system_prompt = (
        "You are a professional academic translator translating English into Chinese. "
        "The input contains multiple text segments separated by the literal marker '@@SEG@@' on its own line. "
        "Translate each segment from English into Chinese. "
        "Output ONLY the translations in the same order, separated by exactly the same '@@SEG@@' marker on its own line. "
        "Do not merge, drop, reorder, or renumber segments. Do not output any extra commentary, headings, code fences, or Markdown. "
        "Preserve any LaTeX commands, math placeholders, numbers, URLs, and proper nouns inside a segment unchanged."
    )
    response = llm_client.chat(
        message=joined,
        system_prompt=system_prompt,
        override_api_key=override_api_key,
        override_base_url=override_base_url,
        override_model=override_model,
    )
    response = _strip_code_fences(response)
    parts = [p.strip() for p in _IR_DELIMITER_PATTERN.split(response)]
    parts = [p for p in parts if p]
    if len(parts) == len(segments):
        return parts
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
    system_prompt = (
        "Translate the following English academic text into Chinese. "
        "Output only the translation, with no extra commentary, code fences, or Markdown. "
        "Preserve numbers, proper nouns, URLs, and any LaTeX commands unchanged."
    )
    translated = llm_client.chat(
        message=stripped,
        system_prompt=system_prompt,
        override_api_key=override_api_key,
        override_base_url=override_base_url,
        override_model=override_model,
    )
    return _strip_code_fences(translated).strip() or text


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
    for batch in _batch_segments(segments, _IR_BATCH_MAX_CHARS):
        batch_segments = [segments[i] for i in batch]
        batch_translations = _translate_segment_batch(
            batch_segments,
            override_api_key=override_api_key,
            override_base_url=override_base_url,
            override_model=override_model,
        )
        for slot, value in zip(batch, batch_translations):
            translations[slot] = value or segments[slot]

    apply_translations(ir, translations)
