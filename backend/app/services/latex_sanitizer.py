"""Sanitize LaTeX body text so that characters not present in the default
Computer-Modern fonts (e.g. raw Greek letters that MinerU/translation may
emit outside math mode) don't break the xelatex compile.

We split the body into math vs. prose regions and only rewrite prose: each
unsupported codepoint is wrapped in inline math (e.g. ``ε`` -> ``$\\varepsilon$``).
Characters that already live inside ``$...$`` / ``\\[...\\]`` / a math
environment are left untouched.
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
    "⋅": r"\cdot", "∘": r"\circ", "∗": r"\ast",
    "∈": r"\in", "∉": r"\notin", "⊂": r"\subset", "⊆": r"\subseteq",
    "⊃": r"\supset", "⊇": r"\supseteq", "∪": r"\cup", "∩": r"\cap",
    "∅": r"\emptyset", "∀": r"\forall", "∃": r"\exists",
    "∇": r"\nabla", "∂": r"\partial", "∑": r"\sum", "∏": r"\prod",
    "∫": r"\int", "∝": r"\propto",
    "ℝ": r"\mathbb{R}", "ℕ": r"\mathbb{N}", "ℤ": r"\mathbb{Z}",
    "ℚ": r"\mathbb{Q}", "ℂ": r"\mathbb{C}",
    "·": r"\cdot",
}

_MATH_ENV_NAMES = (
    "equation", r"equation\*", "align", r"align\*", "gather", r"gather\*",
    "multline", r"multline\*", "eqnarray", r"eqnarray\*",
    "math", "displaymath",
    "array", "matrix", "pmatrix", "bmatrix", "vmatrix", "Vmatrix", "smallmatrix",
)
_MATH_REGION_RE = re.compile(
    r"(?s)("
    r"\$\$.+?\$\$"
    r"|\$[^$\n]+?\$"
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
