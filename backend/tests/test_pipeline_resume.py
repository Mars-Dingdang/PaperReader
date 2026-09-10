import json

import pytest

from app.core.config import settings
from app.models import store
from app.services import document_pipeline
from app.services.latex_service import LatexCompileResult
from app.services.mineru_layout import apply_translations, collect_translatable_strings
from app.services.mineru_service import MinerUResult


def _structured_result(tmp_path):
    return MinerUResult(
        markdown="# Paper\n\nFirst paragraph.\n\nSecond paragraph.",
        mode_label="fixture",
        extracted_files=[],
        content_blocks=[[{
            "type": "title",
            "content": {"title_content": [{"type": "text", "content": "Paper"}], "level": 1},
        }, {
            "type": "paragraph",
            "content": {"paragraph_content": [{"type": "text", "content": "First paragraph."}]},
        }, {
            "type": "paragraph",
            "content": {"paragraph_content": [{"type": "text", "content": "Second paragraph."}]},
        }]],
        images_dir=None,
        two_column=False,
    )


def test_translation_retry_reuses_parse_checkpoint_and_finishes(isolated_storage, monkeypatch):
    source = settings.upload_dir / "resume.pdf"
    source.write_bytes(b"pdf")
    record = document_pipeline.create_document_record(source, "pdf", owner_user_id=1)
    parse_calls: list[int] = []

    def extract_once(*args, **kwargs):
        parse_calls.append(1)
        return _structured_result(isolated_storage)

    monkeypatch.setattr(document_pipeline, "extract_structured_from_pdf_local", extract_once)
    monkeypatch.setattr(document_pipeline, "extract_text_from_pdf_text_layer", lambda *a, **k: "")
    monkeypatch.setattr(
        document_pipeline,
        "translate_ir",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("Translation incomplete: chunk 2 failed")),
    )
    first = document_pipeline.process_document(record)
    assert first.status == "failed"
    assert first.failure is not None
    assert first.failure.stage == "translate"
    assert first.failure.chunk == 2

    def extractor_must_not_run(*args, **kwargs):
        raise AssertionError("retry must load the completed parse checkpoint")

    def translate_ok(ir, **kwargs):
        assert kwargs["checkpoint_path"].parent.is_dir()
        apply_translations(ir, [f"译-{index}" for index, _ in enumerate(collect_translatable_strings(ir))])

    def compile_ok(path, output_dir, compiler=None):
        pdf = output_dir / "translated.pdf"
        pdf.write_bytes(b"pdf")
        return LatexCompileResult(pdf)

    monkeypatch.setattr(document_pipeline, "extract_structured_from_pdf_local", extractor_must_not_run)
    monkeypatch.setattr(document_pipeline, "translate_ir", translate_ok)
    monkeypatch.setattr(document_pipeline, "compile_tex_project_with_fallback", compile_ok)

    second = document_pipeline.process_document(first, resume_from="translate")
    assert second.status == "done"
    assert second.failure is None
    assert len(parse_calls) == 1
    assert second.translated_tex_path is not None
    assert second.translated_tex_path.is_file()


def test_clean_retry_reuses_extraction_checkpoint(isolated_storage, monkeypatch):
    source = settings.upload_dir / "clean-resume.pdf"
    source.write_bytes(b"pdf")
    record = document_pipeline.create_document_record(source, "pdf", owner_user_id=1)
    parse_calls: list[int] = []

    def extract_once(*args, **kwargs):
        parse_calls.append(1)
        return _structured_result(isolated_storage)

    real_clean = document_pipeline._clean_nougat_text_with_metadata
    monkeypatch.setattr(document_pipeline, "extract_structured_from_pdf_local", extract_once)
    monkeypatch.setattr(document_pipeline, "extract_text_from_pdf_text_layer", lambda *a, **k: "")
    monkeypatch.setattr(
        document_pipeline,
        "_clean_nougat_text_with_metadata",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("clean stage failed")),
    )

    first = document_pipeline.process_document(record)
    assert first.status == "failed"
    assert first.failure is not None
    assert first.failure.stage == "clean"

    monkeypatch.setattr(
        document_pipeline,
        "extract_structured_from_pdf_local",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not parse again")),
    )
    monkeypatch.setattr(document_pipeline, "_clean_nougat_text_with_metadata", real_clean)

    def translate_ok(ir, **kwargs):
        apply_translations(ir, [f"译-{index}" for index, _ in enumerate(collect_translatable_strings(ir))])

    def compile_ok(path, output_dir, compiler=None):
        pdf = output_dir / "translated.pdf"
        pdf.write_bytes(b"pdf")
        return LatexCompileResult(pdf)

    monkeypatch.setattr(document_pipeline, "translate_ir", translate_ok)
    monkeypatch.setattr(document_pipeline, "compile_tex_project_with_fallback", compile_ok)

    second = document_pipeline.process_document(first, resume_from="clean")

    assert second.status == "done", second.logs
    assert second.failure is None
    assert parse_calls == [1]


def test_latex_retry_reuses_registered_translated_tex(isolated_storage, monkeypatch):
    source = settings.upload_dir / "latex.pdf"
    source.write_bytes(b"pdf")
    record = store.DocumentRecord(
        "latex-resume",
        1,
        "pdf",
        source,
        status="failed",
        current_stage="latex_build",
        failure=store.FailureEntry(stage="latex_build", message="compile failed"),
    )
    output = settings.output_dir / record.document_id
    output.mkdir()
    translated_tex = output / "translated.tex"
    translated_tex.write_text(
        "\\documentclass{article}\n\\begin{document}\nOK\n\\end{document}\n",
        encoding="utf-8",
    )
    record.translated_tex_path = translated_tex
    store.save_document(record)

    monkeypatch.setattr(
        document_pipeline,
        "extract_structured_from_pdf_local",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not parse")),
    )

    def compile_ok(path, output_dir, compiler=None):
        assert path == translated_tex
        pdf = output_dir / "translated.pdf"
        pdf.write_bytes(b"pdf")
        return LatexCompileResult(pdf)

    monkeypatch.setattr(document_pipeline, "compile_tex_project_with_fallback", compile_ok)
    result = document_pipeline.process_document(record, resume_from="latex_build")
    assert result.status == "done"


def test_tex_project_latex_retry_reuses_registered_translated_tex(
    isolated_storage, monkeypatch
):
    source = settings.upload_dir / "paper.tex"
    source.write_text(
        "\\documentclass{article}\n\\begin{document}\nSource\n\\end{document}\n",
        encoding="utf-8",
    )
    record = store.DocumentRecord(
        "tex-resume",
        1,
        "tex",
        source,
        status="failed",
        current_stage="compile_translated",
        failure=store.FailureEntry(stage="compile_translated", message="compile failed"),
    )
    output = settings.output_dir / record.document_id
    output.mkdir()
    translated_tex = output / "translated.tex"
    translated_tex.write_text(
        "\\documentclass{article}\n\\begin{document}\n译文\n\\end{document}\n",
        encoding="utf-8",
    )
    record.translated_tex_path = translated_tex
    store.save_document(record)

    monkeypatch.setattr(
        document_pipeline,
        "compile_tex_project",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not compile original")),
    )
    monkeypatch.setattr(
        document_pipeline,
        "translate_latex_document",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not translate again")),
    )

    def compile_ok(path, output_dir, compiler=None):
        assert path == source.parent / "__translated.tex"
        assert "译文" in path.read_text(encoding="utf-8")
        pdf = output_dir / "__translated.pdf"
        pdf.write_bytes(b"pdf")
        return LatexCompileResult(pdf)

    monkeypatch.setattr(document_pipeline, "compile_tex_project_with_fallback", compile_ok)

    result = document_pipeline.process_document(record, resume_from="compile_translated")

    assert result.status == "done"
    assert result.failure is None


@pytest.mark.parametrize("payload", [None, [], "text", 1])
def test_extraction_checkpoint_ignores_non_object_json(
    isolated_storage, tmp_path, payload
):
    source = tmp_path / "source.pdf"
    source.write_bytes(b"pdf")
    checkpoint = tmp_path / "extraction-checkpoint.json"
    checkpoint.write_text(json.dumps(payload), encoding="utf-8")

    assert document_pipeline._load_extraction_checkpoint(checkpoint, source) is None
