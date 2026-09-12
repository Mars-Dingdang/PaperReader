from app.services.alignment_service import locate_in_alignment, proportional_highlight


def _entry(index, position, original, translated):
    return {
        "index": index,
        "position": position,
        "original": original,
        "translated": translated,
        "kind": "translation_segment",
    }


def test_repeated_phrase_prefers_entry_nearest_source_page():
    needle_text = "the flux depends on the Reynolds number"
    entries = [
        _entry(0, 0.05, f"Early discussion. {needle_text} in the abstract context.", "译文一：雷诺数"),
        _entry(1, 0.85, f"Later discussion. {needle_text} near the conclusion.", "译文二：雷诺数"),
    ]
    _, _, _, best_index, _ = locate_in_alignment(
        entries, source_side="original", selected_text=needle_text, page_ratio=0.85
    )
    assert best_index == 1


def test_close_entries_still_pick_best_lexical_match():
    entries = [
        _entry(0, 0.0, "totally unrelated content about viscosity", "无关译文"),
        _entry(1, 0.9, "the vorticity equation governs the flow field", "涡量方程控制流场"),
    ]
    target, _, confidence, best_index, _ = locate_in_alignment(
        entries, source_side="original", selected_text="the vorticity equation", page_ratio=0.0
    )
    assert best_index == 1
    assert confidence >= 0.9
    assert "涡量方程" in target


def test_low_confidence_returns_zero_and_empty_highlight():
    entries = [_entry(0, 0.5, "some unrelated physics text", "无关译文")]
    _, _, confidence, _, highlight = locate_in_alignment(
        entries, source_side="original", selected_text="quantum chromodynamics gauge theory", page_ratio=0.5
    )
    assert confidence == 0.0
    assert highlight == ""


def test_highlight_lands_near_selected_part_of_block():
    source = (
        "First sentence introduces the topic. "
        "Second sentence derives the momentum equation for the fluid. "
        "Third sentence discusses the boundary conditions at the wall. "
        "Fourth sentence concludes the analysis of the flow."
    )
    target = (
        "第一句介绍主题。"
        "第二句推导流体的动量方程。"
        "第三句讨论壁面处的边界条件。"
        "第四句总结流动分析。"
    )
    highlight = proportional_highlight(source, "Third sentence discusses the boundary conditions", target)
    assert "边界条件" in highlight
    assert "第一句" not in highlight
    assert "第四句" not in highlight


def test_highlight_covers_target_when_selection_spans_block():
    source = "Short complete block about drag coefficients."
    target = "关于阻力系数的完整短块。"
    highlight = proportional_highlight(source, source, target)
    assert highlight == target


def test_translated_side_lookup_maps_back_to_original():
    entries = [
        _entry(0, 0.3, "原文段落一", "Translated paragraph one about turbulence models"),
        _entry(1, 0.7, "原文段落二", "Translated paragraph two about wall functions"),
    ]
    target, _, confidence, best_index, _ = locate_in_alignment(
        entries,
        source_side="translated",
        selected_text="paragraph two about wall functions",
        page_ratio=0.7,
    )
    assert best_index == 1
    assert confidence >= 0.55
    assert target == "原文段落二"
