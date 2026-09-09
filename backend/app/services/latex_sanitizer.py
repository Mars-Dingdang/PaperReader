"""Sanitize LaTeX body text so that characters not present in the default
Computer-Modern fonts (e.g. raw Greek letters that MinerU/translation may
emit outside math mode) don't break the xelatex compile.

We split the body into math vs. prose regions and only rewrite prose: each
unsupported codepoint is wrapped in inline math (e.g. ``ε`` -> ``$\\varepsilon$``).
Characters that already live inside ``$...$`` / ``\\[...\\]`` / a math
environment are left untouched.

Additionally this module repairs well-known MinerU/OCR math faults (e.g. a
``\\sqrt`` whose radicand was swallowed into the root index) and lints the
document for structural problems (unbalanced ``$``/braces) so failures can
be reported with line numbers instead of a raw latexmk tail.
"""

from __future__ import annotations

import re

# Map of single Unicode characters -> LaTeX command (without $...$ wrapper).
_CHAR_TO_LATEX: dict[str, str] = {
    # Greek lowercase
    "α": r"\alpha", "β": r"\beta", "γ": r"\gamma", "δ": r"\delta",
    "ε": r"\varepsilon", "ϵ": r"\epsilon", "ζ": r"\zeta", "η": r"\eta",
    "θ": r"\theta", "ϑ": r"\vartheta", "ι": r"\iota", "κ": r"\kappa",
    "λ": r"\lambda", "μ": r"\mu", "ν": r"\nu", "ξ": r"\xi",
    "π": r"\pi", "ϖ": r"\varpi", "ρ": r"\rho", "ϱ": r"\varrho",
    "σ": r"\sigma", "ς": r"\varsigma", "τ": r"\tau", "υ": r"\upsilon",
    "φ": r"\varphi", "ϕ": r"\phi", "χ": r"\chi", "ψ": r"\psi", "ω": r"\omega",
    # Greek uppercase
    "Γ": r"\Gamma", "Δ": r"\Delta", "Θ": r"\Theta", "Λ": r"\Lambda",
    "Ξ": r"\Xi", "Π": r"\Pi", "Σ": r"\Sigma", "Υ": r"\Upsilon",
    "Φ": r"\Phi", "Ψ": r"\Psi", "Ω": r"\Omega",
    # Common math operators / arrows
    "≤": r"\leq", "≥": r"\geq", "≠": r"\neq", "≈": r"\approx", "≡": r"\equiv",
    "∼": r"\sim", "≅": r"\cong", "∞": r"\infty",
    "→": r"\to", "←": r"\leftarrow", "↔": r"\leftrightarrow",
    "⇒": r"\Rightarrow", "⇐": r"\Leftarrow", "⇔": r"\Leftrightarrow",
    "↦": r"\mapsto",
    "×": r"\times", "÷": r"\div", "±": r"\pm", "∓": r"\mp",
    "⋅": r"\cdot", "∘": r"\circ", "∗": r"\ast", "⋆": r"\star",
    "∈": r"\in", "∉": r"\notin", "⊂": r"\subset", "⊆": r"\subseteq",
    "⊃": r"\supset", "⊇": r"\supseteq", "∪": r"\cup", "∩": r"\cap",
    "∅": r"\emptyset", "∀": r"\forall", "∃": r"\exists",
    "∇": r"\nabla", "∂": r"\partial", "∑": r"\sum", "∏": r"\prod",
    "∫": r"\int", "∝": r"\propto",
    "ℝ": r"\mathbb{R}", "ℕ": r"\mathbb{N}", "ℤ": r"\mathbb{Z}",
    "ℚ": r"\mathbb{Q}", "ℂ": r"\mathbb{C}",
    "·": r"\cdot",
    # Proof marks / geometric shapes / dingbats that Latin Modern lacks but
    # amssymb provides. Common in CJK lecture notes and OCR output (□ marks
    # the end of a proof in Chinese textbooks).
    "□": r"\square", "■": r"\blacksquare", "▪": r"\blacksquare",
    "▫": r"\square", "◻": r"\square", "◼": r"\blacksquare",
    "◽": r"\square", "◾": r"\blacksquare",
    "●": r"\bullet", "○": r"\circ", "◦": r"\bullet", "◎": r"\circ",
    "★": r"\bigstar", "☆": r"\bigstar",
    "♠": r"\spadesuit", "♤": r"\spadesuit",
    "♥": r"\heartsuit", "♡": r"\heartsuit",
    "♦": r"\diamondsuit", "♢": r"\diamondsuit",
    "♣": r"\clubsuit", "♧": r"\clubsuit",
    "✓": r"\checkmark", "✔": r"\checkmark",
    "✗": r"\times", "✘": r"\times", "✕": r"\times",
    "℃": r"{}^{\circ}\mathrm{C}",
}

_MATH_ENV_NAMES = (
    "equation", r"equation\*", "align", r"align\*", "gather", r"gather\*",
    "multline", r"multline\*", "eqnarray", r"eqnarray\*",
    "math", "displaymath",
    "array", "matrix", "pmatrix", "bmatrix", "vmatrix", "Vmatrix", "smallmatrix",
)
_MATH_REGION_RE = re.compile(
    r"(?s)("
    r"(?<!\\)\$\$.+?(?<!\\)\$\$"
    r"|(?<!\\)\$[^$\n]+?(?<!\\)\$"
    r"|\\\[.+?\\\]"
    r"|\\\(.+?\\\)"
    r"|\\begin\{(?:" + "|".join(_MATH_ENV_NAMES) + r")\}.+?"
    r"\\end\{(?:" + "|".join(_MATH_ENV_NAMES) + r")\}"
    r")"
)


def _sanitize_prose(text: str) -> str:
    out_parts: list[str] = []
    for ch in text:
        latex = _CHAR_TO_LATEX.get(ch)
        if latex is None:
            out_parts.append(ch)
        else:
            out_parts.append(f"${latex}$")
    return "".join(out_parts)


def sanitize_latex_body(text: str) -> str:
    """Replace raw unicode math/Greek characters appearing in prose regions
    with proper inline-math LaTeX equivalents. Math regions are preserved.
    """
    if not text:
        return text
    out: list[str] = []
    last = 0
    for match in _MATH_REGION_RE.finditer(text):
        prose = text[last:match.start()]
        out.append(_sanitize_prose(prose))
        out.append(match.group(0))
        last = match.end()
    out.append(_sanitize_prose(text[last:]))
    return "".join(out)


_BEGIN_DOC = "\\begin{document}"
_END_DOC = "\\end{document}"


def _split_document(text: str) -> tuple[str, str, str] | None:
    """Split a complete LaTeX document into (preamble, body, tail).

    Returns None when `text` is not a full document (no/invalid
    \\begin{document} ... \\end{document} frame) — e.g. a bare body passed
    in from the translate path.
    """
    begin = text.find(_BEGIN_DOC)
    end = text.rfind(_END_DOC)
    if begin == -1 or end == -1 or end < begin:
        return None
    return (
        text[: begin + len(_BEGIN_DOC)],
        text[begin + len(_BEGIN_DOC) : end],
        text[end:],
    )


def find_unsupported_chars(text: str) -> set[str]:
    """Return the set of characters in `text` that are mapped (i.e. would be
    rewritten by sanitize_latex_body) and currently appear in prose regions.
    Useful for diagnostics / vision-check feedback.
    """
    if not text:
        return set()
    found: set[str] = set()
    last = 0
    for match in _MATH_REGION_RE.finditer(text):
        for ch in text[last:match.start()]:
            if ch in _CHAR_TO_LATEX:
                found.add(ch)
        last = match.end()
    for ch in text[last:]:
        if ch in _CHAR_TO_LATEX:
            found.add(ch)
    return found


# ---------------------------------------------------------------------------
# Font-coverage diagnostics
# ---------------------------------------------------------------------------

# Routers (xeCJK/ctex) already hand these blocks to the CJK font, so their
# codepoints are compile-safe even though Latin Modern lacks the glyphs.
_CJK_SAFE_RANGES = (
    (0x3000, 0x303F),   # CJK symbols and punctuation （ 、 。 「 」 …）
    (0x3400, 0x4DBF),   # CJK extension A
    (0x4E00, 0x9FFF),   # CJK unified ideographs
    (0xF900, 0xFAFF),   # CJK compatibility ideographs
    (0xFF00, 0xFFEF),   # fullwidth forms （ ！ ？ ， ）
    (0x20000, 0x2A6DF), # CJK extension B
)

# Non-ASCII codepoints that Latin Modern does provide (quotes, dashes,
# ellipsis, degree sign, daggers, middle dots, spaces).
_FONT_SAFE_EXTRAS = set("‘’“”„‚‛‹›«»–—…•·°†‡℃\u00a0\u2002\u2003\u2007\u2009\u202f")


def replacement_for(ch: str) -> str | None:
    """LaTeX command that `sanitize_latex_body` would substitute for `ch`
    (without the surrounding ``$...$``), or None when unmapped.
    """
    return _CHAR_TO_LATEX.get(ch)


def _is_font_safe_char(ch: str) -> bool:
    code = ord(ch)
    if code < 0x80:
        return True
    # Latin Modern/OpenType covers Latin-1, Latin Extended, IPA/modifier
    # letters and combining marks used in author names and phonetic notation.
    if 0x00A0 <= code <= 0x036F:
        return True
    if ch in _CHAR_TO_LATEX:
        return True  # sanitize_latex_body converts it to a command
    if ch in _FONT_SAFE_EXTRAS:
        return True
    return any(lo <= code <= hi for lo, hi in _CJK_SAFE_RANGES)


def detect_font_unsafe_chars(text: str) -> dict[str, int]:
    """Count non-ASCII characters that no configured font is known to cover
    and that no LaTeX replacement exists for. These are the characters likely
    to trigger ``Missing character`` warnings (or worse) at compile time.
    """
    found: dict[str, int] = {}
    for ch in text:
        if ch in ("\n", "\r", "\t"):
            continue
        if not _is_font_safe_char(ch):
            found[ch] = found.get(ch, 0) + 1
    return found


# ---------------------------------------------------------------------------
# OCR math-fault repair and structural lint
# ---------------------------------------------------------------------------

# A braced atom with up to two levels of nesting, e.g. ``{ a _ { n } }``.
_BRACED = r"\{(?:[^{}]|\{(?:[^{}]|\{[^{}]*\})*\})*\}"

# MinerU sometimes reads ``\sqrt[k]{a_n}`` as ``\sqrt[{k}/{a_n}]``: the
# radicand lands inside the root index and the mandatory argument goes
# missing. Two variants occur in the wild:
#   A) ``\sqrt [ {X} / {Y} ]``   – brackets closed, radicand missing
#   B) ``\sqrt [ {X} / {Y} }``   – the closing ``]`` itself became ``}``
_SQRT_FAULT_A_RE = re.compile(
    r"\\sqrt[ \t]*\[[ \t]*(" + _BRACED + r")[ \t]*/[ \t]*(" + _BRACED + r")[ \t]*\](?![ \t]*\{)"
)
_SQRT_FAULT_B_RE = re.compile(
    r"\\sqrt[ \t]*\[[ \t]*(" + _BRACED + r")[ \t]*/[ \t]*(" + _BRACED + r")[ \t]*\}"
)
_GREEK_COMMANDS = (
    "alpha|beta|gamma|delta|epsilon|varepsilon|zeta|eta|theta|vartheta|iota|"
    "kappa|lambda|mu|nu|xi|pi|varpi|rho|varrho|sigma|varsigma|tau|upsilon|"
    "phi|varphi|chi|psi|omega|Gamma|Delta|Theta|Lambda|Xi|Pi|Sigma|Upsilon|Phi|Psi|Omega"
)
_MATHBF_GREEK_RE = re.compile(
    r"\\mathbf\s*\{\s*(\\(?:" + _GREEK_COMMANDS + r"))\s*\}"
)
_ROMAN_ACCENT_RE = re.compile(
    r"\\mathrm\s*\{\s*\\(bar|hat|tilde)\s*\{\s*([^{}]+?)\s*\}\s*\}"
)


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def repair_common_math_faults(text: str) -> tuple[str, list[str]]:
    """Best-effort repair of known OCR math faults. Returns the repaired
    text plus one human-readable note per repair (with 1-based line numbers
    referring to the *input* text).
    """
    if not text:
        return text, []
    repairs: list[str] = []

    def fix_variant_a(match: re.Match[str]) -> str:
        line = _line_of(text, match.start())
        repairs.append(
            f"L{line}: moved '\\sqrt' radicand out of the root index "
            f"({match.group(0).strip()} -> '\\sqrt[{match.group(1).strip()}]{{{match.group(2).strip()}}}')"
        )
        return f"\\sqrt[{match.group(1)}]{{{match.group(2)}}}"

    def fix_variant_b(match: re.Match[str]) -> str:
        line = _line_of(text, match.start())
        repairs.append(
            f"L{line}: repaired '\\sqrt' with unclosed root index "
            f"({match.group(0).strip()} -> '\\sqrt[{match.group(1).strip()}]{{{match.group(2).strip()}}}')"
        )
        # The trailing '}' terminated the enclosing group in the source, so
        # re-emit it to keep brace balance.
        return f"\\sqrt[{match.group(1)}]{{{match.group(2)}}}}}"

    # Variant A first: when both could match, A's explicit `]` is the more
    # faithful reading of the OCR output.
    repaired = _SQRT_FAULT_A_RE.sub(fix_variant_a, text)
    repaired = _SQRT_FAULT_B_RE.sub(fix_variant_b, repaired)

    def fix_bold_greek(match: re.Match[str]) -> str:
        line = _line_of(text, match.start())
        repairs.append(f"L{line}: replaced \\mathbf around a Greek symbol with \\boldsymbol")
        return f"\\boldsymbol{{{match.group(1)}}}"

    def fix_roman_accent(match: re.Match[str]) -> str:
        line = _line_of(text, match.start())
        accent = {"bar": "overline", "hat": "widehat", "tilde": "widetilde"}[match.group(1)]
        repairs.append(f"L{line}: moved math accent outside \\mathrm")
        return f"\\{accent}{{\\mathrm{{{match.group(2).strip()}}}}}"

    repaired = _MATHBF_GREEK_RE.sub(fix_bold_greek, repaired)
    repaired = _ROMAN_ACCENT_RE.sub(fix_roman_accent, repaired)
    return repaired, repairs


def _count_unescaped(text: str, char: str) -> int:
    count = 0
    for offset, current in enumerate(text):
        if current != char:
            continue
        slashes = 0
        cursor = offset - 1
        while cursor >= 0 and text[cursor] == "\\":
            slashes += 1
            cursor -= 1
        if slashes % 2 == 0:
            count += 1
    return count


def validate_math_structure(text: str) -> list[tuple[int, str]]:
    """Lint `text` for LaTeX math-structure problems that would fatal at
    compile time. Returns ``(line, message)`` pairs (1-based lines).
    """
    issues: list[tuple[int, str]] = []
    if not text:
        return issues

    for line_no, line in enumerate(text.splitlines(), start=1):
        if _count_unescaped(line, "$") % 2 == 1:
            issues.append((line_no, "unbalanced '$' (odd number of unescaped '$' on the line)"))

    for match in _MATH_REGION_RE.finditer(text):
        segment = match.group(0)
        depth = _count_unescaped(segment, "{") - _count_unescaped(segment, "}")
        if depth != 0:
            issues.append((
                _line_of(text, match.start()),
                f"unbalanced braces in math region (depth {depth:+d}): {segment[:60]!r}",
            ))

    for pattern, hint in (
        (_SQRT_FAULT_A_RE, "\\sqrt root index contains '/' and the mandatory radicand is missing"),
        (_SQRT_FAULT_B_RE, "\\sqrt root index is never closed with ']' and the radicand is missing"),
    ):
        for match in pattern.finditer(text):
            issues.append((_line_of(text, match.start()), hint))

    return issues


_ALIGNMENT_ENVIRONMENTS = {
    "align", "align*", "aligned", "alignat", "alignat*", "array",
    "tabular", "tabular*", "matrix", "pmatrix", "bmatrix", "vmatrix",
    "Vmatrix", "smallmatrix", "cases", "eqnarray", "eqnarray*",
}
_ENV_TOKEN_RE = re.compile(r"\\(begin|end)\{([^{}]+)\}")


def _is_escaped_at(text: str, offset: int) -> bool:
    slashes = 0
    offset -= 1
    while offset >= 0 and text[offset] == "\\":
        slashes += 1
        offset -= 1
    return slashes % 2 == 1


def _without_comment(line: str) -> str:
    for offset, ch in enumerate(line):
        if ch == "%" and not _is_escaped_at(line, offset):
            return line[:offset]
    return line


def validate_latex_structure(text: str) -> list[tuple[int, str]]:
    """Conservative preflight for hazards outside the existing math lint.

    The function reports only; it never rewrites source. Alignment tabs remain
    legal inside table/matrix/alignment environments and escaped TeX specials
    are ignored.
    """
    if not text:
        return []
    issues = list(validate_math_structure(text))
    environment_stack: list[tuple[str, int]] = []
    brace_stack: list[int] = []

    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = _without_comment(raw_line)
        events = {match.start(): match for match in _ENV_TOKEN_RE.finditer(line)}
        cursor = 0
        while cursor < len(line):
            event = events.get(cursor)
            if event is not None:
                action, name = event.group(1), event.group(2)
                if action == "begin":
                    environment_stack.append((name, line_no))
                elif not environment_stack:
                    issues.append((line_no, f"environment '{name}' ends without a matching begin"))
                elif environment_stack[-1][0] != name:
                    expected = environment_stack[-1][0]
                    issues.append((line_no, f"environment mismatch: expected end{{{expected}}}, got end{{{name}}}"))
                    environment_stack.pop()
                else:
                    environment_stack.pop()
                cursor = event.end()
                continue

            ch = line[cursor]
            escaped = _is_escaped_at(line, cursor)
            if ch == "{" and not escaped:
                brace_stack.append(line_no)
            elif ch == "}" and not escaped:
                if brace_stack:
                    brace_stack.pop()
                else:
                    issues.append((line_no, "unbalanced braces: unexpected '}'"))
            elif ch == "&" and not escaped:
                if not any(name in _ALIGNMENT_ENVIRONMENTS for name, _ in environment_stack):
                    issues.append((line_no, "bare '&' outside an alignment/table environment"))
            if ord(ch) < 32 and ch not in "\n\r\t":
                issues.append((line_no, f"unsafe C0 control character U+{ord(ch):04X}"))
            cursor += 1

        for ch in raw_line:
            if ord(ch) >= 32 and not _is_font_safe_char(ch):
                issues.append((line_no, f"font-unsafe character {ch!r} (U+{ord(ch):04X})"))

    if brace_stack:
        issues.append((brace_stack[-1], f"unbalanced braces: {len(brace_stack)} opening brace(s) remain"))
    for name, line_no in environment_stack:
        issues.append((line_no, f"environment '{name}' is not closed"))

    return sorted(set(issues), key=lambda issue: (issue[0], issue[1]))


def sanitize_and_repair(text: str) -> tuple[str, list[str]]:
    """Combined pipeline hook: sanitize prose characters, then repair known
    OCR math faults. Returns the new text and repair notes (empty when
    nothing had to be fixed).

    When `text` is a complete document, only the body between
    \\begin{document} and \\end{document} is rewritten: the preamble may
    contain \\newunicodechar{□}{...} declarations whose first argument must
    stay a single literal character, so substituting it (e.g. to
    ``$\\square$``) breaks the compile with "Invalid argument".
    """
    control_count = sum(1 for ch in text if ord(ch) < 32 and ch not in "\n\r\t")
    if control_count:
        text = "".join(ch for ch in text if ord(ch) >= 32 or ch in "\n\r\t")
    control_repairs = (
        [f"Removed {control_count} unsafe C0 control character(s)"]
        if control_count
        else []
    )
    parts = _split_document(text)
    if parts is None:
        sanitized = sanitize_latex_body(text)
        repaired, repairs = repair_common_math_faults(sanitized)
        return repaired, control_repairs + repairs
    head, body, tail = parts
    body, repairs = repair_common_math_faults(sanitize_latex_body(body))
    return head + body + tail, control_repairs + repairs
