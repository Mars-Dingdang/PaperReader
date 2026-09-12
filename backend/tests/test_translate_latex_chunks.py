import json

import pytest

from app.services import translate_service
from app.services.translate_service import (
    _split_latex_document,
    protect_placeholders,
    split_text_into_chunks,
    translate_latex_document,
)

_DOCUMENT = """\\documentclass{article}
\\begin{document}
Hello world.\\cite{knuth}

Second paragraph here.
\\end{document}
"""


def _body_chunks() -> list[str]:
    _, body, _ = _split_latex_document(_DOCUMENT)
    protected, _ = protect_placeholders(body)
    return split_text_into_chunks(protected)


def test_translate_latex_document_reports_progress_and_persists_checkpoint(
    monkeypatch, tmp_path
) -> None:
    def fake_chat(message, system_prompt, **kwargs):
        return f"[译]{message}"

    monkeypatch.setattr(translate_service.llm_client, "chat", fake_chat)
    checkpoint = tmp_path / "translation-checkpoint.json"
    progress: list[tuple[int, int]] = []

    translate_latex_document(
        _DOCUMENT,
        checkpoint_path=checkpoint,
        progress_callback=lambda done, total: progress.append((done, total)),
    )

    assert progress, "progress callback must fire"
    assert progress[0][0] == 0
    assert progress[-1][0] == progress[-1][1]
    assert all(done <= total for done, total in progress)

    payload = json.loads(checkpoint.read_text(encoding="utf-8"))
    assert payload["version"] == translate_service._TRANSLATION_CONTRACT_VERSION
    expected_keys = {
        translate_service._checkpoint_key(chunk, "latex") for chunk in _body_chunks()
    }
    assert expected_keys <= set(payload["segments"])


def test_translate_latex_document_reuses_checkpoint_without_llm_calls(
    monkeypatch, tmp_path
) -> None:
    def fake_chat(message, system_prompt, **kwargs):
        return f"[译]{message}"

    monkeypatch.setattr(translate_service.llm_client, "chat", fake_chat)
    checkpoint = tmp_path / "translation-checkpoint.json"
    first = translate_latex_document(_DOCUMENT, checkpoint_path=checkpoint)

    def must_not_call(**kwargs):
        raise AssertionError("cached chunks must not re-hit the LLM")

    monkeypatch.setattr(translate_service.llm_client, "chat", must_not_call)
    second = translate_latex_document(_DOCUMENT, checkpoint_path=checkpoint)

    assert second == first
    assert "[译]" in second


def test_translate_latex_document_invalid_cached_chunk_is_retranslated(
    monkeypatch, tmp_path
) -> None:
    def fake_chat(message, system_prompt, **kwargs):
        return f"[译]{message}"

    monkeypatch.setattr(translate_service.llm_client, "chat", fake_chat)
    checkpoint = tmp_path / "translation-checkpoint.json"
    translate_latex_document(_DOCUMENT, checkpoint_path=checkpoint)

    payload = json.loads(checkpoint.read_text(encoding="utf-8"))
    first_key = next(iter(payload["segments"]))
    payload["segments"][first_key] = ""
    checkpoint.write_text(json.dumps(payload), encoding="utf-8")

    calls: list[str] = []

    def counting_chat(message, system_prompt, **kwargs):
        calls.append(message)
        return f"[译]{message}"

    monkeypatch.setattr(translate_service.llm_client, "chat", counting_chat)
    translate_latex_document(_DOCUMENT, checkpoint_path=checkpoint)

    assert calls, "invalid cached chunk must be re-translated"


def test_translate_latex_document_retries_chunk_after_placeholder_loss(
    monkeypatch,
) -> None:
    attempts: list[str] = []

    def fake_chat(message, system_prompt, **kwargs):
        attempts.append(message)
        if len(attempts) == 1:
            # The observed DreamGuard failure: the model drops the protected
            # citation placeholders together with the commented-out draft text.
            return "[译]正文"
        return f"[译]{message}"

    monkeypatch.setattr(translate_service.llm_client, "chat", fake_chat)

    translated = translate_latex_document(_DOCUMENT)

    assert len(attempts) >= 2, "first invalid attempt must be retried"
    assert "[译]" in translated
    assert "\\cite{knuth}" in translated


def test_translate_latex_document_fails_after_two_invalid_attempts(monkeypatch) -> None:
    def fake_chat(message, system_prompt, **kwargs):
        return "[译]正文"

    monkeypatch.setattr(translate_service.llm_client, "chat", fake_chat)

    with pytest.raises(RuntimeError, match="Translation incomplete"):
        translate_latex_document(_DOCUMENT)


def test_strip_latex_comments_removes_comments_but_keeps_content() -> None:
    from app.services.translate_service import strip_latex_comments

    body = (
        "% original ======\n".replace("\n", "\n")
        + "Live prose with 50\% share.\n"
        + "%Draft: old sentence with \cite{knuth}\n"
        + "More live prose.\n"
    )

    stripped = strip_latex_comments(body)

    assert "Live prose with 50\% share." in stripped
    assert "More live prose." in stripped
    assert "% original" not in stripped
    assert "Draft: old sentence" not in stripped
    assert "\cite{knuth}" in stripped or "cite" not in stripped


def test_strip_latex_comments_preserves_verbatim_bodies() -> None:
    from app.services.translate_service import strip_latex_comments

    body = (
        "\\begin{verbatim}\n"
        "x = 100% # keep this comment\n"
        "\\end{verbatim}\n"
        "After % real comment\n"
    )

    stripped = strip_latex_comments(body)

    assert "x = 100% # keep this comment" in stripped
    assert "After" in stripped
    assert "real comment" not in stripped


def test_strip_latex_comments_drops_comment_only_lines_entirely() -> None:
    from app.services.translate_service import strip_latex_comments

    body = (
        "\\begin{tcolorbox}[\n"
        "    arc=4pt,              % round corners\n"
        "    % title=\\textbf{Example} % optional\n"
        "]\n"
        "    \\small\n"
        "    % a standalone comment\n"
        "Body text.\n"
    )

    stripped = strip_latex_comments(body)

    assert "    arc=4pt,\n]\n" in stripped, "options block must gain no blank line"
    assert "% title" not in stripped
    assert "Body text." in stripped
    assert "\n\n    Body text." not in stripped, "comment-only line must not become \\par"


def test_translate_latex_document_accepts_reordered_placeholders(monkeypatch) -> None:
    # Chinese word order legitimately moves math/citation tokens relative to
    # the English source; placeholders restore by token key, so a permutation
    # is a valid translation while a dropped token is not.
    def fake_chat(message, system_prompt, **kwargs):
        tokens = [t for t in message.split() if t.startswith("__PR_PH_")]
        reordered = list(reversed(tokens))
        translated = message
        for original, replacement in zip(tokens, reordered):
            translated = translated.replace(original, f"@@{replacement}@@", 1)
        translated = translated.replace("@@", "")
        return f"[译]{translated}"

    monkeypatch.setattr(translate_service.llm_client, "chat", fake_chat)

    translated = translate_latex_document(_DOCUMENT)
    assert "\cite{knuth}" in translated


def test_translate_latex_document_still_rejects_dropped_placeholders(monkeypatch) -> None:
    attempts: list[int] = []

    def fake_chat(message, system_prompt, **kwargs):
        attempts.append(1)
        return "[译]丢了占位符的译文"

    monkeypatch.setattr(translate_service.llm_client, "chat", fake_chat)

    with pytest.raises(RuntimeError, match="Translation incomplete"):
        translate_latex_document(_DOCUMENT)
    assert len(attempts) == 3


def test_environment_commands_survive_translation(monkeypatch) -> None:
    source = (
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "\\begin{figure*}[t]\n"
        "\\centering\n"
        "A figure caption text.\n"
        "\\end{figure*}\n"
        "\\end{document}\n"
    )
    attempts: list[str] = []

    def fake_chat(message, system_prompt, **kwargs):
        attempts.append(message)
        if len(attempts) == 1:
            # The observed SafeMCP corruption: the model silently drops the
            # environment-open token while keeping the close.
            return message.replace("__PR_PH_0000__[t]\n", "")
        return f"[译]{message}"

    monkeypatch.setattr(translate_service.llm_client, "chat", fake_chat)

    translated = translate_latex_document(source)

    assert translated.count("\\begin{figure*}") == 1
    assert translated.count("\\end{figure*}") == 1
    assert len(attempts) >= 2, "dropping an environment token must trigger a retry"


def test_pdf_only_font_packages_are_replaced_for_xelatex(monkeypatch) -> None:
    source = (
        "\\documentclass{article}\n"
        "\\usepackage{times}\n"
        "\\begin{document}\n"
        "Hello world.\n"
        "\\end{document}\n"
    )

    monkeypatch.setattr(
        translate_service.llm_client,
        "chat",
        lambda message, system_prompt, **kwargs: f"[译]{message}",
    )

    translated = translate_latex_document(source)

    assert "\\usepackage{newtxtext}" in translated
    assert "\\usepackage{times}" not in translated
