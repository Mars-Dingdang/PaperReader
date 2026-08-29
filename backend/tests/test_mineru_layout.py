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
from app.services.latex_service import render_ir_to_tex


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
    assert "\\usepackage[UTF8]{ctex}" in tex
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
