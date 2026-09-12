from app.services.latex_sanitizer import (
    detect_font_unsafe_chars,
    find_unsupported_chars,
    repair_common_math_faults,
    sanitize_and_repair,
    sanitize_latex_body,
    validate_latex_structure,
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


def test_sanitize_math_star_and_real_control_characters() -> None:
    out, repairs = sanitize_and_repair("score ⋆ best" + chr(1) + " and more" + chr(22))
    assert out == r"score $\star$ best and more"
    assert any("control" in note for note in repairs)


def test_sanitize_removes_unicode_replacement_marker() -> None:
    out, repairs = sanitize_and_repair("我们发\ufffd现了这个结果。")

    assert out == "我们发现了这个结果。"
    assert any("Unicode replacement" in note for note in repairs)


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


def test_repair_invalid_math_alphabet_and_accent_nesting() -> None:
    src = r"$\mathbf { \Delta } a + \mathrm { \bar { G i G P O } }$"
    fixed, repairs = repair_common_math_faults(src)
    assert r"\boldsymbol{\Delta}" in fixed
    assert r"\overline{\mathrm{G i G P O}}" in fixed
    assert len(repairs) == 2


def test_validate_math_structure_reports_lines() -> None:
    doc = (
        "\\documentclass{article}\n"
        "Good line $x=1$ here.\n"
        "Plain prose on this line.\n"
        "Braces $\\frac{a}{b}$ ok \\quad ${ x }$ ok\n"
        r"Faulty ${ \sqrt [ { k } / { a _ { n } } ] }$" + "\n"
        "Broken $unclosed math\n"
    )
    issues = validate_math_structure(doc)
    lines = {line for line, _ in issues}
    messages = [msg for _, msg in issues]
    assert 6 in lines  # unclosed '$' at end of document
    assert 5 in lines  # malformed \sqrt survives (lint reports, does not modify)
    assert any("sqrt" in m for m in messages)
    assert 2 not in lines  # clean line stays clean


def test_validate_latex_structure_reports_general_compile_hazards() -> None:
    doc = (
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "\\section*{broken title\n"
        "plain Big & Tall text\n"
        "\\begin{itemize}\\item x\\end{enumerate}\n"
        + "bad" + chr(1) + " control and ∷ glyph\n"
        "\\end{document}\n"
    )
    issues = validate_latex_structure(doc)
    messages = "\n".join(message for _, message in issues)
    assert "unbalanced braces" in messages
    assert "bare '&'" in messages
    assert "environment" in messages
    assert "control" in messages
    assert "font-unsafe" in messages


def test_validate_latex_structure_accepts_legal_tex_contexts() -> None:
    doc = (
        "\\documentclass{article}\n"
        "\\newcommand{\\identity}[1]{#1}\n"
        "\\begin{document}\n"
        "Price \\$10.99 and escaped \\& are prose.\n"
        "\\begin{tabular}{cc}a & b \\\\ c & d\\end{tabular}\n"
        "\\begin{align}x &= y \\\\ z &= 1\\end{align}\n"
        "$a+b$ and \\(c+d\\).\n"
        "\\end{document}\n"
    )
    assert validate_latex_structure(doc) == []


def test_validate_latex_structure_accepts_multiline_math_verbatim_and_comments() -> None:
    doc = (
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "$a +\n b$ is valid multiline math.\n"
        r"\verb|literal { & ∷ $| is opaque." + "\n"
        "% comment with { & ∷ $ is ignored\n"
        "\\begin{verbatim}\n"
        "literal { & ∷ $\n"
        "\\end{verbatim}\n"
        "\\end{document}\n"
    )

    assert validate_latex_structure(doc) == []


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


def test_repair_stray_closing_braces_removes_only_unmatched() -> None:
    from app.services.latex_sanitizer import repair_stray_closing_braces

    text = (
        r"论文：\url{https://arxiv.org/abs/2603.27148}.} 代码见仓库。" + "\n"
        + r"\textbf{加粗 {嵌套} 文本}" + "\n"
    )
    repaired, repairs = repair_stray_closing_braces(text)

    assert r"\url{https://arxiv.org/abs/2603.27148}. 代码见仓库。" in repaired
    assert r"\textbf{加粗 {嵌套} 文本}" in repaired
    assert len(repairs) == 1
    assert repairs[0].startswith("L1: removed 1 closing brace")


def test_repair_stray_closing_braces_ignores_comments_and_verbatim() -> None:
    from app.services.latex_sanitizer import repair_stray_closing_braces

    text = (
        "\\begin{verbatim}\n"
        "stray } inside verbatim\n"
        "\\end{verbatim}\n"
        "prose } % comment with }\n"
    )
    repaired, repairs = repair_stray_closing_braces(text)

    assert "stray } inside verbatim" in repaired
    assert repairs and repairs[0].startswith("L4:")


def test_alignment_advisory_accepts_alignedat() -> None:
    text = (
        "\\begin{equation}\n"
        "\\begin{alignedat}{2}\n"
        "&\\text{左} &&\\quad x = 1 \\\\\n"
        "&\\text{右} &&\\quad y = 2\n"
        "\\end{alignedat}\n"
        "\\end{equation}\n"
    )

    assert validate_latex_structure(text) == []


def test_repair_prose_underscores_escapes_bare_underscore() -> None:
    from app.services.latex_sanitizer import repair_prose_underscores

    text = (
        "\\textbf{User instruction:} [user_instruction] follows.\n"
        "Math $a_1$ stays, and \\begin{my_env}\\end{my_env} survives.\n"
    )
    repaired, repairs = repair_prose_underscores(text)

    assert "[user\\_instruction]" in repaired
    assert "$a_1$" in repaired, "math underscores are untouched"
    assert "\\begin{my_env}" in repaired, "command arguments are untouched"
    assert len(repairs) == 1


def test_repair_linebreak_optional_args_inserts_group() -> None:
    from app.services.latex_sanitizer import repair_linebreak_optional_args

    text = "\\textbf{Format} \\\\\n[Scratchpad] follows: $x$\n"
    repaired, repairs = repair_linebreak_optional_args(text)

    assert "\\{}" in repaired
    assert "[Scratchpad]" in repaired
    assert len(repairs) == 1

    spaced = "\\textbf{Format} \\\\[2ex]\nnext\n"
    kept, repairs2 = repair_linebreak_optional_args(spaced)
    assert kept == spaced
    assert repairs2 == []
