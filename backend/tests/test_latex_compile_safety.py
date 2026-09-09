import json
import subprocess
import sys
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

    def fake_run(tex_path: Path, output_dir: Path, *, force: bool, compiler=None):
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


def test_explicit_compiler_overrides_arxiv_declaration(tmp_path, monkeypatch):
    tex = tmp_path / "__translated.tex"
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

    latex_service._run_latexmk(tex, tmp_path, force=False, compiler="xelatex")

    assert "-xelatex" in captured[0]
    assert "-pdf" not in captured[0]


def test_explicit_compiler_overrides_tex_program_magic_comment(tmp_path, monkeypatch):
    tex = tmp_path / "__translated.tex"
    tex.write_text(
        "% !TeX program = pdflatex\n\\documentclass{article}\n",
        encoding="utf-8",
    )
    captured: list[list[str]] = []

    def fake_subprocess_run(command, **kwargs):
        captured.append(command)
        return CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(latex_service.subprocess, "run", fake_subprocess_run)

    latex_service._run_latexmk(tex, tmp_path, force=False, compiler="xelatex")

    assert "-xelatex" in captured[0]
    assert "-pdf" not in captured[0]


def test_stale_fdb_latexmk_is_removed_before_strict_run(tmp_path, monkeypatch):
    tex = tmp_path / "paper.tex"
    tex.write_text("\\documentclass{article}\n", encoding="utf-8")
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    fdb = output_dir / "paper.fdb_latexmk"
    fdb.write_text("stale latexmk database with cached error state", encoding="utf-8")

    observed: list[bool] = []

    def fake_run(tex_path: Path, output_dir: Path, *, force: bool, compiler=None):
        observed.append(fdb.exists())
        (output_dir / "paper.pdf").write_bytes(b"%PDF-1.4")
        return CompletedProcess([], 0, stdout="", stderr="")

    monkeypatch.setattr(latex_service, "_run_latexmk", fake_run)

    latex_service.compile_tex_project_with_fallback(tex, output_dir)

    assert observed == [False]


def test_strict_failure_fdb_is_cleared_before_lenient_retry(tmp_path, monkeypatch):
    tex = tmp_path / "paper.tex"
    tex.write_text("broken", encoding="utf-8")
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    fdb = output_dir / "paper.fdb_latexmk"

    def fake_run(tex_path: Path, output_dir: Path, *, force: bool, compiler=None):
        if not force:
            # A failing strict pass leaves its error state in the fdb, which
            # would otherwise make the retry report "Nothing to do".
            fdb.write_text("cached error", encoding="utf-8")
            return CompletedProcess([], 11, stdout="strict error", stderr="")
        assert not fdb.exists(), "lenient retry must start without the strict pass's fdb"
        return CompletedProcess([], 11, stdout="lenient error", stderr="")

    monkeypatch.setattr(latex_service, "_run_latexmk", fake_run)

    with pytest.raises(RuntimeError, match="LaTeX compile failed"):
        latex_service.compile_tex_project_with_fallback(tex, output_dir)


def test_error_detail_reports_strict_and_lenient_failures(tmp_path, monkeypatch):
    tex = tmp_path / "paper.tex"
    tex.write_text("broken", encoding="utf-8")

    def fake_run(tex_path: Path, output_dir: Path, *, force: bool, compiler=None):
        stdout = "real TeX error in strict pass" if not force else "lenient pass failure"
        return CompletedProcess([], 11, stdout=stdout, stderr="")

    monkeypatch.setattr(latex_service, "_run_latexmk", fake_run)

    with pytest.raises(RuntimeError) as excinfo:
        latex_service.compile_tex_project_with_fallback(tex, tmp_path)

    assert "real TeX error in strict pass" in str(excinfo.value)
    assert "lenient pass failure" in str(excinfo.value)


def test_latexmk_child_processes_do_not_flash_a_console_window(tmp_path, monkeypatch):
    tex = tmp_path / "paper.tex"
    tex.write_text(r"\documentclass{article}" "\n", encoding="utf-8")
    observed: dict[str, object] = {}

    def fake_subprocess_run(command, **kwargs):
        observed.update(kwargs)
        return CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(latex_service.subprocess, "run", fake_subprocess_run)

    latex_service._run_latexmk(tex, tmp_path, force=False)

    # The packaged desktop app runs windowed; on Windows every console child
    # (latexmk, xelatex, bibtex) would otherwise pop up its own terminal.
    if sys.platform == "win32":
        assert observed["creationflags"] == subprocess.CREATE_NO_WINDOW
    else:
        assert observed["creationflags"] == 0
