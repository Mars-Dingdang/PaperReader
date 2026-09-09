import json
import logging
import re
import shutil
import subprocess
import sys
from pathlib import Path

from app.core.config import settings
from app.services.latex_sanitizer import sanitize_and_repair
from app.services.mineru_layout import (
    Author,
    Block,
    DisplayMath,
    Image,
    InlineMath,
    ListBlock,
    Paragraph,
    Table,
    TextRun,
    Title,
)

logger = logging.getLogger(__name__)

# The packaged desktop app runs windowed (no console). On Windows, spawning a
# console-subsystem child (latexmk, xelatex, bibtex) from a console-less
# process makes each child flash its own terminal window at the user. This
# flag prevents the child from receiving a visible console window. POSIX has
# no equivalent flag, so it degrades to the default 0 there.
CREATION_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


_HEADING_PATTERN = re.compile(r"^(#{2,4})\s+(.+)$", re.MULTILINE)
_BOLD_PATTERN = re.compile(r"\*\*(.+?)\*\*")
_ITALIC_PATTERN = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")
_NUMBERED_PATTERN = re.compile(r"^\s*\d+[\.)]\s+(.+)$", re.MULTILINE)
_BULLET_PATTERN = re.compile(r"^\s*[-*]\s+(.+)$", re.MULTILINE)
_TEX_PROGRAM_PATTERN = re.compile(
    r"^\s*%\s*!\s*TEX\s+program\s*=\s*([^\s]+)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_DEFAULT_LATEX_COMPILER = "xelatex"
_LATEXMK_ENGINE_FLAGS = {
    "pdflatex": "-pdf",
    "xelatex": "-xelatex",
    "lualatex": "-lualatex",
    "latex": "-pdfdvi",
}
# Translated documents always carry injected xeCJK/ctex preamble support
# (translate_service._ensure_cjk_support / the ctex templates), which only
# compiles under XeLaTeX. A source project's declared compiler applies to the
# original document only, never to the translated one.
TRANSLATED_LATEX_COMPILER = "xelatex"


def _markdown_to_latex_fallback(text: str) -> str:
    def heading_repl(match: re.Match[str]) -> str:
        marks = match.group(1)
        title = match.group(2).strip()
        if len(marks) == 2:
            return f"\\section{{{title}}}"
        if len(marks) == 3:
            return f"\\subsection{{{title}}}"
        return f"\\subsubsection{{{title}}}"

    converted = _HEADING_PATTERN.sub(heading_repl, text)
    converted = _BOLD_PATTERN.sub(r"\\textbf{\1}", converted)
    converted = _ITALIC_PATTERN.sub(r"\\textit{\1}", converted)

    lines = converted.splitlines()
    result: list[str] = []
    list_mode: str | None = None

    def close_list() -> None:
        nonlocal list_mode
        if list_mode is not None:
            result.append(f"\\end{{{list_mode}}}")
            list_mode = None

    for line in lines:
        numbered = _NUMBERED_PATTERN.match(line)
        bullet = _BULLET_PATTERN.match(line)

        if numbered:
            if list_mode != "enumerate":
                close_list()
                result.append("\\begin{enumerate}")
                list_mode = "enumerate"
            result.append(f"\\item {numbered.group(1).strip()}")
            continue

        if bullet:
            if list_mode != "itemize":
                close_list()
                result.append("\\begin{itemize}")
                list_mode = "itemize"
            result.append(f"\\item {bullet.group(1).strip()}")
            continue

        if line.strip() == "":
            close_list()
            result.append("")
            continue

        close_list()
        result.append(line)

    close_list()
    return "\n".join(result)


class LatexCompileResult:
    """Outcome of a (possibly fallback) LaTeX compilation.

    `warning` is set when the strict pass failed but a successful lenient
    `-f` pass produced a PDF; it contains the original strict-mode error
    detail so the UI can surface it without aborting the pipeline.

    `errors` (``[{line, message}]``) and `missing_chars`
    (``[{char, codepoint, count, suggest}]``) are parsed from the TeX log so
    callers can surface precise, actionable diagnostics.
    """

    def __init__(
        self,
        pdf_path: Path,
        warning: str | None = None,
        *,
        errors: list[dict] | None = None,
        missing_chars: list[dict] | None = None,
    ) -> None:
        self.pdf_path = pdf_path
        self.warning = warning
        self.errors = errors or []
        self.missing_chars = missing_chars or []


def _normalize_latex_compiler(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    compiler = value.strip().replace("\\", "/").rsplit("/", 1)[-1].lower()
    if compiler.endswith(".exe"):
        compiler = compiler[:-4]
    if compiler in _LATEXMK_ENGINE_FLAGS:
        return compiler
    return None


def _declared_latex_compiler(tex_path: Path) -> str | None:
    """Return a supported compiler explicitly declared by the source project.

    arXiv source archives may include ``00README.json`` with
    ``process.compiler``. Standalone TeX files commonly use a
    ``% !TeX program = ...`` magic comment. Metadata is treated as data only:
    compiler names must match the allowlist above before they can affect the
    latexmk command line.
    """
    metadata_path = tex_path.parent / "00README.json"
    if metadata_path.is_file():
        try:
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            logger.warning("Could not read LaTeX compiler metadata %s: %s", metadata_path, exc)
        else:
            process = payload.get("process") if isinstance(payload, dict) else None
            raw_compiler = process.get("compiler") if isinstance(process, dict) else None
            compiler = _normalize_latex_compiler(raw_compiler)
            if compiler:
                return compiler
            if raw_compiler:
                logger.warning(
                    "Ignoring unsupported LaTeX compiler declaration %r in %s",
                    raw_compiler,
                    metadata_path,
                )

    try:
        with tex_path.open("r", encoding="utf-8", errors="replace") as source:
            source_head = source.read(8192)
    except OSError as exc:
        logger.warning("Could not inspect LaTeX compiler declaration in %s: %s", tex_path, exc)
        return None

    match = _TEX_PROGRAM_PATTERN.search(source_head)
    if not match:
        return None
    compiler = _normalize_latex_compiler(match.group(1))
    if compiler:
        return compiler
    logger.warning("Ignoring unsupported TeX program declaration %r in %s", match.group(1), tex_path)
    return None


def _latexmk_engine_flag(tex_path: Path, compiler: str | None = None) -> str:
    engine = compiler or _declared_latex_compiler(tex_path) or _DEFAULT_LATEX_COMPILER
    return _LATEXMK_ENGINE_FLAGS[engine]


def _run_latexmk(
    tex_path: Path,
    output_dir: Path,
    *,
    force: bool,
    compiler: str | None = None,
) -> subprocess.CompletedProcess[str]:
    engine_flag = _latexmk_engine_flag(tex_path, compiler)
    command = [
        settings.latexmk_path,
        engine_flag,
        "-interaction=nonstopmode",
        "-output-directory=" + str(output_dir),
    ]
    if force:
        command.append("-f")
    else:
        command.append("-halt-on-error")
    command.append(tex_path.name)
    return subprocess.run(
        command,
        check=False,
        cwd=str(tex_path.parent),
        capture_output=True,
        text=True,
        creationflags=CREATION_FLAGS,
        # TeX engines emit UTF-8 (e.g. Chinese from ctex, CJK filenames,
        # echoed source lines in warnings). The Windows default locale is GBK,
        # which crashes subprocess' reader thread with UnicodeDecodeError and
        # yields empty error output. Pin UTF-8 and tolerate stray bytes.
        encoding="utf-8",
        errors="replace",
    )


_LOG_LINE_REF_RE = re.compile(r"^l\.(\d+)")
_LOG_MISSING_CHAR_RE = re.compile(r"Missing character: There is no (.+?) \(U\+([0-9A-Fa-f]+)\)")


def parse_latex_log_issues(log_path: Path) -> tuple[list[dict], list[dict]]:
    """Extract actionable diagnostics from a TeX engine .log file.

    Returns ``(errors, missing_chars)`` where errors are
    ``{"line": int | None, "message": str}`` from fatal ``!`` lines (with the
    ``l.<n>`` source line echoed right after them) and missing_chars are
    ``{"char", "codepoint", "count", "suggest"}`` aggregated from
    ``Missing character`` warnings.
    """
    errors: list[dict] = []
    missing: dict[str, dict] = {}
    try:
        content = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return errors, list(missing.values())

    from app.services.latex_sanitizer import replacement_for

    lines = content.splitlines()
    seen: set[tuple[int | None, str]] = set()
    for idx, line in enumerate(lines):
        fatal = re.match(r"^!\s+(.+?)\s*$", line)
        if fatal:
            tex_line: int | None = None
            for follow in lines[idx + 1 : idx + 6]:
                line_ref = _LOG_LINE_REF_RE.match(follow)
                if line_ref:
                    tex_line = int(line_ref.group(1))
                    break
            key = (tex_line, fatal.group(1))
            if key not in seen and len(errors) < 20:
                seen.add(key)
                errors.append({"line": tex_line, "message": fatal.group(1)})

        for miss in _LOG_MISSING_CHAR_RE.finditer(line):
            ch = miss.group(1) or " "
            entry = missing.setdefault(
                ch,
                {
                    "char": ch,
                    "codepoint": f"U+{miss.group(2)}",
                    "count": 0,
                    "suggest": replacement_for(ch),
                },
            )
            entry["count"] += 1
    return errors, list(missing.values())


def _summarize_missing_chars(missing_chars: list[dict]) -> str:
    parts = []
    for entry in missing_chars:
        piece = f"{entry['char']!r} ({entry['codepoint']}) x{entry['count']}"
        if entry.get("suggest"):
            piece += f" -> replace with ${entry['suggest']}$"
        parts.append(piece)
    return "; ".join(parts)


def compile_tex_project_with_fallback(
    tex_path: Path,
    output_dir: Path,
    *,
    compiler: str | None = None,
) -> LatexCompileResult:
    """Compile with strict mode first; if it fails, retry with `-f`.

    A lenient pass is accepted only when latexmk exits successfully and the
    expected PDF exists. A TeX engine can write an incomplete PDF before
    returning an error, and treating that artifact as success truncates whole
    papers.

    ``compiler`` forces the TeX engine, overriding any declaration in the
    source project (pass ``TRANSLATED_LATEX_COMPILER`` for translated
    documents); ``None`` honors the declared compiler or the default.
    """
    tex_path = tex_path.resolve()
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    expected_pdf = output_dir / (tex_path.stem + ".pdf")
    fdb_path = output_dir / f"{tex_path.stem}.fdb_latexmk"
    log_path = output_dir / f"{tex_path.stem}.log"

    # Never let a stale or partially written PDF from an earlier failed pass
    # masquerade as the result of this compile attempt.
    expected_pdf.unlink(missing_ok=True)
    # A .fdb_latexmk from an earlier attempt records the previous run's error
    # state; latexmk would then run zero rules ("Nothing to do") and merely
    # re-report the cached error instead of actually compiling.
    fdb_path.unlink(missing_ok=True)

    strict = _run_latexmk(tex_path, output_dir, force=False, compiler=compiler)
    if strict.returncode == 0 and expected_pdf.exists():
        errors, missing_chars = parse_latex_log_issues(log_path)
        warning = None
        if missing_chars:
            warning = (
                f"PDF compiled, but {len(missing_chars)} character(s) are missing "
                f"from the font and render as blank: {_summarize_missing_chars(missing_chars)}"
            )
            logger.warning(warning)
        return LatexCompileResult(expected_pdf, warning=warning, errors=errors, missing_chars=missing_chars)

    strict_detail = (strict.stderr or strict.stdout or "").strip()
    if len(strict_detail) > 800:
        strict_detail = strict_detail[-800:]
    logger.warning("latexmk strict pass failed (rc=%s); retrying with -f", strict.returncode)

    # A failed strict TeX pass may already have emitted a truncated PDF.
    # Remove it so only a fresh, successful lenient pass can satisfy the gate,
    # and drop the strict pass's error state from the fdb so the retry
    # actually reruns the rules instead of declaring everything up-to-date.
    expected_pdf.unlink(missing_ok=True)
    fdb_path.unlink(missing_ok=True)
    lenient = _run_latexmk(tex_path, output_dir, force=True, compiler=compiler)
    if lenient.returncode == 0 and expected_pdf.exists():
        errors, missing_chars = parse_latex_log_issues(log_path)
        warning = (
            f"LaTeX strict compile failed but a PDF was produced via -f. "
            f"log={log_path}. strict_details={strict_detail}"
        )
        if missing_chars:
            warning += f" Missing glyphs: {_summarize_missing_chars(missing_chars)}"
        logger.warning(warning)
        return LatexCompileResult(
            expected_pdf, warning=warning, errors=errors, missing_chars=missing_chars
        )

    lenient_detail = (lenient.stderr or lenient.stdout or "").strip()
    if len(lenient_detail) > 800:
        lenient_detail = lenient_detail[-800:]

    # Prefer a structured digest of the log (fatal errors with source line
    # numbers, missing glyphs) over the raw subprocess tail, which is usually
    # flooded by "Missing character" warnings that hide the real error.
    errors, missing_chars = parse_latex_log_issues(log_path)
    parts = [f"LaTeX compile failed. log={log_path}"]
    if errors:
        digest = "; ".join(
            f"L{e['line']}: {e['message']}" if e.get("line") else str(e["message"])
            for e in errors[:5]
        )
        parts.append(f"errors: {digest}")
    if missing_chars:
        parts.append(f"missing glyphs: {_summarize_missing_chars(missing_chars)}")
    if not errors and not missing_chars:
        detail = " | ".join(part for part in (strict_detail, lenient_detail) if part)
        parts.append(f"details={detail}")
    raise RuntimeError(". ".join(parts))


def compile_tex_project(tex_path: Path, output_dir: Path, *, compiler: str | None = None) -> Path:
    """Backwards-compatible wrapper that returns just the PDF path."""
    return compile_tex_project_with_fallback(tex_path, output_dir, compiler=compiler).pdf_path


_LATEX_TEXT_ESCAPES = (
    ("\\", "\\textbackslash{}"),
    ("&", "\\&"),
    ("%", "\\%"),
    ("$", "\\$"),
    ("#", "\\#"),
    ("_", "\\_"),
    ("{", "\\{"),
    ("}", "\\}"),
    ("~", "\\textasciitilde{}"),
    ("^", "\\textasciicircum{}"),
)


def _escape_latex_text(text: str) -> str:
    escape_map = dict(_LATEX_TEXT_ESCAPES)
    out: list[str] = []
    index = 0
    while index < len(text):
        # MinerU commonly emits currency as ``\$``. Preserve the already
        # escaped pair instead of escaping its backslash a second time.
        if text.startswith(r"\$", index):
            out.append(r"\$")
            index += 2
            continue
        ch = text[index]
        out.append(escape_map.get(ch, ch))
        index += 1
    return "".join(out)


def create_translated_tex(source_text: str, out_tex_path: Path, title: str | None = None) -> list[str]:
    """Write a translated .tex from markdown fallback text.

    Returns the list of OCR math-fault repair notes (empty when nothing had
    to be fixed).
    """
    out_tex_path.parent.mkdir(parents=True, exist_ok=True)
    body = _markdown_to_latex_fallback(source_text)
    body, repairs = sanitize_and_repair(body)
    title_block = ""
    if title and title.strip():
        title_text = _escape_latex_text(title.strip())
        title_block = f"\\title{{{title_text}}}\n\\maketitle\n"
    content = f"""
\\documentclass[12pt]{{article}}
\\usepackage[UTF8]{{ctex}}
\\usepackage{{amsmath,amssymb,graphicx,hyperref}}
{_UNICODE_FALLBACK_PREAMBLE}\\begin{{document}}
{title_block}{body}
\\end{{document}}
""".strip()
    out_tex_path.write_text(content, encoding="utf-8")
    return repairs


def copy_pdf_to_output(source_pdf: Path, output_pdf: Path) -> None:
    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    if source_pdf.resolve() == output_pdf.resolve():
        return
    shutil.copyfile(source_pdf, output_pdf)


# ---------------------------------------------------------------------------
# IR-based rendering (preferred path for MinerU structured output)
# ---------------------------------------------------------------------------

# Safety net for Unicode symbols that Latin Modern lacks (proof marks like
# □, bullets, stars, check marks …). Two layers:
#   1. explicit \newunicodechar mappings for the most common proof symbols;
#   2. \xeCJKDeclareCharClass routes whole symbol blocks (geometric shapes,
#      misc symbols, dingbats) to the CJK font, which covers them via
#      GB2312 — this catches anything the curated list misses, including
#      characters the user types later in the TeX editor.
# Valid because translated documents always compile with XeLaTeX + ctex
# (which loads xeCJK).
_UNICODE_FALLBACK_PREAMBLE = """\\usepackage{newunicodechar}
\\newunicodechar{□}{\\ensuremath{\\square}}
\\newunicodechar{■}{\\ensuremath{\\blacksquare}}
\\newunicodechar{●}{\\ensuremath{\\bullet}}
\\newunicodechar{○}{\\ensuremath{\\circ}}
\\newunicodechar{★}{\\ensuremath{\\bigstar}}
\\newunicodechar{☆}{\\ensuremath{\\bigstar}}
\\newunicodechar{✓}{\\ensuremath{\\checkmark}}
\\newunicodechar{✗}{\\ensuremath{\\times}}
\\xeCJKDeclareCharClass{CJK}{"25A0 -> "25FF, "2600 -> "26FF, "2700 -> "27BF}
"""

_TEX_DOCUMENT_TEMPLATE = """\\documentclass[{documentclass_opts}]{{article}}
\\usepackage[UTF8]{{ctex}}
\\usepackage{{amsmath,amssymb,amsfonts,mathrsfs}}
\\usepackage{{graphicx}}
\\usepackage{{float}}
\\usepackage{{caption}}
\\usepackage{{hyperref}}
{unicode_fallback}\\graphicspath{{{{./images/}}}}
\\begin{{document}}
{title_block}{body}
\\end{{document}}
"""


def _level_to_section_command(level: int) -> str:
    if level <= 1:
        return "\\section*"
    if level == 2:
        return "\\subsection*"
    return "\\subsubsection*"


def _normalize_image_path(rel_path: str) -> str:
    rel_path = rel_path.replace("\\", "/").lstrip("./")
    if rel_path.startswith("images/"):
        rel_path = rel_path[len("images/"):]
    return rel_path


def _render_paragraph(paragraph: Paragraph) -> str:
    return _render_runs(paragraph.runs)


def _render_runs(runs: list[TextRun | InlineMath]) -> str:
    parts: list[str] = []
    for run in runs:
        if isinstance(run, TextRun):
            text = run.text
            if not text:
                continue
            parts.append(_escape_latex_text(text))
        elif isinstance(run, InlineMath):
            latex = run.latex.strip()
            if latex:
                parts.append(f"${latex}$")
    rendered = "".join(parts).strip()
    return rendered


def _render_list(block: ListBlock) -> str:
    rendered_items = [_render_runs(item) for item in block.items]
    rendered_items = [item for item in rendered_items if item]
    if not rendered_items:
        return ""

    # Reference entries already carry labels such as ``[12]``. Rendering
    # those as an enumerate environment would duplicate/re-number labels, so
    # preserve them as consecutive paragraphs. Other MinerU list types use a
    # normal LaTeX list environment.
    if block.list_type == "reference_list":
        return "\n\n".join(f"\\noindent {item}\\par" for item in rendered_items)

    ordered = "ordered" in block.list_type or "number" in block.list_type
    environment = "enumerate" if ordered else "itemize"
    items = "\n".join(f"  \\item {item}" for item in rendered_items)
    return f"\\begin{{{environment}}}\n{items}\n\\end{{{environment}}}"


def _render_image(block: Image) -> str:
    rel = _normalize_image_path(block.rel_path)
    if not rel:
        return ""
    caption = block.caption
    caption = _escape_latex_text(caption) if caption else ""
    caption_line = f"\\caption*{{{caption}}}\n" if caption else ""
    return (
        "\\begin{figure}[H]\n"
        "  \\centering\n"
        f"  \\includegraphics[width=0.90\\linewidth,height=0.68\\textheight,keepaspectratio]{{{rel}}}\n"
        f"  {caption_line}"
        "\\end{figure}"
    )


_GROUP_CAPTION_RE = re.compile(
    r"(?P<caption>(?:Figure|Fig\.?|图)\s*\d+\s*[:：].*)",
    re.IGNORECASE | re.DOTALL,
)


def _split_group_caption(caption: str) -> tuple[str, str]:
    """Separate a panel caption from the overall figure caption."""
    match = _GROUP_CAPTION_RE.search(caption)
    if not match:
        return caption.strip(), ""
    panel = caption[:match.start()].strip()
    return panel, match.group("caption").strip()


def _images_share_source_row(left: Image, right: Image) -> bool:
    """Whether adjacent MinerU image/chart blocks form one panel row."""
    if left.page_index < 0 or left.page_index != right.page_index:
        return False
    if left.bbox is None or right.bbox is None:
        return False
    lx0, ly0, lx1, ly1 = left.bbox
    rx0, ry0, rx1, ry1 = right.bbox
    overlap = min(ly1, ry1) - max(ly0, ry0)
    min_height = min(ly1 - ly0, ry1 - ry0)
    if overlap <= 0 or overlap / min_height < 0.60:
        return False
    # Panels should be laid out left-to-right and close enough to plausibly
    # belong to one figure rather than unrelated page decorations.
    gap = rx0 - lx1
    max_width = max(lx1 - lx0, rx1 - rx0)
    return gap >= -5 and gap <= max_width * 0.35


def _render_image_group(blocks: list[Image]) -> str:
    """Restore a MinerU-split multi-panel figure as one LaTeX figure."""
    if len(blocks) == 1:
        return _render_image(blocks[0])

    width = 0.48 if len(blocks) == 2 else 0.31
    panels: list[str] = []
    overall_caption = ""
    for block in blocks:
        rel = _normalize_image_path(block.rel_path)
        if not rel:
            continue
        panel_caption, group_caption = _split_group_caption(block.caption)
        if group_caption:
            overall_caption = group_caption
        caption_line = ""
        if panel_caption:
            caption_line = f"    \\caption*{{{_escape_latex_text(panel_caption)}}}\n"
        panels.append(
            f"  \\begin{{minipage}}[t]{{{width:.2f}\\linewidth}}\n"
            "    \\centering\n"
            f"    \\includegraphics[width=\\linewidth,height=0.52\\textheight,keepaspectratio]{{{rel}}}\n"
            f"{caption_line}"
            "  \\end{minipage}"
        )

    if not panels:
        return ""
    caption_line = ""
    if overall_caption:
        caption_line = f"\n  \\caption*{{{_escape_latex_text(overall_caption)}}}"
    return (
        "\\begin{figure}[H]\n"
        "  \\centering\n"
        + "\n  \\hfill\n".join(panels)
        + caption_line
        + "\n\\end{figure}"
    )


def _render_table(block: Table) -> str:
    rel = _normalize_image_path(block.rel_path) if block.rel_path else ""
    caption = block.caption
    caption = _escape_latex_text(caption) if caption else ""
    caption_line = f"\\caption*{{{caption}}}\n" if caption else ""
    if rel:
        return (
            "\\begin{figure}[H]\n"
            "  \\centering\n"
            f"  \\includegraphics[width=0.90\\linewidth,height=0.68\\textheight,keepaspectratio]{{{rel}}}\n"
            f"  {caption_line}"
            "\\end{figure}"
        )
    # No image fallback: skip the table to keep the document compilable.
    return ""


def _render_author(text: str) -> str:
    """Render an author/affiliation string, converting `<sup>`/`<sub>` HTML to
    LaTeX while escaping the surrounding plain text (but not the commands)."""
    def _esc(value: str) -> str:
        return _escape_latex_text(value)

    pattern = re.compile(r"<(sup|sub)>(.*?)</\1>", re.IGNORECASE)
    parts: list[str] = []
    last = 0
    for match in pattern.finditer(text):
        parts.append(_esc(text[last:match.start()]))
        tag, inner = match.group(1).lower(), match.group(2)
        command = "textsuperscript" if tag == "sup" else "textsubscript"
        parts.append(f"\\{command}{{{_esc(inner.strip())}}}")
        last = match.end()
    parts.append(_esc(text[last:]))
    return re.sub(r"<[^>]+>", "", "".join(parts)).strip()


def render_ir_to_tex(
    ir: list[Block],
    title: str | None = None,
    authors: str | None = None,
    two_column: bool = False,
) -> str:
    """Render an IR list as a complete, compilable LaTeX document."""
    rendered_blocks: list[str] = []
    paper_title: str | None = None
    paper_authors: str | None = authors

    index = 0
    while index < len(ir):
        block = ir[index]
        if isinstance(block, Title):
            text_escaped = _escape_latex_text(block.text)
            if paper_title is None and block.level <= 1:
                paper_title = block.text
            else:
                command = _level_to_section_command(block.level)
                rendered_blocks.append(f"{command}{{{text_escaped}}}")
        elif isinstance(block, Author):
            if paper_authors is None:
                paper_authors = block.text
        elif isinstance(block, Paragraph):
            rendered = _render_paragraph(block)
            if rendered:
                rendered_blocks.append(rendered)
        elif isinstance(block, ListBlock):
            rendered = _render_list(block)
            if rendered:
                rendered_blocks.append(rendered)
        elif isinstance(block, DisplayMath):
            latex = block.latex.strip()
            if latex:
                rendered_blocks.append(f"\\[\n{latex}\n\\]")
        elif isinstance(block, Image):
            image_group = [block]
            cursor = index + 1
            while (
                cursor < len(ir)
                and isinstance(ir[cursor], Image)
                and _images_share_source_row(image_group[-1], ir[cursor])
            ):
                image_group.append(ir[cursor])
                cursor += 1
            rendered = _render_image_group(image_group)
            if rendered:
                rendered_blocks.append(rendered)
            index = cursor - 1
        elif isinstance(block, Table):
            rendered = _render_table(block)
            if rendered:
                rendered_blocks.append(rendered)

        index += 1

    if title and title.strip():
        paper_title = paper_title or title.strip()

    title_block = ""
    if paper_title:
        title_block = f"\\title{{{_escape_latex_text(paper_title.strip())}}}\n"
        if paper_authors and paper_authors.strip():
            title_block += f"\\author{{{_render_author(paper_authors)}}}\n"
        title_block += "\\date{}\n\\maketitle\n\n"

    body = "\n\n".join(rendered_blocks).strip() + "\n"
    documentclass_opts = "10pt,twocolumn" if two_column else "12pt"
    return _TEX_DOCUMENT_TEMPLATE.format(
        documentclass_opts=documentclass_opts,
        unicode_fallback=_UNICODE_FALLBACK_PREAMBLE,
        title_block=title_block,
        body=body,
    )


def create_translated_tex_from_ir(
    ir: list[Block],
    out_tex_path: Path,
    images_src_dir: Path | None = None,
    title: str | None = None,
    authors: str | None = None,
    two_column: bool = False,
) -> list[str]:
    """Write `translated.tex` from an IR list and copy `images/` next to it.

    Returns the list of OCR math-fault repair notes (empty when the rendered
    document needed no fixing).
    """
    out_tex_path.parent.mkdir(parents=True, exist_ok=True)
    tex = render_ir_to_tex(
        ir, title=title, authors=authors, two_column=two_column
    )
    tex, repairs = sanitize_and_repair(tex)
    out_tex_path.write_text(tex, encoding="utf-8")

    if images_src_dir and images_src_dir.is_dir():
        target = out_tex_path.parent / "images"
        if target.resolve() != images_src_dir.resolve():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(images_src_dir, target)

    return repairs
