import re

from app.services.mineru_layout import (
    DisplayMath,
    Image,
    InlineMath,
    ListBlock,
    Paragraph,
    TextRun,
    Title,
    blocks_to_ir,
    collect_translatable_strings,
    apply_translations,
)
from app.services.latex_service import create_translated_tex_from_ir, render_ir_to_tex


SAMPLE_PAGES = [
    [
        {
            "type": "title",
            "content": {"title_content": [{"type": "text", "content": "Math for CS & AI: Homework 7 "}], "level": 1},
        },
        {
            "type": "paragraph",
            "content": {"paragraph_content": [{"type": "text", "content": "Sitian Ding "}]},
        },
        {
            "type": "title",
            "content": {"title_content": [{"type": "text", "content": "Problem 1 "}], "level": 1},
        },
        {
            "type": "paragraph",
            "content": {
                "paragraph_content": [
                    {"type": "text", "content": "Denote the first term as "},
                    {"type": "equation_inline", "content": "B(x)"},
                    {"type": "text", "content": ". We have "},
                ]
            },
        },
        {
            "type": "equation_interline",
            "content": {
                "math_content": "A(x) = \\sum_{n} a_n x^n",
                "math_type": "latex",
                "image_source": {"path": "images/eq1.jpg"},
            },
        },
        {
            "type": "image",
            "content": {
                "image_source": {"path": "images/fig1.jpg"},
                "image_caption": [{"type": "text", "content": "A figure caption."}],
            },
        },
    ]
]


def test_blocks_to_ir_extracts_titles_paragraphs_math_image():
    ir = blocks_to_ir(SAMPLE_PAGES)
    assert len(ir) == 6

    assert isinstance(ir[0], Title) and ir[0].level == 1 and "Math for CS" in ir[0].text
    assert isinstance(ir[1], Paragraph) and ir[1].runs == [TextRun(text="Sitian Ding ")]
    assert isinstance(ir[2], Title) and ir[2].text.strip() == "Problem 1"

    para = ir[3]
    assert isinstance(para, Paragraph)
    assert isinstance(para.runs[0], TextRun)
    assert isinstance(para.runs[1], InlineMath) and para.runs[1].latex == "B(x)"
    assert isinstance(para.runs[2], TextRun)

    assert isinstance(ir[4], DisplayMath) and ir[4].latex.startswith("A(x)")
    assert isinstance(ir[5], Image) and ir[5].rel_path == "images/fig1.jpg"
    assert ir[5].caption == "A figure caption."


def test_collect_and_apply_translations_roundtrip():
    ir = blocks_to_ir(SAMPLE_PAGES)
    segments = collect_translatable_strings(ir)
    # Title (Math for CS), paragraph (Sitian), Title (Problem 1),
    # 2 text runs in the inline-math paragraph, image caption = 6 strings.
    assert len(segments) == 6

    translations = [f"译{i}" for i in range(len(segments))]
    apply_translations(ir, translations)

    assert ir[0].text == "译0"
    assert ir[1].runs[0].text == "译1"
    assert ir[2].text == "译2"
    assert ir[3].runs[0].text == "译3"
    assert ir[3].runs[2].text == "译4"
    assert ir[5].caption == "译5"


def test_render_ir_to_tex_emits_sections_math_and_image():
    ir = blocks_to_ir(SAMPLE_PAGES)
    tex = render_ir_to_tex(ir)

    # Document scaffolding
    assert "\\documentclass" in tex
    assert "\\usepackage[UTF8,fontset=none]{ctex}" in tex
    assert "mathrsfs" in tex
    assert "\\begin{document}" in tex and "\\end{document}" in tex

    # First level-1 title becomes the \title{}/\maketitle, second becomes \section*
    assert "\\title{" in tex
    assert "\\section*{Problem 1}" in tex

    # Display math wrapped in \[ \]
    assert "\\[" in tex and "A(x) = \\sum_{n} a_n x^n" in tex and "\\]" in tex

    # Inline math wrapped in $...$
    assert "$B(x)$" in tex

    # Image included via \includegraphics with normalized relative path
    assert "\\includegraphics" in tex
    assert "{fig1.jpg}" in tex
    assert "\\caption*{A figure caption.}" in tex
    # Bound both dimensions so tall source figures are scaled down instead of
    # extending beyond (and being clipped by) the PDF page.
    assert "height=0.68\\textheight" in tex
    assert "keepaspectratio" in tex


def test_chart_panel_is_preserved_and_grouped_with_adjacent_image():
    pages = [[
        {
            "type": "title",
            "content": {
                "title_content": [{"type": "text", "content": "Paper"}],
                "level": 1,
            },
        },
        {
            "type": "image",
            "bbox": [100, 500, 400, 700],
            "content": {
                "image_source": {"path": "images/figure-4a.jpg"},
                "image_caption": [{"type": "text", "content": "(a) Left panel."}],
            },
        },
        {
            "type": "chart",
            "bbox": [420, 505, 800, 700],
            "content": {
                "image_source": {"path": "images/figure-4b.jpg"},
                "chart_caption": [
                    {"type": "text", "content": "(b) Right panel."},
                    {"type": "text", "content": "Figure 4: Complete statistics."},
                ],
            },
        },
    ]]

    ir = blocks_to_ir(pages)
    assert len(ir) == 3
    assert isinstance(ir[1], Image) and isinstance(ir[2], Image)
    assert ir[2].rel_path == "images/figure-4b.jpg"
    assert ir[1].page_index == ir[2].page_index == 0

    tex = render_ir_to_tex(ir)
    assert "{figure-4a.jpg}" in tex
    assert "{figure-4b.jpg}" in tex
    assert tex.count("\\begin{minipage}") == 2
    assert "\\caption*{Figure 4: Complete statistics.}" in tex
    # One multi-panel source figure must remain one LaTeX figure.
    assert tex.count("\\begin{figure}[H]") == 1


def test_reference_list_blocks_are_preserved_translated_and_rendered():
    pages = [[
        {
            "type": "title",
            "content": {"title_content": [{"type": "text", "content": "Paper"}], "level": 1},
        },
        {
            "type": "list",
            "content": {
                "list_type": "reference_list",
                "list_items": [
                    {
                        "item_type": "text",
                        "item_content": [
                            {"type": "text", "content": "[1] First complete reference."}
                        ],
                    },
                    {
                        "item_type": "text",
                        "item_content": [
                            {"type": "text", "content": "[2] Second reference with "},
                            {"type": "equation_inline", "content": "x^2"},
                            {"type": "text", "content": "."},
                        ],
                    },
                ],
            },
        },
    ]]

    ir = blocks_to_ir(pages)
    assert isinstance(ir[1], ListBlock)
    assert len(ir[1].items) == 2

    segments = collect_translatable_strings(ir)
    assert segments == [
        "Paper",
        "[1] First complete reference.",
        "[2] Second reference with ",
        ".",
    ]
    apply_translations(ir, ["论文", "[1] 完整文献一。", "[2] 含公式的文献", "。"])

    tex = render_ir_to_tex(ir)
    assert "\\noindent [1] 完整文献一。\\par" in tex
    assert "[2] 含公式的文献$x^2$。" in tex


def test_escape_special_characters_in_text_only():
    ir = [
        Paragraph(runs=[TextRun(text="Math & code: 50% done #1")]),
        DisplayMath(latex="a & b \\\\ c & d"),
    ]
    tex = render_ir_to_tex(ir)
    # Text & is escaped, but math content is preserved verbatim.
    assert "Math \\& code: 50\\% done \\#1" in tex
    assert "a & b \\\\ c & d" in tex


def test_escaped_currency_dollars_do_not_turn_prose_into_inline_math():
    """Regression: MinerU escaped currency markers must not span prose as math."""
    pages = [[{
        "type": "list",
        "content": {
            "list_type": "reference_list",
            "list_items": [{
                "item_type": "text",
                "item_content": [{
                    "type": "text",
                    "content": r"Prices are \$10.99 in Big & Tall and \$3.99 to $x^2$.",
                }],
            }],
        },
    }]]

    ir = blocks_to_ir(pages)
    assert isinstance(ir[0], ListBlock)
    assert [type(run) for run in ir[0].items[0]] == [TextRun, InlineMath, TextRun]
    assert ir[0].items[0][1].latex == "x^2"

    tex = render_ir_to_tex(ir)
    assert r"Prices are \$10.99 in Big \& Tall and \$3.99 to $x^2$." in tex


def test_pdf_sample_currency_and_malformed_display_math_stay_prose():
    pages = [[{
        "type": "title",
        "content": {"title_content": [{"type": "text", "content": "Samples"}], "level": 1},
    }, {
        "type": "paragraph",
        "content": {
            "paragraph_content": [{
                "type": "text",
                "content": (
                    "brownies for $3 a slice and cheesecakes for$4 a slice. "
                    r"Each is \$ \$3. $\[ 3 \times 43 = 129$ "
                    r"Then \[\[4 \times 23 = 92 \]"
                ),
            }],
        },
    }]]

    ir = blocks_to_ir(pages)
    paragraph = next(block for block in ir if isinstance(block, Paragraph))
    assert [type(run) for run in paragraph.runs] == [TextRun]

    tex = render_ir_to_tex(ir)
    assert r"\$3 a slice" in tex
    assert r"\textbackslash{}[" in tex


def test_create_translated_tex_from_ir_returns_iterable_repairs(tmp_path):
    # Regression: the function used to fall through without returning, so the
    # pipeline's `for note in repairs:` raised "'NoneType' object is not iterable".
    ir = blocks_to_ir(SAMPLE_PAGES)
    repairs = create_translated_tex_from_ir(ir, tmp_path / "translated.tex", title="Paper")
    assert isinstance(repairs, list)
    tex_written = (tmp_path / "translated.tex").read_text(encoding="utf-8")
    assert "\\begin{document}" in tex_written


def test_typed_math_output_keeps_bare_currency_dollars_literal():
    """Regression (v2.1.6 GiGPO run): content_list_v2 types math explicitly
    but strips the backslash from escaped currency. With typed math present,
    bare ``$`` in prose must stay literal instead of pairing into fake inline
    math that swallows ``Big & Tall``."""
    pages = [
        [
            {
                "type": "title",
                "content": {"title_content": [{"type": "text", "content": "Appendix"}], "level": 1},
            },
            {
                "type": "list",
                "content": {
                    "list_type": "reference_list",
                    "list_items": [
                        {
                            "item_type": "text",
                            "item_content": [
                                {
                                    "type": "text",
                                    "content": "'B09QQP3356': shirt 'Big & Tall', $10.99 to $3.99.",
                                }
                            ],
                        }
                    ],
                },
            },
            {
                "type": "paragraph",
                "content": {
                    "paragraph_content": [
                        {"type": "text", "content": "The objective "},
                        {"type": "equation_inline", "content": "J(\\theta)"},
                        {"type": "text", "content": " is maximized."},
                    ]
                },
            },
        ]
    ]

    ir = blocks_to_ir(pages)
    list_runs = next(block for block in ir if isinstance(block, ListBlock)).items[0]
    assert [type(run) for run in list_runs] == [TextRun]
    assert "$10.99 to $3.99" in list_runs[0].text

    paragraph = next(block for block in ir if isinstance(block, Paragraph))
    assert any(isinstance(run, InlineMath) and run.latex == "J(\\theta)" for run in paragraph.runs)

    tex = render_ir_to_tex(ir)
    assert not re.search(r"(?<!\\)\$\d", tex)
    assert "\\$10.99 to \\$3.99" in tex
    assert "Big \\& Tall" in tex
