from pathlib import Path
from subprocess import CompletedProcess

import pytest

from app.services import latex_service


def test_failed_lenient_compile_does_not_accept_partial_pdf(tmp_path, monkeypatch):
    tex = tmp_path / "paper.tex"
    tex.write_text("broken", encoding="utf-8")
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"stale or partial")

    calls = 0

    def fake_run(tex_path: Path, output_dir: Path, *, force: bool):
        nonlocal calls
        calls += 1
        # Reproduce XeLaTeX's troublesome behavior: both passes write a
        # partial artifact but still exit with an error.
        pdf.write_bytes(b"partial")
        return CompletedProcess([], 12, stdout="Undefined control sequence", stderr="")

    monkeypatch.setattr(latex_service, "_run_latexmk", fake_run)

    with pytest.raises(RuntimeError, match="LaTeX compile failed"):
        latex_service.compile_tex_project_with_fallback(tex, tmp_path)

    assert calls == 2
