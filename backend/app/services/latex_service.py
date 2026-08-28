import logging
import re
import shutil
import subprocess
from pathlib import Path

from app.core.config import settings
from app.services.latex_sanitizer import sanitize_latex_body
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


_HEADING_PATTERN = re.compile(r"^(#{2,4})\s+(.+)$", re.MULTILINE)
_BOLD_PATTERN = re.compile(r"\*\*(.+?)\*\*")
_ITALIC_PATTERN = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")
_NUMBERED_PATTERN = re.compile(r"^\s*\d+[\.)]\s+(.+)$", re.MULTILINE)
_BULLET_PATTERN = re.compile(r"^\s*[-*]\s+(.+)$", re.MULTILINE)


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
    """

    def __init__(self, pdf_path: Path, warning: str | None = None) -> None:
        self.pdf_path = pdf_path
        self.warning = warning


def _run_latexmk(tex_path: Path, output_dir: Path, *, force: bool) -> subprocess.CompletedProcess[str]:
    command = [
        settings.latexmk_path,
        "-xelatex",
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
        # latexmk/xelatex emit UTF-8 (e.g. Chinese from ctex, CJK filenames,
        # echoed source lines in warnings). The Windows default locale is GBK,
        # which crashes subprocess' reader thread with UnicodeDecodeError and
        # yields empty error output. Pin UTF-8 and tolerate stray bytes.
        encoding="utf-8",
        errors="replace",
    )


def compile_tex_project_with_fallback(tex_path: Path, output_dir: Path) -> LatexCompileResult:
    """Compile with strict mode first; if it fails, retry with `-f`.

    A lenient pass is accepted only when latexmk exits successfully and the
    expected PDF exists. XeLaTeX can write an incomplete PDF before returning
    an error, and treating that artifact as success truncates whole papers.
    """
    tex_path = tex_path.resolve()
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    expected_pdf = output_dir / (tex_path.stem + ".pdf")

    # Never let a stale or partially written PDF from an earlier failed pass
    # masquerade as the result of this compile attempt.
    expected_pdf.unlink(missing_ok=True)

    strict = _run_latexmk(tex_path, output_dir, force=False)
    if strict.returncode == 0 and expected_pdf.exists():
        return LatexCompileResult(expected_pdf)

    strict_detail = (strict.stderr or strict.stdout or "").strip()
    if len(strict_detail) > 800:
        strict_detail = strict_detail[-800:]
    log_path = output_dir / f"{tex_path.stem}.log"
    logger.warning("latexmk strict pass failed (rc=%s); retrying with -f", strict.returncode)

    # A failed strict XeLaTeX pass may already have emitted a truncated PDF.
    # Remove it so only a fresh, successful lenient pass can satisfy the gate.
    expected_pdf.unlink(missing_ok=True)
    lenient = _run_latexmk(tex_path, output_dir, force=True)
    if lenient.returncode == 0 and expected_pdf.exists():
        warning = (
            f"LaTeX strict compile failed but a PDF was produced via -f. "
            f"log={log_path}. strict_details={strict_detail}"
        )
        logger.warning(warning)
        return LatexCompileResult(expected_pdf, warning=warning)

    detail = (lenient.stderr or lenient.stdout or strict_detail or "").strip()
    if len(detail) > 800:
        detail = detail[-800:]
    raise RuntimeError(f"LaTeX compile failed. log={log_path}. details={detail}")


def compile_tex_project(tex_path: Path, output_dir: Path) -> Path:
    """Backwards-compatible wrapper that returns just the PDF path."""
    return compile_tex_project_with_fallback(tex_path, output_dir).pdf_path


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
    out = text
    for src, dst in _LATEX_TEXT_ESCAPES:
        out = out.replace(src, dst)
    return out


def create_translated_tex(source_text: str, out_tex_path: Path, title: str | None = None) -> None:
    out_tex_path.parent.mkdir(parents=True, exist_ok=True)
    body = _markdown_to_latex_fallback(source_text)
    body = sanitize_latex_body(body)
    title_block = ""
    if title and title.strip():
        title_text = _escape_latex_text(title.strip())
        title_block = f"\\title{{{title_text}}}\n\\maketitle\n"
    content = f"""
\\documentclass[12pt]{{article}}
\\usepackage[UTF8]{{ctex}}
\\usepackage{{amsmath,amssymb,graphicx,hyperref}}
\\begin{{document}}
{title_block}{body}
\\end{{document}}
""".strip()
    out_tex_path.write_text(content, encoding="utf-8")


def copy_pdf_to_output(source_pdf: Path, output_pdf: Path) -> None:
    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    if source_pdf.resolve() == output_pdf.resolve():
        return
    shutil.copyfile(source_pdf, output_pdf)


# ---------------------------------------------------------------------------
# IR-based rendering (preferred path for MinerU structured output)
# ---------------------------------------------------------------------------

_TEX_DOCUMENT_TEMPLATE = """\\documentclass[{documentclass_opts}]{{article}}
\\usepackage[UTF8]{{ctex}}
\\usepackage{{amsmath,amssymb,amsfonts,mathrsfs}}
\\usepackage{{graphicx}}
\\usepackage{{float}}
\\usepackage{{caption}}
\\usepackage{{hyperref}}
\\graphicspath{{{{./images/}}}}
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
        documentclass_opts=documentclass_opts, title_block=title_block, body=body
    )


def create_translated_tex_from_ir(
    ir: list[Block],
    out_tex_path: Path,
    images_src_dir: Path | None = None,
    title: str | None = None,
    authors: str | None = None,
    two_column: bool = False,
) -> None:
    """Write `translated.tex` from an IR list and copy `images/` next to it."""
    out_tex_path.parent.mkdir(parents=True, exist_ok=True)
    tex = render_ir_to_tex(
        ir, title=title, authors=authors, two_column=two_column
    )
    tex = sanitize_latex_body(tex)
    out_tex_path.write_text(tex, encoding="utf-8")

    if images_src_dir and images_src_dir.is_dir():
        target = out_tex_path.parent / "images"
        if target.resolve() != images_src_dir.resolve():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(images_src_dir, target)
