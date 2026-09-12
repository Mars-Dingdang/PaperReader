import json

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


def test_translate_ir_preserves_structural_think_tag_without_sending_it(monkeypatch):
    def unexpected_chat(*args, **kwargs):
        raise AssertionError("a pure structural tag must bypass the model")

    monkeypatch.setattr(translate_service.llm_client, "chat", unexpected_chat)
    ir = [Title(level=2, text="<think>")]
    translate_service.translate_ir(ir)
    assert ir[0].text == "<think>"


def test_translate_ir_retries_only_invalid_batch_member(monkeypatch):
    calls: list[str] = []

    def fake_chat(message, system_prompt, **kwargs):
        calls.append(message)
        if "@@SEG@@" in message:
            return "第一段@@SEG@@I am supposed to translate the text inside these tags, but cannot."
        assert "Second" in message
        return "第二段"

    monkeypatch.setattr(translate_service.llm_client, "chat", fake_chat)
    ir = [Paragraph(runs=[TextRun(text="First"), TextRun(text="Second")])]
    translate_service.translate_ir(ir)

    assert ir[0].runs[0].text == "第一段"
    assert ir[0].runs[1].text == "第二段"
    assert len(calls) == 2


def test_translate_ir_reuses_verified_checkpoint_across_provider_changes(tmp_path, monkeypatch):
    calls: list[str] = []

    def fake_chat(message, system_prompt, **kwargs):
        calls.append(message)
        return "已验证译文"

    monkeypatch.setattr(translate_service.llm_client, "chat", fake_chat)
    checkpoint = tmp_path / "translation-checkpoint.json"
    first = [Paragraph(runs=[TextRun(text="Stable source")])]
    translate_service.translate_ir(first, checkpoint_path=checkpoint, override_model="model-a")
    assert first[0].runs[0].text == "已验证译文"

    def provider_must_not_run(*args, **kwargs):
        raise AssertionError("verified chunks must survive provider setting changes")

    monkeypatch.setattr(translate_service.llm_client, "chat", provider_must_not_run)
    second = [Paragraph(runs=[TextRun(text="Stable source")])]
    translate_service.translate_ir(second, checkpoint_path=checkpoint, override_model="model-b")
    assert second[0].runs[0].text == "已验证译文"
    assert len(calls) == 1


def test_translate_ir_reuses_checkpoint_with_structural_placeholders(tmp_path, monkeypatch):
    checkpoint = tmp_path / "translation-checkpoint.json"
    source = "<think>Reason about $x$ at https://example.com</think>"

    def fake_chat(message, system_prompt, **kwargs):
        return message.replace("Reason about", "推理")

    monkeypatch.setattr(translate_service.llm_client, "chat", fake_chat)
    first = [Paragraph(runs=[TextRun(text=source)])]
    translate_service.translate_ir(first, checkpoint_path=checkpoint)
    assert first[0].runs[0].text == "<think>推理 $x$ at https://example.com</think>"

    monkeypatch.setattr(
        translate_service.llm_client,
        "chat",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("checkpoint must be reused")),
    )
    second = [Paragraph(runs=[TextRun(text=source)])]
    translate_service.translate_ir(second, checkpoint_path=checkpoint)
    assert second[0].runs[0].text == first[0].runs[0].text


def test_translate_ir_checkpoints_siblings_before_later_chunk_fails(tmp_path, monkeypatch):
    checkpoint = tmp_path / "translation-checkpoint.json"
    calls: list[str] = []

    def fake_chat(message, system_prompt, **kwargs):
        calls.append(message)
        if "@@SEG@@" in message:
            return "malformed batch response"
        if message == "First":
            return "第一"
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(translate_service.llm_client, "chat", fake_chat)
    ir = [Paragraph(runs=[TextRun(text="First"), TextRun(text="Second")])]

    with pytest.raises(RuntimeError, match=r"chunk 2\b"):
        translate_service.translate_ir(ir, checkpoint_path=checkpoint)

    payload = json.loads(checkpoint.read_text(encoding="utf-8"))
    assert payload["segments"][translate_service._checkpoint_key("First")] == "第一"
    assert translate_service._checkpoint_key("Second") not in payload["segments"]


def test_translate_output_with_extra_structural_tag_is_retried(monkeypatch):
    calls: list[str] = []

    def fake_chat(message, system_prompt, **kwargs):
        calls.append(message)
        return "<think>model reasoning</think>" if len(calls) == 1 else "安全译文"

    monkeypatch.setattr(translate_service.llm_client, "chat", fake_chat)
    ir = [Paragraph(runs=[TextRun(text="Source prose")])]

    translate_service.translate_ir(ir)

    assert ir[0].runs[0].text == "安全译文"
    assert len(calls) == 2


def test_placeholder_generation_does_not_collide_with_source_text():
    source = "literal __PR_PH_0000__ then <think>"
    protected, mapping = translate_service.protect_placeholders(source)

    assert "__PR_PH_0000__" in protected
    assert "__PR_PH_0000__" not in mapping
    assert translate_service.restore_placeholders(protected, mapping) == source


@pytest.mark.parametrize("payload", [None, [], "text", 1])
def test_translation_checkpoint_ignores_non_object_json(tmp_path, payload):
    checkpoint = tmp_path / "translation-checkpoint.json"
    checkpoint.write_text(json.dumps(payload), encoding="utf-8")

    assert translate_service._load_translation_checkpoint(checkpoint) == {}


def test_translate_text_rejects_invalid_cached_chunk(tmp_path, monkeypatch):
    source = "Translate this paragraph."
    checkpoint = tmp_path / "translation-checkpoint.json"
    checkpoint.write_text(
        json.dumps(
            {
                "version": translate_service._TRANSLATION_CONTRACT_VERSION,
                "segments": {
                    translate_service._checkpoint_key(source, "text"): "```latex\nunsafe\n```"
                },
            }
        ),
        encoding="utf-8",
    )
    calls: list[str] = []

    def fake_chat(message, system_prompt, **kwargs):
        calls.append(message)
        return "安全译文"

    monkeypatch.setattr(translate_service.llm_client, "chat", fake_chat)

    translated = translate_service.translate_text(source, checkpoint_path=checkpoint)

    assert translated == "安全译文"
    assert calls == [source]


def test_normalize_repairs_lost_currency_escape_without_recall(monkeypatch):
    # A temperature-zero model reproduces the same corruption on retry, so the
    # dropped backslash is restored deterministically instead of re-asking.
    repaired = translate_service._normalize_translation(
        "shirts priced \\$10.99 to \\$3.99", "shirts priced $10.99 to $3.99"
    )
    assert repaired == "shirts priced \\$10.99 to \\$3.99"

    # Cached chunks self-heal the same way on checkpoint load.
    cached = translate_service._normalize_translation("shirt \\$10.99", "shirt $10.99")
    assert cached == "shirt \\$10.99"


def test_normalize_removes_unicode_replacement_marker() -> None:
    repaired = translate_service._normalize_translation(
        "We find this result.", "我们发\ufffd现了这个结果。"
    )

    assert repaired == "我们发现了这个结果。"

    # Real math in the source keeps unescaped delimiters untouched.
    assert (
        translate_service._normalize_translation("formula $x$ holds", "公式 $x$ 成立")
        == "公式 $x$ 成立"
    )


def test_translate_accepts_preserved_currency_escape_and_real_math():
    translate_service._validate_translation("shirts \\$10.99", "shirts \\$10.99")
    translate_service._validate_translation("formula $x$ holds", "formula $x$ holds")
    translate_service._validate_translation("price \\$9", "price 9 dollars")


def test_translate_ir_repairs_chunk_that_loses_currency_escape(monkeypatch):
    calls: list[str] = []

    def fake_chat(message, system_prompt, **kwargs):
        calls.append(message)
        assert "@@SEG@@" in message
        # First member lost the escape; second member is fine. The repair must
        # happen inline, so exactly one batch call is made.
        return "shirt $10.99 Big & Tall@@SEG@@第二段"

    monkeypatch.setattr(translate_service.llm_client, "chat", fake_chat)
    ir = [Paragraph(runs=[TextRun(text="shirt \\$10.99"), TextRun(text="Second")])]
    translate_service.translate_ir(ir)

    assert ir[0].runs[0].text == "shirt \\$10.99 Big & Tall"
    assert ir[0].runs[1].text == "第二段"
    assert len(calls) == 1


def _references_ir():
    from app.services.mineru_layout import ListBlock

    return [
        Title(level=1, text="Introduction"),
        Paragraph(runs=[TextRun(text="Body prose about agents.")]),
        Title(level=1, text="References"),
        ListBlock(
            list_type="reference_list",
            items=[[TextRun(text="[1] Wang et al. Agent safety, 2025.")]],
        ),
        Paragraph(runs=[TextRun(text="[2] Ren et al. Power regulation, 2025.")]),
        Title(level=1, text="Appendix"),
        Paragraph(runs=[TextRun(text="Appendix training details.")]),
    ]


def test_translatable_mask_marks_reference_region():
    from app.services.mineru_layout import collect_translatable_strings, translatable_mask

    ir = _references_ir()
    strings = collect_translatable_strings(ir)
    mask = translatable_mask(ir)

    assert len(mask) == len(strings)
    assert mask[0] and mask[1], "pre-reference content translates"
    assert not mask[2], "References heading stays English"
    assert not mask[3] and not mask[4], "bibliography entries stay English"
    assert mask[5] and mask[6], "content after the section still translates"


def test_translate_ir_leaves_references_untranslated(monkeypatch):
    sent: list[str] = []

    def fake_chat(message, system_prompt, **kwargs):
        if "@@SEG@@" in message:
            sent.append(message)
            parts = message.split("@@SEG@@")
            return "@@SEG@@".join(f"[译]{p.strip()}" for p in parts)
        sent.append(message)
        return f"[译]{message.strip()}"

    monkeypatch.setattr(translate_service.llm_client, "chat", fake_chat)

    ir = _references_ir()
    translate_service.translate_ir(ir)

    assert ir[0].text.startswith("[译]")
    assert ir[1].runs[0].text.startswith("[译]")
    assert ir[2].text == "References"
    assert ir[3].items[0][0].text == "[1] Wang et al. Agent safety, 2025."
    assert ir[4].runs[0].text == "[2] Ren et al. Power regulation, 2025."
    assert ir[5].text.startswith("[译]")
    assert ir[6].runs[0].text.startswith("[译]")

    joined = "\n".join(sent)
    assert "[1] Wang et al." not in joined
    assert "Body prose about agents." in joined
    assert "Appendix training details." in joined


def test_translate_ir_injects_translation_context_into_prompts(monkeypatch):
    prompts: list[str] = []

    def fake_chat(message, system_prompt, **kwargs):
        prompts.append(system_prompt)
        if "@@SEG@@" in message:
            parts = message.split("@@SEG@@")
            return "@@SEG@@".join(f"[译]{p.strip()}" for p in parts)
        return f"[译]{message.strip()}"

    monkeypatch.setattr(translate_service.llm_client, "chat", fake_chat)

    ir = _make_ir()
    translate_service.translate_ir(
        ir, translation_context='The paper title is "Hello World".'
    )

    assert prompts
    assert all('The paper title is "Hello World".' in prompt for prompt in prompts)


def test_build_translation_context_parses_glossary(monkeypatch):
    def fake_chat(message, system_prompt, **kwargs):
        assert "Paper title: DreamGuard" in message
        return '```json\n{"terms": [{"en": "world model", "zh": "世界模型"}, "bad", {"en": ""}], "extra": 1}\n```'

    monkeypatch.setattr(translate_service.llm_client, "chat", fake_chat)

    context = translate_service.build_translation_context(
        "DreamGuard", "We train a world model for agents.", override_api_key="k"
    )

    assert 'The paper title is "DreamGuard"' in context
    assert "world model = 世界模型" in context
    assert "bad" not in context


def test_build_translation_context_fails_open(monkeypatch):
    def broken_chat(**kwargs):
        raise RuntimeError("provider down")

    monkeypatch.setattr(translate_service.llm_client, "chat", broken_chat)
    assert translate_service.build_translation_context("T", "sample text") == ""

    monkeypatch.setattr(
        translate_service.llm_client, "chat", lambda **kwargs: "not json at all"
    )
    assert translate_service.build_translation_context("T", "sample text") == ""

    assert translate_service.build_translation_context("T", "   ") == ""
