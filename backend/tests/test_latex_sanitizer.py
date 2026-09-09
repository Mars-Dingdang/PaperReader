from app.services.latex_sanitizer import (
    detect_font_unsafe_chars,
    find_unsupported_chars,
    repair_common_math_faults,
    sanitize_and_repair,
    sanitize_latex_body,
    validate_math_structure,
)


def test_sanitize_prose_greek_to_inline_math() -> None:
    src = "Set ε to 0.1 and let α≤β."
    out = sanitize_latex_body(src)
    assert r"$\varepsilon$" in out
    assert r"$\alpha$" in out
    assert r"$\leq$" in out
    assert r"$\beta$" in out
    assert "ε" not in out
    assert "≤" not in out


def test_sanitize_preserves_math_regions() -> None:
    src = r"Inline $\alpha \leq \beta$ stays. Also \begin{equation}ε\end{equation} kept."
    out = sanitize_latex_body(src)
    # Inline-math content untouched
    assert r"$\alpha \leq \beta$" in out
    # Equation environment kept verbatim including the raw ε inside it
    assert r"\begin{equation}ε\end{equation}" in out


def test_sanitize_preserves_inline_dollar_with_unicode() -> None:
    src = "Use $a \\cdot b$ then say π is fine."
    out = sanitize_latex_body(src)
    assert "$a \\cdot b$" in out
    assert r"$\pi$" in out
    assert "π is fine" not in out


def test_find_unsupported_chars_only_prose() -> None:
    src = r"prose ε and math $\varepsilon$ then ≤"
    found = find_unsupported_chars(src)
    assert "ε" in found
    assert "≤" in found


def test_sanitize_proof_marks_to_inline_math() -> None:
    src = "证明完毕□ 以及 ■ 和 ✓✗。"
    out = sanitize_latex_body(src)
    assert r"$\square$" in out
    assert r"$\blacksquare$" in out
    assert r"$\checkmark$" in out
    assert r"$\times$" in out
    assert "□" not in out


def test_detect_font_unsafe_chars_flags_unknown_only() -> None:
    src = "中文 ok ‘—…’ □ ε ∷"
    found = detect_font_unsafe_chars(src)
    # CJK, mapped chars (□/ε), and Latin-Modern punctuation pass through
    assert "□" not in found
    assert "ε" not in found
    assert "中" not in found
    assert "—" not in found
    # Unmapped, non-CJK, font-unknown symbols are reported
    assert found.get("∷") == 1


def test_repair_sqrt_radicand_swallowed_into_index() -> None:
    # Variant A (regression fixture: line 740 of the 数列极限 lecture)
    src = r"$\lim { \sqrt [ { k } / { a _ { n } } ] } = 1$"
    fixed, repairs = repair_common_math_faults(src)
    assert r"\sqrt[{ k }]{{ a _ { n } }}" in fixed
    assert len(repairs) == 1
    assert repairs[0].startswith("L1:")


def test_repair_sqrt_unclosed_root_index() -> None:
    # Variant B: the closing `]` itself became `}`
    src = r"(1) k，${ \sqrt [ { k } / { A } } ;$"
    fixed, repairs = repair_common_math_faults(src)
    assert r"{ \sqrt[{ k }]{{ A }}}" in fixed
    assert len(repairs) == 1
    assert validate_math_structure(fixed) == []


def test_repair_leaves_valid_sqrt_untouched() -> None:
    src = r"$\sqrt [ { k } ] { A } + \sqrt [ { k } / { a } ] { b }$"
    fixed, repairs = repair_common_math_faults(src)
    assert fixed == src
    assert repairs == []


def test_validate_math_structure_reports_lines() -> None:
    doc = (
        "\\documentclass{article}\n"
        "Good line $x=1$ here.\n"
        "Broken $unclosed math\n"
        "Braces $\\frac{a}{b}$ ok \\quad ${ x }$ ok\n"
        r"Faulty ${ \sqrt [ { k } / { a _ { n } } ] }$" + "\n"
    )
    issues = validate_math_structure(doc)
    lines = {line for line, _ in issues}
    messages = [msg for _, msg in issues]
    assert 3 in lines  # odd '$' count
    assert 5 in lines  # malformed \sqrt survives (lint reports, does not modify)
    assert any("sqrt" in m for m in messages)
    assert 2 not in lines  # clean line stays clean


def test_sanitize_and_repair_combined() -> None:
    src = "证明□\n" + r"$\lim { \sqrt [ { k } / { A } }$" + "\n"
    out, repairs = sanitize_and_repair(src)
    assert r"$\square$" in out
    assert len(repairs) == 1
    assert validate_math_structure(out) == []


def test_sanitize_and_repair_leaves_preamble_untouched() -> None:
    # Regression (v2.1.5): sanitize_and_repair used to rewrite the preamble's
    # \newunicodechar{□}{...} declaration into \newunicodechar{$\square$}{...},
    # and newunicodechar then aborted the compile with "Invalid argument"
    # because its first argument must be a single literal character.
    doc = (
        "\\documentclass[12pt]{article}\n"
        "\\usepackage{newunicodechar}\n"
        "\\newunicodechar{□}{\\ensuremath{\\square}}\n"
        "\\begin{document}\n"
        "证明完毕□\n"
        "\\end{document}\n"
    )
    out, repairs = sanitize_and_repair(doc)
    assert "\\newunicodechar{□}{\\ensuremath{\\square}}" in out
    assert "$\\square$" not in out.split("\\begin{document}")[0]
    # Body prose is still sanitized
    assert "证明完毕$\\square$" in out
    assert repairs == []
