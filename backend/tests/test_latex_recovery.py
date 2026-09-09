import copy

from app.models.store import LatexRecoveryEntry
from app.services import latex_recovery
from app.services.latex_service import LatexCompileResult


def _fixture_tex() -> str:
    return (
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "Safe before.\n"
        "Another safe line.\n"
        "Big & Tall\n"
        "Safe after.\n"
        "\\end{document}\n"
    )


def _fixture_log() -> str:
    return "! Misplaced alignment tab character &.\nl.5 Big & Tall\n"


def test_recovery_persists_analysis_before_applying_bounded_patch(tmp_path, monkeypatch):
    tex_path = tmp_path / "translated.tex"
    log_path = tmp_path / "translated.log"
    tex_path.write_text(_fixture_tex(), encoding="utf-8")
    log_path.write_text(_fixture_log(), encoding="utf-8")
    original = tex_path.read_bytes()
    responses = iter([
        '{"summary":"An unescaped ampersand is used in prose.","error_lines":[5]}',
        '{"patches":[{"start_line":5,"end_line":5,"original":"Big & Tall","replacement":"Big \\\\& Tall","reason":"escape prose ampersand"}]}',
    ])
    monkeypatch.setattr(latex_recovery.llm_client, "chat", lambda **kwargs: next(responses))
    updates: list[LatexRecoveryEntry] = []

    def on_update(report: LatexRecoveryEntry) -> None:
        updates.append(copy.deepcopy(report))
        if report.status == "analyzing" and report.diagnosis:
            assert tex_path.read_bytes() == original

    def compile_ok(path, output_dir, compiler=None):
        assert "Big \\& Tall" in path.read_text(encoding="utf-8")
        pdf = output_dir / "translated.pdf"
        pdf.write_bytes(b"pdf")
        return LatexCompileResult(pdf)

    outcome = latex_recovery.recover_latex_document(
        tex_path,
        log_path,
        provider_settings=None,
        compile_func=compile_ok,
        on_update=on_update,
    )

    assert outcome.result is not None
    assert outcome.report.status == "succeeded"
    assert outcome.report.rounds == 1
    assert outcome.report.diagnosis == "An unescaped ampersand is used in prose."
    assert (tmp_path / "translated.before-repair-1.tex").read_bytes() == original
    assert updates[0].status == "analyzing"
    assert any(update.status == "repairing" for update in updates)
    assert any(update.status == "recompiling" for update in updates)


def test_recovery_rejects_dangerous_or_out_of_window_patch_without_writing(tmp_path, monkeypatch):
    tex_path = tmp_path / "translated.tex"
    log_path = tmp_path / "translated.log"
    tex_path.write_text(_fixture_tex(), encoding="utf-8")
    log_path.write_text(_fixture_log(), encoding="utf-8")
    original = tex_path.read_bytes()
    responses = iter([
        '{"summary":"Bad ampersand.","error_lines":[5]}',
        '{"patches":[{"start_line":5,"end_line":5,"original":"Big & Tall","replacement":"\\\\input{secret}","reason":"unsafe"}]}',
    ])
    monkeypatch.setattr(latex_recovery.llm_client, "chat", lambda **kwargs: next(responses))

    outcome = latex_recovery.recover_latex_document(
        tex_path,
        log_path,
        provider_settings=None,
        compile_func=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not compile")),
    )

    assert outcome.result is None
    assert outcome.report.status == "failed"
    assert "unsafe" in (outcome.report.last_error or "").lower()
    assert tex_path.read_bytes() == original
    assert not (tmp_path / "translated.before-repair-1.tex").exists()


def test_recovery_rejects_new_file_paths_without_writing(tmp_path, monkeypatch):
    tex_path = tmp_path / "translated.tex"
    log_path = tmp_path / "translated.log"
    tex_path.write_text(_fixture_tex(), encoding="utf-8")
    log_path.write_text(_fixture_log(), encoding="utf-8")
    original = tex_path.read_bytes()
    responses = iter([
        '{"summary":"Bad ampersand.","error_lines":[5]}',
        '{"patches":[{"start_line":5,"end_line":5,"original":"Big & Tall",'
        '"replacement":"Read C:\\\\private\\\\secret.tex","reason":"unsafe path"}]}',
    ])
    monkeypatch.setattr(latex_recovery.llm_client, "chat", lambda **kwargs: next(responses))

    outcome = latex_recovery.recover_latex_document(
        tex_path,
        log_path,
        provider_settings=None,
        compile_func=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not compile")),
    )

    assert outcome.result is None
    assert "file path" in (outcome.report.last_error or "").lower()
    assert tex_path.read_bytes() == original
    assert not (tmp_path / "translated.before-repair-1.tex").exists()


def test_patch_validator_rejects_whole_document_rewrite(tmp_path):
    tex_path = tmp_path / "translated.tex"
    lines = ["\\begin{document}"] + [f"line {index}" for index in range(1, 70)] + ["\\end{document}"]
    tex_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    payload = {
        "patches": [{
            "start_line": 2,
            "end_line": 66,
            "original": "\n".join(lines[1:66]),
            "replacement": "small replacement",
            "reason": "rewrite almost everything",
        }]
    }

    try:
        latex_recovery._validate_and_apply_patches(
            tex_path, payload, set(range(1, len(lines) + 1)), 1
        )
    except ValueError as exc:
        assert "too many lines" in str(exc).lower()
    else:
        raise AssertionError("whole-document rewrite must be rejected")

    assert not (tmp_path / "translated.before-repair-1.tex").exists()


def test_recovery_stops_after_two_rounds(tmp_path, monkeypatch):
    tex_path = tmp_path / "translated.tex"
    log_path = tmp_path / "translated.log"
    tex_path.write_text(_fixture_tex(), encoding="utf-8")
    log_path.write_text(_fixture_log(), encoding="utf-8")
    responses = iter([
        '{"summary":"round one","error_lines":[5]}',
        '{"patches":[{"start_line":5,"end_line":5,"original":"Big & Tall","replacement":"Big \\\\& Tall","reason":"round one"}]}',
        '{"summary":"round two","error_lines":[5]}',
        '{"patches":[{"start_line":5,"end_line":5,"original":"Big \\\\& Tall","replacement":"Big \\\\& Tall.","reason":"round two"}]}',
    ])
    monkeypatch.setattr(latex_recovery.llm_client, "chat", lambda **kwargs: next(responses))

    def compile_fail(*args, **kwargs):
        raise RuntimeError("still broken")

    outcome = latex_recovery.recover_latex_document(
        tex_path,
        log_path,
        provider_settings=None,
        compile_func=compile_fail,
    )
    assert outcome.result is None
    assert outcome.report.status == "failed"
    assert outcome.report.rounds == 2
    assert (tmp_path / "translated.before-repair-1.tex").exists()
    assert (tmp_path / "translated.before-repair-2.tex").exists()
