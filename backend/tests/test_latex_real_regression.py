import shutil

import pytest

from app.core.config import settings
from app.services.latex_service import (
    TRANSLATED_LATEX_COMPILER,
    _run_latexmk,
    compile_tex_project_with_fallback,
    create_translated_tex_from_ir,
    parse_latex_log_issues,
)
from app.services.mineru_layout import Paragraph, TextRun


@pytest.mark.skipif(shutil.which(settings.latexmk_path) is None, reason="latexmk is not installed")
def test_real_xelatex_compiles_currency_ampersand_and_math_star(tmp_path):
    tex_path = tmp_path / "translated.tex"
    create_translated_tex_from_ir(
        [
            Paragraph(runs=[TextRun(text=r"\$10.99 in Big & Tall, then \$3.99.")]),
            Paragraph(runs=[TextRun(text="GiGPO ⋆ is highlighted.")]),
        ],
        tex_path,
        title="Regression",
    )

    result = compile_tex_project_with_fallback(
        tex_path, tmp_path, compiler=TRANSLATED_LATEX_COMPILER
    )

    assert result.pdf_path.is_file()
    assert result.pdf_path.stat().st_size > 0
    assert result.missing_chars == []
    generated = tex_path.read_text(encoding="utf-8")
    assert r"Big \& Tall" in generated
    assert r"$\star$" in generated


@pytest.mark.skipif(shutil.which(settings.latexmk_path) is None, reason="latexmk is not installed")
def test_real_xelatex_reproduces_the_three_original_fatal_errors(tmp_path):
    tex_path = tmp_path / "broken.tex"
    tex_path.write_text(
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "\\subsection*{leaked model reasoning\n\n"
        "more leaked reasoning}\n"
        "}\n"
        "Big & Tall\n"
        "\\end{document}\n",
        encoding="utf-8",
    )

    result = _run_latexmk(
        tex_path, tmp_path, force=True, compiler=TRANSLATED_LATEX_COMPILER
    )
    errors, _ = parse_latex_log_issues(tmp_path / "broken.log")
    messages = "\n".join(str(error["message"]) for error in errors)

    assert result.returncode != 0
    assert "Paragraph ended before \\@ssect was complete" in messages
    assert "Too many }'s" in messages
    assert "Misplaced alignment tab character &" in messages
