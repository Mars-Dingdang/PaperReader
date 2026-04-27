import re
import shutil
import subprocess
from pathlib import Path

from app.core.config import settings
from app.services.mineru_layout import (
    Block,
    DisplayMath,
    Image,
    InlineMath,
    Paragraph,
    Table,
    TextRun,
    Title,
)


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


def compile_tex_project(tex_path: Path, output_dir: Path) -> Path:
    tex_path = tex_path.resolve()
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    command = [
        settings.latexmk_path,
        "-xelatex",
        "-interaction=nonstopmode",
        "-halt-on-error",
        "-output-directory=" + str(output_dir),
        tex_path.name,
    ]
    try:
        subprocess.run(
            command,
            check=True,
            cwd=str(tex_path.parent),
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        log_path = output_dir / f"{tex_path.stem}.log"
        detail = (exc.stderr or exc.stdout or "").strip()
        if len(detail) > 800:
            detail = detail[-800:]
        raise RuntimeError(f"LaTeX compile failed. log={log_path}. details={detail}") from exc

    expected_pdf = output_dir / (tex_path.stem + ".pdf")
    if not expected_pdf.exists():
        raise FileNotFoundError(f"Compiled PDF not found: {expected_pdf}")
    return expected_pdf


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

_TEX_DOCUMENT_TEMPLATE = """\\documentclass[12pt]{{article}}
\\usepackage[UTF8]{{ctex}}
\\usepackage{{amsmath,amssymb,amsfonts}}
\\usepackage{{graphicx}}
\\usepackage{{float}}
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
    parts: list[str] = []
    for run in paragraph.runs:
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


def _render_image(block: Image) -> str:
    rel = _normalize_image_path(block.rel_path)
    if not rel:
        return ""
    caption = _escape_latex_text(block.caption) if block.caption else ""
    caption_line = f"\\caption{{{caption}}}\n" if caption else ""
    return (
        "\\begin{figure}[H]\n"
        "  \\centering\n"
        f"  \\includegraphics[width=0.85\\linewidth]{{{rel}}}\n"
        f"  {caption_line}"
        "\\end{figure}"
    )


def _render_table(block: Table) -> str:
    rel = _normalize_image_path(block.rel_path) if block.rel_path else ""
    caption = _escape_latex_text(block.caption) if block.caption else ""
    caption_line = f"\\caption{{{caption}}}\n" if caption else ""
    if rel:
        return (
            "\\begin{figure}[H]\n"
            "  \\centering\n"
            f"  \\includegraphics[width=0.85\\linewidth]{{{rel}}}\n"
            f"  {caption_line}"
            "\\end{figure}"
        )
    # No image fallback: skip the table to keep the document compilable.
    return ""


def render_ir_to_tex(
    ir: list[Block],
    title: str | None = None,
) -> str:
    """Render an IR list as a complete, compilable LaTeX document."""
    rendered_blocks: list[str] = []
    title_block = ""
    title_consumed = False

    for block in ir:
        if isinstance(block, Title):
            text_escaped = _escape_latex_text(block.text)
            if not title_consumed and block.level <= 1 and not title and not title_block:
                title_block = f"\\title{{{text_escaped}}}\n\\maketitle\n\n"
                title_consumed = True
                continue
            command = _level_to_section_command(block.level)
            rendered_blocks.append(f"{command}{{{text_escaped}}}")
        elif isinstance(block, Paragraph):
            rendered = _render_paragraph(block)
            if rendered:
                rendered_blocks.append(rendered)
        elif isinstance(block, DisplayMath):
            latex = block.latex.strip()
            if latex:
                rendered_blocks.append(f"\\[\n{latex}\n\\]")
        elif isinstance(block, Image):
            rendered = _render_image(block)
            if rendered:
                rendered_blocks.append(rendered)
        elif isinstance(block, Table):
            rendered = _render_table(block)
            if rendered:
                rendered_blocks.append(rendered)

    if title and title.strip() and not title_block:
        title_block = f"\\title{{{_escape_latex_text(title.strip())}}}\n\\maketitle\n\n"

    body = "\n\n".join(rendered_blocks).strip() + "\n"
    return _TEX_DOCUMENT_TEMPLATE.format(title_block=title_block, body=body)


def create_translated_tex_from_ir(
    ir: list[Block],
    out_tex_path: Path,
    images_src_dir: Path | None = None,
    title: str | None = None,
) -> None:
    """Write `translated.tex` from an IR list and copy `images/` next to it."""
    out_tex_path.parent.mkdir(parents=True, exist_ok=True)
    tex = render_ir_to_tex(ir, title=title)
    out_tex_path.write_text(tex, encoding="utf-8")

    if images_src_dir and images_src_dir.is_dir():
        target = out_tex_path.parent / "images"
        if target.resolve() != images_src_dir.resolve():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(images_src_dir, target)
