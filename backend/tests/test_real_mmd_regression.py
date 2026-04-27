from pathlib import Path

from app.services.document_pipeline import _clean_nougat_text


def test_real_homework7_mmd_regression() -> None:
    mmd_path = Path("data/outputs/41cf6c24-dc5f-487a-a2d4-abc8de7b9dbc/nougat/homework7.mmd")
    assert mmd_path.exists()

    raw = mmd_path.read_text(encoding="utf-8", errors="ignore")
    cleaned, repaired_up_to, missing_page_count = _clean_nougat_text(raw)

    assert cleaned.startswith("## Problem 1")
    assert repaired_up_to == 1
    assert missing_page_count == 0
