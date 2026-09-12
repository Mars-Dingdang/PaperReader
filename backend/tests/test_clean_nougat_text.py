from app.services.document_pipeline import (
    _clean_nougat_text_with_metadata,
    _recover_missing_leading_text,
)


def test_clean_nougat_text_no_changes_needed() -> None:
    text = "Heading\n\nBody"
    cleaned, missing_page_count, recovered_leading = _clean_nougat_text_with_metadata(text)
    assert cleaned == text
    assert missing_page_count == 0
    assert recovered_leading is False


def test_clean_nougat_text_counts_and_removes_missing_page_markers() -> None:
    text = "[MISSING_PAGE_EMPTY:1]\n\n[MISSING_PAGE_EMPTY:2]\n\n## Section\n\nBody"
    cleaned, missing_page_count, _ = _clean_nougat_text_with_metadata(text)
    assert "MISSING_PAGE_EMPTY" not in cleaned
    assert missing_page_count == 2


def test_clean_nougat_text_collapses_blank_line_runs() -> None:
    cleaned, _, _ = _clean_nougat_text_with_metadata("A\n\n\n\n\nB")
    assert cleaned == "A\n\nB"


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
