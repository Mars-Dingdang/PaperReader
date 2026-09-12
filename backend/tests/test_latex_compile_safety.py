import json
import os
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
    assert "-no-shell-escape" in captured[0]
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

    def fake_run(tex_path: Path, output_dir: Path, *, force: bool, compiler=None, texinputs=None):
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

    def fake_run(tex_path: Path, output_dir: Path, *, force: bool, compiler=None, texinputs=None):
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

    def fake_run(tex_path: Path, output_dir: Path, *, force: bool, compiler=None, texinputs=None):
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

    def fake_run(tex_path: Path, output_dir: Path, *, force: bool, compiler=None, texinputs=None):
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


def test_absolute_latexmk_path_exposes_sibling_tex_engine(tmp_path, monkeypatch):
    tex = tmp_path / "paper.tex"
    tex.write_text(r"\documentclass{article}" "\n", encoding="utf-8")
    latex_bin_dir = Path("C:/texlive/bin") if os.name == "nt" else Path("/Library/TeX/texbin")
    latexmk_path = latex_bin_dir / ("latexmk.exe" if os.name == "nt" else "latexmk")
    observed: dict[str, object] = {}

    def fake_subprocess_run(command, **kwargs):
        observed.update(kwargs)
        return CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(latex_service.settings, "latexmk_path", str(latexmk_path))
    monkeypatch.setenv("PATH", os.pathsep.join(["/usr/bin", "/bin"]))
    monkeypatch.setattr(latex_service.subprocess, "run", fake_subprocess_run)

    latex_service._run_latexmk(tex, tmp_path, force=False, compiler="xelatex")

    child_path = str(observed["env"]["PATH"])
    assert child_path.split(os.pathsep)[0] == str(latex_bin_dir)


# --------------------------------------------------------------------------
# TeX log diagnostics
# --------------------------------------------------------------------------

_SAMPLE_LOG = """This is XeTeX, Version 3.141592653
[17]
Missing character: There is no □ (U+25A1) in font [lmroman12-regular]:mapping=tex-text;!
[18]
! Argument of \\@sqrt has an extra }.
<inserted text>
                \\par
l.740 ...fty } { \\sqrt [ { k } / { a _ { n } } ] }
                                                  = { \\sqrt [ { k } / { A }...
! Missing $ inserted.
<inserted text>
                $
l.740 ...fty } { \\sqrt [ { k } / { a _ { n } } ] }
Missing character: There is no □ (U+25A1) in font [lmroman12-regular]:mapping=tex-text;!
"""


def test_parse_latex_log_supports_file_line_error_format(tmp_path):
    log_path = tmp_path / "translated.log"
    log_path.write_text(
        "C:/work/translated.tex:610: Paragraph ended before \\@ssect was complete.\n"
        "l.610\n"
        "C:/work/translated.tex:637: Too many }'s.\n"
        "C:/work/translated.tex:773: Misplaced alignment tab character &.\n",
        encoding="utf-8",
    )

    errors, missing = latex_service.parse_latex_log_issues(log_path)

    assert [(item["line"], item["message"]) for item in errors] == [
        (610, "Paragraph ended before \\@ssect was complete."),
        (637, "Too many }'s."),
        (773, "Misplaced alignment tab character &."),
    ]
    assert missing == []


def test_parse_latex_log_issues_extracts_errors_and_missing_chars(tmp_path):
    log = tmp_path / "paper.log"
    log.write_text(_SAMPLE_LOG, encoding="utf-8")

    errors, missing = latex_service.parse_latex_log_issues(log)

    assert errors, "fatal ! lines must be extracted"
    assert errors[0]["message"].startswith("Argument of \\@sqrt")
    assert errors[0]["line"] == 740
    assert {e["line"] for e in errors} == {740}

    assert len(missing) == 1
    assert missing[0]["char"] == "□"
    assert missing[0]["codepoint"] == "U+25A1"
    assert missing[0]["count"] == 2
    assert missing[0]["suggest"] == "\\square"


def test_compile_failure_report_prefers_structured_log_digest(tmp_path, monkeypatch):
    tex = tmp_path / "paper.tex"
    tex.write_text("broken", encoding="utf-8")

    def fake_run(tex_path: Path, output_dir: Path, *, force: bool, compiler=None, texinputs=None):
        (output_dir / "paper.log").write_text(_SAMPLE_LOG, encoding="utf-8")
        return CompletedProcess([], 12, stdout="Missing character noise everywhere", stderr="")

    monkeypatch.setattr(latex_service, "_run_latexmk", fake_run)

    with pytest.raises(RuntimeError) as excinfo:
        latex_service.compile_tex_project_with_fallback(tex, tmp_path)

    message = str(excinfo.value)
    assert "L740" in message
    assert "Argument of \\@sqrt" in message
    assert "U+25A1" in message


def test_compile_success_with_missing_glyphs_sets_warning(tmp_path, monkeypatch):
    tex = tmp_path / "paper.tex"
    tex.write_text("\\documentclass{article}", encoding="utf-8")
    log = tmp_path / "paper.log"
    log.write_text(_SAMPLE_LOG, encoding="utf-8")

    def fake_run(tex_path: Path, output_dir: Path, *, force: bool, compiler=None, texinputs=None):
        (output_dir / "paper.pdf").write_bytes(b"%PDF-1.4")
        return CompletedProcess([], 0, stdout="", stderr="")

    monkeypatch.setattr(latex_service, "_run_latexmk", fake_run)

    result = latex_service.compile_tex_project_with_fallback(tex, tmp_path)

    assert result.warning is not None
    assert "U+25A1" in result.warning
    assert result.missing_chars[0]["suggest"] == "\\square"


def test_translated_templates_carry_unicode_fallback_preamble(tmp_path):
    from app.services.latex_sanitizer import repair_common_math_faults

    tex_path = tmp_path / "translated.tex"
    repairs = latex_service.create_translated_tex(
        "证毕□ 说明", tex_path, title="标题"
    )
    content = tex_path.read_text(encoding="utf-8")

    assert repairs == []
    assert "\\newunicodechar{□}" in content
    assert "\\xeCJKDeclareCharClass{CJK}{\"25A0 -> \"25FF" in content
    # Prose proof marks are converted to math commands at write time
    assert r"$\square$" in content
    assert "□" not in content.replace("\\newunicodechar{□}", "")


def test_translated_templates_disable_obsolete_ctex_platform_fonts(tmp_path):
    tex_path = tmp_path / "translated.tex"
    latex_service.create_translated_tex("中文", tex_path)
    content = tex_path.read_text(encoding="utf-8")

    assert r"\usepackage[UTF8,fontset=none]{ctex}" in content
    assert "Songti SC" in content
    assert "FandolSong" in content


def test_retry_upgrades_legacy_ctex_template_font_config():
    legacy = (
        "\\documentclass{article}\n"
        "\\usepackage[UTF8]{ctex}\n"
        "\\begin{document}\n中文\n"
    )

    updated = latex_service.ensure_portable_cjk_font_config(legacy)

    assert r"\usepackage[UTF8,fontset=none]{ctex}" in updated
    assert "Songti SC" in updated
    assert latex_service.ensure_portable_cjk_font_config(updated) == updated


def test_create_translated_tex_returns_sqrt_repairs(tmp_path):
    tex_path = tmp_path / "translated.tex"
    markdown = "公式 ${ \\sqrt [ { k } / { A } }$ 结束"
    repairs = latex_service.create_translated_tex(markdown, tex_path)

    content = tex_path.read_text(encoding="utf-8")
    assert repairs and repairs[0].startswith("L1:")
    assert r"\sqrt[{ k }]{{ A }}}" in content


def test_parse_latex_log_filters_planted_file_line_anchors_by_tex_name(tmp_path):
    # TeX logs echo source text verbatim, so a document can plant lines shaped
    # like "file.tex:N:" inside its own content. Anchors must only be accepted
    # for the file that was actually compiled.
    log = tmp_path / "translated.log"
    log.write_text(
        "evil.tex:150: planted anchor\n"
        "./translated.tex:722: Misplaced alignment tab character &.\n",
        encoding="utf-8",
    )

    unfiltered_errors, _ = latex_service.parse_latex_log_issues(log)
    assert {e["line"] for e in unfiltered_errors} == {150, 722}

    filtered_errors, _ = latex_service.parse_latex_log_issues(log, tex_name="translated.tex")
    assert {e["line"] for e in filtered_errors} == {722}

    spoofed_name_errors, _ = latex_service.parse_latex_log_issues(
        log, tex_name="main.tex"
    )
    assert spoofed_name_errors == []


def test_parse_latex_log_rejects_absurd_line_numbers(tmp_path):
    log = tmp_path / "translated.log"
    log.write_text("translated.tex:999999999: planted far anchor\n", encoding="utf-8")

    errors, _ = latex_service.parse_latex_log_issues(log, tex_name="translated.tex")

    assert errors == []
