import shutil

import pytest

from app.core.config import settings
from app.services.latex_service import (
    TRANSLATED_LATEX_COMPILER,
    compile_tex_project_with_fallback,
    create_translated_tex_from_ir,
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
