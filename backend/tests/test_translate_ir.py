from app.services import translate_service
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
