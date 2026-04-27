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
    monkeypatch.setattr(document_pipeline, "translate_latex_document", fake_translate_latex_document)
    monkeypatch.setattr(document_pipeline, "extract_text_from_pdf", fake_extract_text_from_pdf)
    monkeypatch.setattr(document_pipeline, "create_translated_tex", fake_create_translated_tex)

    record = document_pipeline.create_document_record(source_path, "tex")
    result = document_pipeline.process_document(record)

    assert result.status == "done"
    assert nougat_called is False
    assert wrapper_called is False
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

    def fake_chat(**kwargs) -> str:
        return """\\begin{spacing}{1.1}
\\begin{homeworkProblem}
\\Answer 你好，世界。
\\end{homeworkProblem}
\\end{spacing}
"""

    monkeypatch.setattr(translate_service.llm_client, "chat", fake_chat)

    translated = translate_service.translate_latex_document(source_text)

    assert "\\usepackage{setspace}" in translated
    assert "\\newenvironment{homeworkProblem}" in translated
    assert translated.count("\\begin{document}") == 1
    assert translated.count("\\end{document}") == 1
    assert "你好，世界。" in translated