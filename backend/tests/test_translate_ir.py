import pytest

from app.services import translate_service
from app.services.llm_client import LLMOutputTruncatedError
from app.services.mineru_layout import (
    DisplayMath,
    Image,
    InlineMath,
    Paragraph,
    TextRun,
    Title,
)


def _make_ir():
    return [
        Title(level=1, text="Hello World"),
        Paragraph(
            runs=[
                TextRun(text="See also "),
                InlineMath(latex="x^2"),
                TextRun(text=" and 100%."),
            ]
        ),
        DisplayMath(latex="\\int_0^1 x dx = 1/2"),
        Image(rel_path="images/fig1.jpg", caption="A nice figure"),
    ]


def test_translate_ir_only_translates_text(monkeypatch):
    captured: list[str] = []

    def fake_chat(message, system_prompt, **kwargs):
        captured.append(message)
        # Produce one Chinese translation per segment, preserving the delimiter.
        if "@@SEG@@" in message:
            parts = message.split("@@SEG@@")
            return "@@SEG@@".join(f"[译]{p.strip()}" for p in parts)
        return f"[译]{message.strip()}"

    monkeypatch.setattr(translate_service.llm_client, "chat", fake_chat)

    ir = _make_ir()
    translate_service.translate_ir(ir)

    # Title and the two text runs and the caption are translated.
    assert ir[0].text.startswith("[译]")
    assert ir[1].runs[0].text.startswith("[译]")
    assert ir[1].runs[2].text.startswith("[译]")
    assert ir[3].caption.startswith("[译]")

    # Inline + display math are NOT touched.
    assert ir[1].runs[1].latex == "x^2"
    assert ir[2].latex == "\\int_0^1 x dx = 1/2"
    # Image path remains intact.
    assert ir[3].rel_path == "images/fig1.jpg"

    # All segments were sent in a single batched LLM call.
    assert len(captured) == 1
    assert captured[0].count("@@SEG@@") == 3  # 4 segments => 3 separators


def test_translate_ir_falls_back_when_batch_count_mismatches(monkeypatch):
    calls: list[str] = []

    def fake_chat(message, system_prompt, **kwargs):
        calls.append(message)
        # First call (batched): return a malformed response with wrong delimiter count.
        if "@@SEG@@" in message:
            return "single blob with no delimiter"
        return f"CN({message.strip()})"

    monkeypatch.setattr(translate_service.llm_client, "chat", fake_chat)

    ir = _make_ir()
    translate_service.translate_ir(ir)

    # Per-segment fallback yields exactly one extra call per segment.
    # 1 batch call + 4 fallback calls = 5
    assert len(calls) == 5
    assert ir[0].text == "CN(Hello World)"
    assert ir[1].runs[1].latex == "x^2"  # math still untouched


def test_translate_ir_splits_long_logical_segment_and_reassembles(monkeypatch):
    calls: list[str] = []

    def fake_chat(message, system_prompt, **kwargs):
        calls.append(message)
        if "@@SEG@@" in message:
            return "@@SEG@@".join(f"译({part.strip()})" for part in message.split("@@SEG@@"))
        return f"译({message.strip()})"

    monkeypatch.setattr(translate_service.llm_client, "chat", fake_chat)
    monkeypatch.setattr(translate_service.settings, "translate_segment_max_chars", 300)

    source = "START " + " ".join(f"word{i}" for i in range(160)) + " END"
    ir = [Paragraph(runs=[TextRun(text=source)])]
    translate_service.translate_ir(ir)

    translated = ir[0].runs[0].text
    assert "START" in translated and "END" in translated
    assert any(call.count("@@SEG@@") >= 1 for call in calls)


def test_translate_ir_recovers_truncated_batch_with_smaller_calls(monkeypatch):
    calls: list[str] = []

    def fake_chat(message, system_prompt, **kwargs):
        calls.append(message)
        if "@@SEG@@" in message:
            raise LLMOutputTruncatedError("length")
        return f"译({message.strip()})"

    monkeypatch.setattr(translate_service.llm_client, "chat", fake_chat)
    ir = [Paragraph(runs=[TextRun(text="First segment."), TextRun(text="Second segment.")])]

    translate_service.translate_ir(ir)

    assert ir[0].runs[0].text == "译(First segment.)"
    assert ir[0].runs[1].text == "译(Second segment.)"
    assert len(calls) == 3


def test_translate_ir_never_silently_publishes_failed_english_chunks(monkeypatch):
    def fake_chat(message, system_prompt, **kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(translate_service.llm_client, "chat", fake_chat)
    ir = [Paragraph(runs=[TextRun(text="This must not be silently left untranslated.")])]

    with pytest.raises(RuntimeError, match="Translation incomplete"):
        translate_service.translate_ir(ir)
