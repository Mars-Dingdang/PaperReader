import json
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from app.services import latex_service


def test_arxiv_readme_declared_compiler_is_used(tmp_path, monkeypatch):
    tex = tmp_path / "paper.tex"
    tex.write_text("\\documentclass{article}\n", encoding="utf-8")
    (tmp_path / "00README.json").write_text(
        json.dumps({"process": {"compiler": "pdflatex"}}),
        encoding="utf-8",
    )
    captured: list[list[str]] = []

    def fake_subprocess_run(command, **kwargs):
        captured.append(command)
        return CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(latex_service.subprocess, "run", fake_subprocess_run)

    latex_service._run_latexmk(tex, tmp_path, force=False)

    assert captured[0][1] == "-pdf"
    assert "-xelatex" not in captured[0]


def test_tex_program_magic_comment_is_used_without_arxiv_metadata(tmp_path):
    tex = tmp_path / "paper.tex"
    tex.write_text(
        "% !TeX program = lualatex\n\\documentclass{article}\n",
        encoding="utf-8",
    )

    assert latex_service._latexmk_engine_flag(tex) == "-lualatex"


def test_latex_compile_defaults_to_xelatex_without_declaration(tmp_path):
    tex = tmp_path / "paper.tex"
    tex.write_text("\\documentclass{article}\n", encoding="utf-8")

    assert latex_service._latexmk_engine_flag(tex) == "-xelatex"


def test_unsupported_compiler_declaration_falls_back_safely(tmp_path):
    tex = tmp_path / "paper.tex"
    tex.write_text("\\documentclass{article}\n", encoding="utf-8")
    (tmp_path / "00README.json").write_text(
        json.dumps({"process": {"compiler": "pdflatex --shell-escape"}}),
        encoding="utf-8",
    )

    assert latex_service._latexmk_engine_flag(tex) == "-xelatex"


def test_failed_lenient_compile_does_not_accept_partial_pdf(tmp_path, monkeypatch):
    tex = tmp_path / "paper.tex"
    tex.write_text("broken", encoding="utf-8")
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"stale or partial")

    calls = 0

    def fake_run(tex_path: Path, output_dir: Path, *, force: bool):
        nonlocal calls
        calls += 1
        # Reproduce a TeX engine's troublesome behavior: both passes write a
        # partial artifact but still exit with an error.
        pdf.write_bytes(b"partial")
        return CompletedProcess([], 12, stdout="Undefined control sequence", stderr="")

    monkeypatch.setattr(latex_service, "_run_latexmk", fake_run)

    with pytest.raises(RuntimeError, match="LaTeX compile failed"):
        latex_service.compile_tex_project_with_fallback(tex, tmp_path)

    assert calls == 2
