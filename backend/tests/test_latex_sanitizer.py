from app.services.latex_sanitizer import find_unsupported_chars, sanitize_latex_body


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
