from pathlib import Path

from app.services import document_pipeline
from app.services import translate_service


def test_process_document_uses_latex_translation_path_for_tex(monkeypatch, tmp_path: Path) -> None:
    source_path = tmp_path / "sample.tex"
    source_text = """\\documentclass{article}
\\begin{document}
Hello world.
\\end{document}
"""
    source_path.write_text(source_text, encoding="utf-8")

    output_root = tmp_path / "outputs"
    monkeypatch.setattr(document_pipeline.settings, "data_dir", tmp_path)
    monkeypatch.setattr(document_pipeline.settings, "output_dir_name", "outputs")

    nougat_called = False
    wrapper_called = False

    def fake_compile_tex_project(tex_path: Path, output_dir: Path) -> Path:
        pdf_path = output_dir / f"{tex_path.stem}.pdf"
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_path.write_bytes(b"%PDF-1.4\n")
        return pdf_path

    def fake_translate_latex_document(*args, **kwargs) -> str:
        return """\\documentclass{article}
\\begin{document}
你好，世界。
\\end{document}
"""

    def fake_extract_text_from_pdf(*args, **kwargs):
        nonlocal nougat_called
        nougat_called = True
        raise AssertionError("Nougat should not run for TEX input")

    def fake_create_translated_tex(*args, **kwargs) -> None:
        nonlocal wrapper_called
        wrapper_called = True
        raise AssertionError("Generic translated TeX wrapper should not run for TEX input")

    monkeypatch.setattr(document_pipeline, "compile_tex_project", fake_compile_tex_project)
    from app.services.latex_service import LatexCompileResult
    translated_compiler_kwargs: list[dict] = []

    def fake_compile_translated(tex_path: Path, output_dir: Path, **kwargs) -> LatexCompileResult:
        registered = output_root / record.document_id / "translated.tex"
        assert registered.is_file()
        assert any(
            artifact.kind == "translated_tex" and Path(artifact.path) == registered
            for artifact in record.artifacts
        )
        translated_compiler_kwargs.append(kwargs)
        return LatexCompileResult(fake_compile_tex_project(tex_path, output_dir))

    monkeypatch.setattr(
        document_pipeline, "compile_tex_project_with_fallback", fake_compile_translated,
    )
    monkeypatch.setattr(document_pipeline, "translate_latex_document", fake_translate_latex_document)
    monkeypatch.setattr(document_pipeline, "extract_text_from_pdf", fake_extract_text_from_pdf)
    monkeypatch.setattr(document_pipeline, "create_translated_tex", fake_create_translated_tex)

    record = document_pipeline.create_document_record(source_path, "tex")
    result = document_pipeline.process_document(record)

    assert result.status == "done", result.logs
    assert nougat_called is False
    assert wrapper_called is False
    assert translated_compiler_kwargs == [{"compiler": "xelatex"}]
    translated_tex = output_root / record.document_id / "translated.tex"
    assert translated_tex.exists()
    assert "你好，世界。" in translated_tex.read_text(encoding="utf-8")


def test_translate_latex_document_preserves_original_preamble(monkeypatch) -> None:
    source_text = """\\documentclass{article}
\\usepackage{setspace}
\\newcommand{\\Answer}{\\textbf{Answer:}}
\\newenvironment{homeworkProblem}{\\begin{quote}}{\\end{quote}}
\\begin{document}
\\begin{spacing}{1.1}
\\begin{homeworkProblem}
\\Answer Hello world.
\\end{homeworkProblem}
\\end{spacing}
\\end{document}
"""

    def fake_chat(message, system_prompt, **kwargs) -> str:
        return "[译]" + message.replace("Hello world.", "你好，世界。")

    monkeypatch.setattr(translate_service.llm_client, "chat", fake_chat)

    translated = translate_service.translate_latex_document(source_text)

    assert "\\usepackage{setspace}" in translated
    assert "\\newenvironment{homeworkProblem}" in translated
    assert translated.count("\\begin{document}") == 1
    assert translated.count("\\end{document}") == 1
    assert "你好，世界。" in translated
    # Environment commands ride through as protected placeholders and must
    # come back verbatim.
    assert translated.count("\\begin{spacing}{1.1}") == 1
    assert translated.count("\\end{spacing}") == 1
    assert translated.count("\\begin{homeworkProblem}") == 1
    assert translated.count("\\end{homeworkProblem}") == 1


def test_translate_latex_document_shims_arxiv_unicode_declaration_for_xelatex(
    monkeypatch,
) -> None:
    source_text = r"""\DeclareUnicodeCharacter{0301}{\'{e}}
\documentclass{article}
\usepackage[utf8]{inputenc}
\begin{document}
Hello world.
\end{document}
"""

    monkeypatch.setattr(
        translate_service, "_translate_latex_body", lambda *args, **kwargs: "你好。"
    )

    translated = translate_service.translate_latex_document(source_text)

    compatibility = r"\providecommand{\DeclareUnicodeCharacter}[2]{}"
    declaration = r"\DeclareUnicodeCharacter{0301}{\'{e}}"
    assert translated.index(compatibility) < translated.index(declaration)
    assert translated.count(compatibility) == 1
    assert declaration in translated
    assert "你好。" in translated

    translated_again = translate_service._ensure_xelatex_compatibility(translated)
    assert translated_again == translated


def test_translate_latex_document_does_not_add_unused_unicode_compatibility(
    monkeypatch,
) -> None:
    source_text = r"""\documentclass{article}
\begin{document}
Hello world.
\end{document}
"""

    monkeypatch.setattr(
        translate_service, "_translate_latex_body", lambda *args, **kwargs: "你好。"
    )

    translated = translate_service.translate_latex_document(source_text)

    assert r"\providecommand{\DeclareUnicodeCharacter}[2]{}" not in translated


def test_translate_latex_document_prefers_windows_cjk_font(monkeypatch) -> None:
    source_text = r"""\documentclass{article}
\begin{document}
Hello world.
\end{document}
"""

    monkeypatch.setattr(
        translate_service, "_translate_latex_body", lambda *args, **kwargs: "你好。"
    )

    translated = translate_service.translate_latex_document(source_text)

    snippet = translate_service._CJK_PREAMBLE_SNIPPET
    assert r"\usepackage{xeCJK}" in snippet
    # SimSun is a standard Windows CJK font and embeds as TrueType with a
    # ToUnicode map, so translated PDFs render even in viewers without CMap
    # support (the packaged pdf.js pane before its cMap configuration).
    # It must be tried before the macOS/Linux/Fandol fallbacks.
    assert snippet.index("SimSun") < snippet.index("Songti SC")
    assert snippet.index("Songti SC") < snippet.index("PingFang SC")
    assert snippet.index("PingFang SC") < snippet.index("Noto Serif CJK SC")
    assert snippet.index("Noto Serif CJK SC") < snippet.index("FandolSong")
    # The chain is injected right before \begin{document}, ahead of the body.
    assert translated.index(snippet.strip().splitlines()[1]) < translated.index(
        r"\begin{document}"
    )


def test_ensure_cjk_support_skips_documents_that_already_declare_cjk() -> None:
    prefix = (
        r"\documentclass{article}"
        "\n"
        r"\usepackage[UTF8]{ctex}"
        "\n"
        r"\begin{document}"
    )

    assert translate_service._ensure_cjk_support(prefix) == prefix


def test_ensure_cjk_support_ignores_commented_cjk_packages() -> None:
    # aaai2027.sty's template lists forbidden packages in comments; that must
    # not count as existing CJK support or Chinese renders in the Latin text
    # font and disappears from the PDF.
    prefix = (
        r"\documentclass{article}"
        "\n"
        r"% \usepackage{CJK} -- This package is specifically forbidden"
        "\n"
        r"\begin{document}"
    )

    supported = translate_service._ensure_cjk_support(prefix)

    assert r"\usepackage{xeCJK}" in supported
    assert supported.rindex(r"\usepackage{xeCJK}") < supported.rindex(
        r"\begin{document}"
    )
