from app.services.document_pipeline import _clean_nougat_text, _recover_missing_leading_text


def test_clean_nougat_text_no_changes_needed() -> None:
    text = "## Problem 1\n\nBody"
    cleaned, repaired_up_to, missing_page_count = _clean_nougat_text(text)
    assert cleaned == text
    assert repaired_up_to == 0
    assert missing_page_count == 0


def test_clean_nougat_text_repairs_abstract_problem2_case() -> None:
    text = "**Abstract**\n\nIntro text\n\n## Problem 2\n\nP2"
    cleaned, repaired_up_to, missing_page_count = _clean_nougat_text(text)
    assert cleaned.startswith("## Problem 1")
    assert "Intro text" in cleaned
    assert repaired_up_to == 1
    assert missing_page_count == 0


def test_clean_nougat_text_inserts_problem1_stub_when_starting_at_problem2() -> None:
    text = "## Problem 2\n\nP2"
    cleaned, repaired_up_to, missing_page_count = _clean_nougat_text(text)
    assert cleaned.startswith("## Problem 1")
    assert "[Content not extracted by Nougat]" in cleaned
    assert "## Problem 2" in cleaned
    assert repaired_up_to == 1
    assert missing_page_count == 0


def test_clean_nougat_text_inserts_missing_leading_problems_when_starting_at_problem3() -> None:
    text = "## Problem 3\n\nP3"
    cleaned, repaired_up_to, missing_page_count = _clean_nougat_text(text)
    assert "## Problem 1" in cleaned
    assert "## Problem 2" in cleaned
    assert cleaned.rstrip().endswith("## Problem 3\n\nP3")
    assert repaired_up_to == 2
    assert missing_page_count == 0


def test_clean_nougat_text_counts_and_removes_missing_page_markers() -> None:
    text = "[MISSING_PAGE_EMPTY:1]\n\n[MISSING_PAGE_EMPTY:2]\n\n## Problem 3\n\nP3"
    cleaned, repaired_up_to, missing_page_count = _clean_nougat_text(text)
    assert "MISSING_PAGE_EMPTY" not in cleaned
    assert missing_page_count == 2
    assert repaired_up_to == 2


def test_recover_missing_leading_text_prepends_only_missing_prefix() -> None:
    fallback = "Title Author Problem 1 setup alpha beta gamma delta epsilon zeta eta theta iota kappa lambda Problem 2 tail"
    primary = "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda Problem 2 tail"

    merged, recovered = _recover_missing_leading_text(primary, fallback)

    assert recovered is True
    assert merged.startswith("Title Author Problem 1 setup")
    assert merged.endswith("Problem 2 tail")


def test_recover_missing_leading_text_leaves_complete_content_unchanged() -> None:
    text = "Title Author alpha beta gamma delta epsilon zeta eta theta iota kappa lambda"

    merged, recovered = _recover_missing_leading_text(text, text)

    assert recovered is False
    assert merged == text
