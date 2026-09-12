import hashlib
import json
import logging
import os
import re
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, TypeVar

from app.core.config import settings
from app.services.latex_service import CJK_FONT_FALLBACK_PREAMBLE
from app.services.latex_sanitizer import sanitize_and_repair
from app.services.llm_client import LLMOutputTruncatedError, llm_client
from app.services.mineru_layout import (
    Block,
    apply_translations,
    collect_translatable_strings,
    translatable_mask,
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


_PLACEHOLDER_PATTERN = re.compile(r"((?<!\\)\$[^$\n]+?(?<!\\)\$|\\\[[\s\S]*?\\\]|\\\([\s\S]*?\\\)|\\(?:cite|ref)\{[^}]+\}|https?://\S+)")
_LATEX_ENV_PATTERN = re.compile(r"\\(?:begin|end)\s*\{[A-Za-z@]+\*?\}")
_MAX_CHARS_PER_CHUNK = 4000
_STRUCTURAL_TAG_PATTERN = re.compile(r"</?[A-Za-z][^>\r\n]*>")
_PLACEHOLDER_TOKEN_RE = re.compile(r"__PR_PH_\d+__")
_UNESCAPED_DOLLAR_RE = re.compile(r"(?<!\\)\$")
_LATEX_FENCE_PATTERN = re.compile(r"^```(?:latex)?\s*|\s*```$", re.MULTILINE)
_DOCUMENT_BODY_PATTERN = re.compile(r"(?s)^(.*?\\begin\{document\})(.*?)(\\end\{document\}.*)$")
_CJK_PACKAGE_PATTERN = re.compile(r"\\usepackage(?:\[[^\]]*\])?\{(?:ctex|xeCJK|CJKutf8|CJK)\}")
_DECLARE_UNICODE_CHARACTER_PATTERN = re.compile(r"\\DeclareUnicodeCharacter\s*\{")
_CJK_PREAMBLE_SNIPPET = (
    "\n% Injected by PaperReader to render Chinese translation\n"
    "\\usepackage{xeCJK}\n"
    + CJK_FONT_FALLBACK_PREAMBLE
)
_CJK_EARLY_SNIPPET = (
    "% Injected by PaperReader to render Chinese translation. Loaded right\n"
    "% after \\documentclass because font packages that venue styles pull in\n"
    "% (newtxtext via aaai2027.sty) break fontspec font-name resolution for\n"
    "% fonts declared after them under XeLaTeX.\n"
    "\\usepackage{xeCJK}\n"
    + CJK_FONT_FALLBACK_PREAMBLE
)
_DOCUMENTCLASS_PATTERN = re.compile(r"^[ \t]*\\documentclass[ \t]*", re.MULTILINE)
_XELATEX_UNICODE_COMPAT_SNIPPET = (
    "% Injected by PaperReader for pdfLaTeX source compatibility under XeLaTeX\n"
    "\\providecommand{\\DeclareUnicodeCharacter}[2]{}\n"
)
_XELATEX_ENGINE_SHIM_SNIPPET = (
    "% Injected by PaperReader: translated builds always compile with XeLaTeX for CJK\n"
    "% output. Load the engine tests first, then disarm styles that hard-abort on\n"
    "% non-pdfTeX engines (e.g. aaai2027.sty's \\RequirePDFTeX gate); the style's own\n"
    "% later \\RequirePackage{iftex} becomes a no-op and cannot re-arm it. Some of\n"
    "% those styles also call the pdfTeX-only \\pdfinfo primitive unconditionally,\n"
    "% so give it a content-absorbing no-op too.\n"
    "\\RequirePackage{iftex}\n"
    "\\let\\RequirePDFTeX\\relax\n"
    "\\providecommand{\\pdfinfo}[1]{}\n"
)


def _is_escaped_at(text: str, offset: int) -> bool:
    slashes = 0
    offset -= 1
    while offset >= 0 and text[offset] == "\\":
        slashes += 1
        offset -= 1
    return slashes % 2 == 1


def protect_placeholders(text: str) -> tuple[str, dict[str, str]]:
    mapping: dict[str, str] = {}
    source_text = text
    next_index = 0

    def repl(match: re.Match[str]) -> str:
        nonlocal next_index
        token = f"__PR_PH_{next_index:04d}__"
        while token in source_text or token in mapping:
            next_index += 1
            token = f"__PR_PH_{next_index:04d}__"
        next_index += 1
        mapping[token] = match.group(0)
        return token

    # LaTeX environment commands go first: models silently drop or rewrite
    # them (observed: \begin{figure*}/\begin{promptbox} lost mid-document,
    # which left every later \end mispaired and the document uncompilable).
    # As placeholder tokens they are validated verbatim like math and cites.
    text = _LATEX_ENV_PATTERN.sub(repl, text)
    text = _STRUCTURAL_TAG_PATTERN.sub(repl, text)
    return _PLACEHOLDER_PATTERN.sub(repl, text), mapping


def _placeholder_tokens(text: str) -> list[str]:
    return _PLACEHOLDER_TOKEN_RE.findall(text)


def _placeholder_only(text: str, mapping: dict[str, str] | None = None) -> bool:
    if mapping is None:
        remainder = _PLACEHOLDER_TOKEN_RE.sub("", text)
    else:
        remainder = text
        for token in mapping:
            remainder = remainder.replace(token, "")
    return not remainder.strip()


def restore_placeholders(text: str, mapping: dict[str, str]) -> str:
    # Later placeholders may contain earlier ones (a URL immediately followed
    # by a protected closing tag is one example), so unwind in reverse order.
    for key, value in reversed(mapping.items()):
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


def _fail_incomplete_translation(idx: int, _item: T, exc: Exception) -> str:
    """Never publish a document whose failed chunks were silently left English."""
    raise RuntimeError(f"Translation incomplete: chunk {idx + 1} failed") from exc


_GLOSSARY_SAMPLE_CHARS = 6000
_GLOSSARY_MAX_TERMS = 24


def build_translation_context(
    title: str | None,
    sample_text: str,
    override_api_key: str | None = None,
    override_base_url: str | None = None,
    override_model: str | None = None,
) -> str:
    """Pin the paper title and a shared glossary via one best-effort LLM pass.

    Batches otherwise translate in isolation and can render the same term
    differently in the abstract and the conclusion. Any failure returns ""
    — context improves consistency but must never block translation.
    """
    try:
        sample = sample_text[:_GLOSSARY_SAMPLE_CHARS]
        if not sample.strip():
            return ""
        response = llm_client.chat(
            message=f"Paper title: {title or 'unknown'}\n\n{sample}",
            system_prompt=(
                "You extract domain terminology from an academic paper so later "
                "translation batches stay consistent. Return strict JSON only: "
                '{"terms": [{"en": "...", "zh": "..."}]}. '
                f"Include at most {_GLOSSARY_MAX_TERMS} entries: recurring technical "
                "terms, method or system names, and acronyms, each with its "
                "established Chinese translation. No commentary."
            ),
            override_api_key=override_api_key,
            override_base_url=override_base_url,
            override_model=override_model,
        )
        start = response.find("{")
        end = response.rfind("}")
        if start == -1 or end <= start:
            return ""
        data = json.loads(response[start : end + 1])
        terms = data.get("terms") if isinstance(data, dict) else None
        lines: list[str] = []
        if title:
            lines.append(f'The paper title is "{title}"; render it consistently.')
        if isinstance(terms, list):
            pairs = [
                (str(term["en"]).strip(), str(term["zh"]).strip())
                for term in terms[:_GLOSSARY_MAX_TERMS]
                if isinstance(term, dict)
                and isinstance(term.get("en"), str)
                and isinstance(term.get("zh"), str)
                and term["en"].strip()
                and term["zh"].strip()
            ]
            if pairs:
                lines.append(
                    "Translate these recurring terms the same way everywhere: "
                    + "; ".join(f"{en} = {zh}" for en, zh in pairs)
                )
        return "\n".join(lines)
    except Exception as exc:
        logger.info("Terminology extraction skipped: %s", exc)
        return ""


def _with_context(system_prompt: str, translation_context: str) -> str:
    if translation_context:
        return f"{system_prompt}\n\n{translation_context}"
    return system_prompt


def _translate_complete_chunk(
    text: str,
    system_prompt: str,
    override_api_key: str | None,
    override_base_url: str | None,
    override_model: str | None,
    *,
    strip_fences: bool,
    ordered: bool = True,
) -> str:
    """Translate one bounded chunk, recursively shrinking on output truncation."""
    try:
        translated = llm_client.chat(
            message=text,
            system_prompt=system_prompt,
            override_api_key=override_api_key,
            override_base_url=override_base_url,
            override_model=override_model,
        )
    except LLMOutputTruncatedError:
        # Halve the source at a natural boundary. At the minimum size, surface
        # the failure instead of returning a knowingly partial translation.
        if len(text) <= 300:
            raise
        smaller = split_text_into_chunks(text, max_chars=max(300, len(text) // 2))
        if len(smaller) <= 1:
            raise
        return "\n\n".join(
            _translate_complete_chunk(
                part,
                system_prompt,
                override_api_key,
                override_base_url,
                override_model,
                strip_fences=strip_fences,
                ordered=ordered,
            )
            for part in smaller
        )

    translated = _normalize_translation(text, translated, ordered=ordered)
    cleaned = _strip_code_fences(translated) if strip_fences else translated.strip()
    cleaned = _normalize_translation(text, cleaned, ordered=ordered)
    return cleaned


def translate_text(
    text: str,
    override_api_key: str | None = None,
    override_base_url: str | None = None,
    override_model: str | None = None,
    *,
    checkpoint_path: Path | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
    translation_context: str = "",
) -> str:
    protected_text, mapping = protect_placeholders(text)
    chunks = split_text_into_chunks(protected_text)
    system_prompt = _with_context(
        (
            "You are a professional academic translator. Translate English academic text into Chinese and output only LaTeX body content. "
            "Do not include document preamble commands like \\documentclass or \\begin{document}. "
            "Use LaTeX structure commands for headings and lists, such as \\section{}, \\subsection{}, \\begin{enumerate}...\\end{enumerate}, "
            "and \\begin{itemize}...\\end{itemize}. Use \\textbf{} or \\textit{} for emphasis when needed. "
            "Do not output Markdown syntax like #, ##, **, or 1./- list markers. "
            "Never repeat, translate, or explain these instructions. "
            "Keep all placeholder tokens like __PR_PH_0000__ unchanged, and do not alter LaTeX commands or citation references represented by placeholders."
        ),
        translation_context,
    )

    checkpoint_entries = _load_translation_checkpoint(checkpoint_path)
    translated_chunks: list[str] = []
    for chunk in chunks:
        cached = checkpoint_entries.get(_checkpoint_key(chunk, "text"), "")
        if cached:
            try:
                cached = _normalize_translation(chunk, cached)
            except TranslationValidationError:
                cached = ""
        translated_chunks.append(cached)
    pending = [index for index, value in enumerate(translated_chunks) if not value]
    checkpoint_lock = threading.Lock()
    if progress_callback:
        progress_callback(len(chunks) - len(pending), len(chunks))

    def translate_pending(_relative: int, source_index: int) -> str:
        chunk = chunks[source_index]
        if _placeholder_only(chunk, mapping):
            translated = chunk
        else:
            translated = _translate_complete_chunk(
                chunk,
                system_prompt,
                override_api_key,
                override_base_url,
                override_model,
                strip_fences=False,
            )
        with checkpoint_lock:
            translated_chunks[source_index] = translated
            if checkpoint_path is not None:
                checkpoint_entries[_checkpoint_key(chunk, "text")] = translated
                _save_translation_checkpoint(checkpoint_path, checkpoint_entries)
            if progress_callback:
                progress_callback(sum(bool(value) for value in translated_chunks), len(chunks))
        return translated

    _run_concurrent(
        pending,
        worker=translate_pending,
        fallback=lambda _relative, source_index, exc: _fail_incomplete_translation(
            source_index, source_index, exc
        ),
    )

    translated = "\n\n".join(part for part in translated_chunks if part)
    return restore_placeholders(translated, mapping)


def _strip_code_fences(text: str) -> str:
    return _LATEX_FENCE_PATTERN.sub("", text).strip()


_COMMENT_START_PATTERN = re.compile(r"(?<!\\)%")
_VERBATIM_ENV_PATTERN = re.compile(
    r"\\begin\{(verbatim|lstlisting|minted)\*?\}.*?\\end\{\1\*?\}",
    re.DOTALL,
)
_SENTINEL_PATTERN = re.compile(r"\x00(\d+)\x00")


def strip_latex_comments(text: str) -> str:
    """Remove ``%``-to-end-of-line comments outside verbatim-like environments.

    Commented-out draft text is invisible in the compiled PDF, but it still
    gets chunked and sent to the LLM — wasting tokens and, when a draft
    carries protected placeholders the model chooses not to echo back,
    failing chunk validation persistently. Escaped ``\\%`` is kept, and
    verbatim/lstlisting/minted bodies are preserved verbatim: their ``%``
    characters are content, not comments.
    """
    protected: list[str] = []

    def _blank(match: re.Match[str]) -> str:
        protected.append(match.group(0))
        return f"\x00{len(protected) - 1}\x00"

    text = _VERBATIM_ENV_PATTERN.sub(_blank, text)

    lines = []
    for line in text.split("\n"):
        comment = _COMMENT_START_PATTERN.search(line)
        if comment is None:
            lines.append(line)
            continue
        # A comment-only line must be dropped entirely: TeX treats it as no
        # line at all, and replacing it with an empty line would introduce a
        # \par — fatal inside pgfkeys option blocks, where venue templates
        # (appendix comments like "% title=...") commonly carry comment-only
        # lines. A line with content before the comment keeps that content.
        before = line[: comment.start()].rstrip()
        if before:
            lines.append(before)
    text = "\n".join(lines)

    return _SENTINEL_PATTERN.sub(lambda match: protected[int(match.group(1))], text)


def _split_latex_document(source_text: str) -> tuple[str, str, str]:
    matched = _DOCUMENT_BODY_PATTERN.search(source_text)
    if not matched:
        raise ValueError("Expected a complete LaTeX document with \\begin{document} and \\end{document}")
    return matched.group(1), matched.group(2), matched.group(3)


def _end_of_documentclass(prefix: str, start: int) -> int | None:
    """Offset just past the ``\\documentclass`` command starting at ``start``,
    skipping its optional ``[...]`` and required balanced ``{...}`` arguments.
    """
    index = start + len("\\documentclass")
    length = len(prefix)
    while index < length and prefix[index].isspace():
        index += 1
    if index < length and prefix[index] == "[":
        depth = 1
        index += 1
        while index < length and depth:
            if prefix[index] == "]":
                depth -= 1
            index += 1
        while index < length and prefix[index].isspace():
            index += 1
    if index >= length or prefix[index] != "{":
        return None
    depth = 0
    while index < length:
        ch = prefix[index]
        if ch == "{" and not _is_escaped_at(prefix, index):
            depth += 1
        elif ch == "}" and not _is_escaped_at(prefix, index):
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    return None


def _ensure_cjk_support(prefix: str) -> str:
    for match in _CJK_PACKAGE_PATTERN.finditer(prefix):
        # Venue templates list forbidden packages in comments (aaai2027.sty:
        # "% \usepackage{CJK} -- This package is specifically forbidden");
        # only a live declaration counts as existing CJK support.
        line_start = prefix.rfind("\n", 0, match.start()) + 1
        if not _COMMENT_START_PATTERN.search(prefix, line_start, match.start()):
            return prefix
    class_match = _DOCUMENTCLASS_PATTERN.search(prefix)
    if class_match is not None:
        # Load CJK support right after \documentclass. Font packages some
        # venue styles pull in (newtxtext, loaded by aaai2027.sty) break
        # fontspec's font-name resolution for fonts declared after them, so
        # the CJK font must be selected before those packages load — but
        # after the class, which defines the size commands font selection
        # needs.
        end = _end_of_documentclass(prefix, class_match.start())
        if end is not None:
            return prefix[:end] + "\n" + _CJK_EARLY_SNIPPET + prefix[end:]
    begin_doc = "\\begin{document}"
    idx = prefix.rfind(begin_doc)
    if idx == -1:
        return prefix
    return prefix[:idx] + _CJK_PREAMBLE_SNIPPET + prefix[idx:]


_PDF_ONLY_FONT_PACKAGE_PATTERN = re.compile(
    r"^[ \t]*\\usepackage(?:\[[^\]]*\])?\{(?:times|mathptmx|txfonts)\}[ \t]*$",
    re.MULTILINE,
)
_PDF_ONLY_FONT_REPLACEMENT = (
    "% Injected by PaperReader: psnfss Times packages use Type1 metrics that\n"
    "% XeLaTeX cannot fully handle (XeTeXglyph errors); newtxtext provides the\n"
    "% same Times-like text face natively.\n"
    "\\usepackage{newtxtext}\n"
)


def _ensure_xelatex_compatibility(prefix: str) -> str:
    """Make pdfLaTeX-only constructs harmless under XeLaTeX.

    Translated builds always compile with XeLaTeX for CJK output. Three source
    constructs would otherwise fail there:

    - arXiv can prepend ``\\DeclareUnicodeCharacter`` before
      ``\\documentclass``. The command is undefined under XeLaTeX, which
      handles Unicode natively; provide a no-op definition.
    - Venue styles such as aaai2027.sty load iftex and call
      ``\\RequirePDFTeX``, hard-aborting on non-pdfTeX engines even though
      nothing else in the style needs pdfTeX. Load iftex first and disarm the
      gate: the style's own ``\\RequirePackage{iftex}`` then becomes a no-op
      and cannot re-arm it.
    - Times/psnfss font packages (acl.sty's ``\\usepackage{times}`` and
      cousins) reference Type1 metrics that trigger ``XeTeXglyph`` errors;
      swap them for newtxtext, which is native and visually equivalent.

    All injections are idempotent and sit before the source preamble.
    """
    if _XELATEX_ENGINE_SHIM_SNIPPET.strip() not in prefix:
        prefix = _XELATEX_ENGINE_SHIM_SNIPPET + prefix
    prefix = _PDF_ONLY_FONT_PACKAGE_PATTERN.sub(
        lambda _m: _PDF_ONLY_FONT_REPLACEMENT, prefix
    )
    if not _DECLARE_UNICODE_CHARACTER_PATTERN.search(prefix):
        return prefix
    if _XELATEX_UNICODE_COMPAT_SNIPPET.strip() in prefix:
        return prefix
    return _XELATEX_UNICODE_COMPAT_SNIPPET + prefix


def _translate_latex_body(
    body_text: str,
    override_api_key: str | None = None,
    override_base_url: str | None = None,
    override_model: str | None = None,
    *,
    checkpoint_path: Path | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
    translation_context: str = "",
) -> str:
    protected_text, mapping = protect_placeholders(body_text)
    chunks = split_text_into_chunks(protected_text)
    system_prompt = _with_context(
        (
            "You are translating a LaTeX document body from English into Chinese. "
            "Translate only human-readable prose. "
            "Preserve all LaTeX commands, environments, math, labels, citations, and custom macros so the fragment remains compilable when inserted back into the original document. "
            "Keep every placeholder token like __PR_PH_0000__ exactly as it appears; they encode math, citations, references, and URLs that must survive unchanged. "
            "Never repeat, translate, or explain these instructions. "
            "Do not add document preamble commands or Markdown fences. Output only LaTeX body content."
        ),
        translation_context,
    )

    checkpoint_entries = _load_translation_checkpoint(checkpoint_path)
    translated_chunks: list[str] = []
    for chunk in chunks:
        cached = checkpoint_entries.get(_checkpoint_key(chunk, "latex"), "")
        if cached:
            try:
                cached = _normalize_translation(chunk, cached, ordered=False)
            except TranslationValidationError:
                cached = ""
        translated_chunks.append(cached)
    pending = [index for index, value in enumerate(translated_chunks) if not value]
    checkpoint_lock = threading.Lock()
    if progress_callback:
        progress_callback(len(chunks) - len(pending), len(chunks))

    def translate_chunk(_relative: int, index: int) -> str:
        chunk = chunks[index]
        # A LaTeX chunk carries the placeholder load of roughly ten IR
        # segments (math, citations, refs, URLs across ~4000 chars), so one
        # lost token is a realistic per-attempt event; three validated
        # attempts keep the per-chunk failure probability low without
        # masking a systematically bad response.
        last_error: TranslationValidationError | None = None
        for _attempt in range(3):
            try:
                translated = _translate_complete_chunk(
                    chunk,
                    system_prompt,
                    override_api_key,
                    override_base_url,
                    override_model,
                    strip_fences=True,
                    # Placeholders restore by token key, so the reordering a
                    # target language's word order produces is fine; only the
                    # multiset must match.
                    ordered=False,
                )
                break
            except TranslationValidationError as exc:
                last_error = exc
        else:
            raise last_error or TranslationValidationError("invalid translation")
        with checkpoint_lock:
            translated_chunks[index] = translated
            if checkpoint_path is not None:
                checkpoint_entries[_checkpoint_key(chunk, "latex")] = translated
                _save_translation_checkpoint(checkpoint_path, checkpoint_entries)
            if progress_callback:
                progress_callback(sum(bool(value) for value in translated_chunks), len(chunks))
        return translated

    _run_concurrent(
        pending,
        worker=translate_chunk,
        fallback=lambda _relative, index, _exc: _fail_incomplete_translation(index, index, _exc),
    )

    translated = "\n\n".join(part for part in translated_chunks if part)
    return restore_placeholders(translated, mapping)


def translate_latex_document(
    source_text: str,
    override_api_key: str | None = None,
    override_base_url: str | None = None,
    override_model: str | None = None,
    *,
    checkpoint_path: Path | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
    translation_context: str = "",
) -> str:
    prefix, body, suffix = _split_latex_document(source_text)
    body = strip_latex_comments(body)
    prefix = _ensure_xelatex_compatibility(prefix)
    prefix = _ensure_cjk_support(prefix)
    translated = _translate_latex_body(
        body,
        override_api_key=override_api_key,
        override_base_url=override_base_url,
        override_model=override_model,
        checkpoint_path=checkpoint_path,
        progress_callback=progress_callback,
        translation_context=translation_context,
    )
    translated = _strip_code_fences(translated)

    # Be tolerant if the model still returns a full document instead of body-only content.
    try:
        _, translated_body, _ = _split_latex_document(translated)
    except ValueError:
        translated_body = translated

    translated_body, repairs = sanitize_and_repair(translated_body.strip())
    for note in repairs:
        logger.info("Repaired OCR math fault at %s", note)
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
    "i am supposed to translate",
    "i'm supposed to translate",
    "inside these tags",
    "cannot translate",
    "unable to translate",
    "没有实际的待译文本",
    "无法进行翻译",
)

_REFUSAL_FRAGMENTS = (
    "i can't help with that",
    "i cannot comply",
    "as an ai language model",
    "请提供需要翻译",
)
_TRANSLATION_CONTRACT_VERSION = "ir-translation-v2"


class TranslationValidationError(RuntimeError):
    pass


class TranslationChunkError(RuntimeError):
    def __init__(self, index: int, cause: Exception):
        super().__init__(str(cause))
        self.index = index


def _repair_lost_dollar_escapes(source: str, translated: str) -> str:
    """Re-escape literal ``$`` whose backslash the model dropped.

    Real math is placeholder-protected before the model sees a segment, so
    when the source holds no unescaped ``$`` every unescaped ``$`` in the
    output is escaped currency that lost its backslash. Restoring it keeps
    prose such as ``Big & Tall`` out of fake inline math at render time; a
    re-translation could not be relied on here because a temperature-zero
    model reproduces the same corruption deterministically.
    """
    if _UNESCAPED_DOLLAR_RE.search(source) or not _UNESCAPED_DOLLAR_RE.search(translated):
        return translated
    return _UNESCAPED_DOLLAR_RE.sub(r"\\$", translated)


def _normalize_translation(source: str, translated: str, *, ordered: bool = True) -> str:
    """Repair deterministic corruptions first, then validate the result."""
    # U+FFFD carries no recoverable content and renders as a blank glyph in
    # XeLaTeX. Models can also insert it between duplicated neighboring
    # characters (for example 发�现), where removal restores the intended word.
    repaired = translated.replace("\ufffd", "")
    repaired = _repair_lost_dollar_escapes(source, repaired)
    _validate_translation(source, repaired, ordered=ordered)
    return repaired


def _validate_translation(source: str, translated: str, *, ordered: bool = True) -> None:
    """Reject structurally unsafe or clearly non-translation model output.

    ``ordered=False`` compares placeholder tokens as a multiset instead of in
    sequence: callers that restore placeholders by token key (LaTeX body
    chunks) tolerate the reordering a target language's word order produces,
    while the IR path maps translations positionally and needs the sequence.
    """
    if not translated.strip():
        raise TranslationValidationError("empty translation")
    if "```" in translated:
        raise TranslationValidationError("unexpected code fence")
    controls = [ch for ch in translated if ord(ch) < 32 and ch not in "\n\r\t"]
    if controls:
        raise TranslationValidationError("unsafe control character")
    source_tokens = _placeholder_tokens(source)
    translated_tokens = _placeholder_tokens(translated)
    if (source_tokens != translated_tokens if ordered
            else Counter(source_tokens) != Counter(translated_tokens)):
        raise TranslationValidationError("placeholder count or order changed")
    # Real math is placeholder-protected before the model sees a segment, so a
    # source without unescaped ``$`` must never gain one: losing the backslash
    # of ``\$10.99`` would later pair into fake inline math and swallow prose
    # such as ``Big & Tall`` into math mode.
    if not _UNESCAPED_DOLLAR_RE.search(source) and _UNESCAPED_DOLLAR_RE.search(translated):
        raise TranslationValidationError("unescaped '$' introduced (escaped currency/math lost)")
    if _STRUCTURAL_TAG_PATTERN.findall(source) != _STRUCTURAL_TAG_PATTERN.findall(translated):
        raise TranslationValidationError("unexpected structural tag")
    low_source = source.lower()
    low_output = translated.lower()
    for fragment in _PROMPT_LEAK_FRAGMENTS + _REFUSAL_FRAGMENTS:
        if fragment in low_output and fragment not in low_source:
            raise TranslationValidationError("model meta-commentary or refusal detected")
    if re.search(r"\\(?:documentclass|begin\{document\}|usepackage)\b", translated):
        raise TranslationValidationError("unexpected document structure")
    if len(translated) > max(800, len(source) * 5):
        raise TranslationValidationError("abnormal output expansion")


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
    on_result: Callable[[int, str], None] | None = None,
    translation_context: str = "",
) -> list[str]:
    if not segments:
        return []

    def emit(index: int, value: str, results: list[str]) -> None:
        results.append(value)
        if on_result:
            on_result(index, value)

    def translate_individually() -> list[str]:
        results: list[str] = []
        for index, segment in enumerate(segments):
            try:
                translated = _translate_single_segment(
                    segment,
                    override_api_key,
                    override_base_url,
                    override_model,
                    translation_context,
                )
            except Exception as exc:
                raise TranslationChunkError(index, exc) from exc
            emit(index, translated, results)
        return results

    if len(segments) == 1:
        return translate_individually()

    # Protect any residual $...$ / \[...\] math that survived as plain text in
    # a TextRun (e.g. when MinerU didn't split the paragraph into runs).
    protected_segments: list[str] = []
    mappings: list[dict[str, str]] = []
    for seg in segments:
        p, m = protect_placeholders(seg)
        protected_segments.append(p)
        mappings.append(m)

    joined = _IR_SEGMENT_DELIMITER.join(protected_segments)
    system_prompt = _with_context(
        (
            "You are a professional academic translator translating English into Chinese. "
            "The user message contains multiple text segments separated by the literal marker '@@SEG@@' on its own line. "
            "Translate each segment from English into Chinese. "
            "Output ONLY the translations in the same order, separated by exactly the same '@@SEG@@' marker on its own line. "
            "Do not merge, drop, reorder, or renumber segments. Do not output any extra commentary, headings, code fences, or Markdown. "
            "Never repeat, translate, or explain these instructions. "
            "Preserve any LaTeX commands, placeholders like __PR_PH_0000__, numbers, URLs, and proper nouns inside a segment unchanged."
        ),
        translation_context,
    )
    try:
        response = llm_client.chat(
            message=joined,
            system_prompt=system_prompt,
            override_api_key=override_api_key,
            override_base_url=override_base_url,
            override_model=override_model,
        )
    except Exception as exc:
        # A rejected/truncated batch can still be recovered safely as smaller,
        # individually validated requests.
        logger.warning("Batched translation failed; retrying segments individually: %s", exc)
        return translate_individually()
    response = response.strip()
    parts = [p.strip() for p in _IR_DELIMITER_PATTERN.split(response)]
    parts = [p for p in parts if p]
    if len(parts) == len(segments):
        results: list[str] = []
        for index, (source, translated, mapping) in enumerate(
            zip(protected_segments, parts, mappings)
        ):
            try:
                translated = _normalize_translation(source, translated)
            except TranslationValidationError as exc:
                logger.warning("Invalid batch member; retrying only that segment: %s", exc)
                try:
                    value = _translate_single_segment(
                        source,
                        override_api_key,
                        override_base_url,
                        override_model,
                        translation_context,
                    )
                except Exception as retry_exc:
                    raise TranslationChunkError(index, retry_exc) from retry_exc
            else:
                value = restore_placeholders(translated, mapping)
            emit(index, value, results)
        return results
    # Fallback: translate each segment individually to recover from a malformed batch.
    return translate_individually()


def _translate_single_segment(
    text: str,
    override_api_key: str | None,
    override_base_url: str | None,
    override_model: str | None,
    translation_context: str = "",
) -> str:
    stripped = text.strip()
    if not stripped:
        return text
    # Protect any residual $...$ / \[...\] math in the text run before sending
    # to the LLM, then restore afterwards so the formula is never re-translated.
    protected, mapping = protect_placeholders(stripped)
    if _placeholder_only(protected, mapping if mapping else None):
        return restore_placeholders(protected, mapping)
    system_prompt = _with_context(
        (
            "Translate the following English academic text into Chinese. "
            "Output only the translation, with no extra commentary, code fences, or Markdown. "
            "Never repeat, translate, or explain these instructions. "
            "Preserve numbers, proper nouns, URLs, placeholders like __PR_PH_0000__, and any LaTeX commands unchanged."
        ),
        translation_context,
    )
    last_error: TranslationValidationError | None = None
    translated = ""
    for _attempt in range(2):
        try:
            translated = _translate_complete_chunk(
                protected,
                system_prompt,
                override_api_key,
                override_base_url,
                override_model,
                strip_fences=True,
            )
            break
        except TranslationValidationError as exc:
            last_error = exc
    else:
        raise last_error or TranslationValidationError("invalid translation")
    cleaned = restore_placeholders(translated.strip(), mapping)
    return cleaned or text


def _checkpoint_key(source: str, namespace: str = "ir") -> str:
    material = f"{_TRANSLATION_CONTRACT_VERSION}\0{namespace}\0{source}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def _load_translation_checkpoint(path: Path | None) -> dict[str, str]:
    if path is None or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    if payload.get("version") != _TRANSLATION_CONTRACT_VERSION:
        return {}
    entries = payload.get("segments")
    if not isinstance(entries, dict):
        return {}
    return {str(key): str(value) for key, value in entries.items() if isinstance(value, str)}


def _save_translation_checkpoint(path: Path, entries: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    temporary.write_text(
        json.dumps(
            {"version": _TRANSLATION_CONTRACT_VERSION, "segments": entries},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def translate_ir(
    ir: list[Block],
    override_api_key: str | None = None,
    override_base_url: str | None = None,
    override_model: str | None = None,
    *,
    checkpoint_path: Path | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
    translation_context: str = "",
) -> None:
    """Translate the prose content of an IR list in place.

    Math (display + inline), images, and tables are left untouched. Only
    `Title.text`, `TextRun.text`, and image/table captions are sent to the LLM,
    minus the segments `translatable_mask` marks as source-language (the
    bibliography).
    """
    source_segments = collect_translatable_strings(ir)
    if not source_segments:
        return

    # MinerU occasionally emits a whole page as one TextRun. Split each such
    # logical segment before batching, then reassemble it after translation.
    # Placeholders are protected before the split so math/URLs cannot be cut.
    translatable = translatable_mask(ir)
    segments: list[str] = []
    segment_groups: list[tuple[list[int], dict[str, str]]] = []
    max_segment_chars = max(300, int(settings.translate_segment_max_chars))
    for source_index, source in enumerate(source_segments):
        protected, mapping = protect_placeholders(source)
        pieces = split_text_into_chunks(protected, max_chars=max_segment_chars)
        indices = list(range(len(segments), len(segments) + len(pieces)))
        segments.extend(pieces)
        segment_groups.append((indices, mapping))
    piece_translatable = [
        translatable[group_index]
        for group_index, (indices, _mapping) in enumerate(segment_groups)
        for _ in indices
    ]

    checkpoint_entries = _load_translation_checkpoint(checkpoint_path)
    translations: list[str] = [""] * len(segments)
    for index, segment in enumerate(segments):
        if not piece_translatable[index]:
            translations[index] = segment
            continue
        cached = checkpoint_entries.get(_checkpoint_key(segment))
        if cached:
            try:
                cached = _normalize_translation(segment, cached)
            except TranslationValidationError:
                continue
            translations[index] = cached

    pending = [index for index, value in enumerate(translations) if not value]
    relative_batches = _batch_segments(
        [segments[index] for index in pending],
        max(max_segment_chars, settings.translate_batch_max_chars),
    )
    batches = [[pending[index] for index in batch] for batch in relative_batches]
    checkpoint_lock = threading.Lock()
    progress_lock = threading.Lock()
    if progress_callback:
        progress_callback(len(segments) - len(pending), len(segments))

    def _do_batch(_i: int, batch: list[int]) -> str:
        batch_segments = [segments[j] for j in batch]
        def persist_result(relative_index: int, value: str) -> None:
            slot = batch[relative_index]
            value = _normalize_translation(segments[slot], value)
            with checkpoint_lock:
                translations[slot] = value
                if checkpoint_path is not None:
                    checkpoint_entries[_checkpoint_key(segments[slot])] = translations[slot]
                    _save_translation_checkpoint(checkpoint_path, checkpoint_entries)
            if progress_callback:
                with progress_lock:
                    progress_callback(sum(bool(item) for item in translations), len(segments))

        try:
            _translate_segment_batch(
                batch_segments,
                override_api_key=override_api_key,
                override_base_url=override_base_url,
                override_model=override_model,
                on_result=persist_result,
                translation_context=translation_context,
            )
        except TranslationChunkError as exc:
            source_index = batch[exc.index]
            raise RuntimeError(
                f"Translation incomplete: chunk {source_index + 1} failed"
            ) from exc
        return ""

    def _fallback(_i: int, batch: list[int], _exc: Exception) -> str:
        if isinstance(_exc, RuntimeError) and str(_exc).startswith("Translation incomplete: chunk "):
            raise _exc
        return _fail_incomplete_translation(batch[0], batch, _exc)

    _run_concurrent(batches, worker=_do_batch, fallback=_fallback)

    logical_translations: list[str] = []
    for indices, mapping in segment_groups:
        parts = [translations[idx].strip() for idx in indices]
        if any(not part for part in parts):
            raise RuntimeError("Translation incomplete: one or more sub-segments are empty")
        logical_translations.append(restore_placeholders(" ".join(parts), mapping))

    apply_translations(ir, logical_translations)
