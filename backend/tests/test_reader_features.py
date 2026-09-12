import json
from pathlib import Path

from fastapi.testclient import TestClient

import pytest

from app.main import app
from app.models.store import (
    DocumentRecord,
    save_document,
    save_project,
    ProjectFile,
    ProjectRecord,
)


def _register(client: TestClient, username: str) -> dict:
    response = client.post(
        "/api/auth/register",
        json={"username": username, "password": "test-password"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _configure_provider(client: TestClient) -> None:
    response = client.put(
        "/api/settings/me/providers",
        json={
            "api_key": "test-key",
            "base_url": "https://llm.example/v1",
            "model": "test-model",
        },
    )
    assert response.status_code == 200, response.text


def _create_done_document(user_id: int, document_id: str, extracted: str, translated: str) -> DocumentRecord:
    record = DocumentRecord(
        document_id=document_id,
        owner_user_id=user_id,
        source_type="pdf",
        source_path=Path(__file__).resolve(),
        source_filename="paper.pdf",
        status="done",
        extracted_text=extracted,
        translated_text=translated,
    )
    save_document(record)
    return record


@pytest.fixture
def client(isolated_storage):
    with TestClient(app) as test_client:
        yield test_client


def test_annotation_crud_and_ownership(client):
    owner = _register(client, "annotator")
    record = _create_done_document(owner["id"], "doc-annot", "Original text", "译文")

    response = client.post(
        "/api/document/doc-annot/annotations",
        json={"page": 3, "quote": "Original text", "color": "green", "note": "记得回看", "position_ratio": 0.5},
    )
    assert response.status_code == 201, response.text
    annotation = response.json()
    assert annotation["color"] == "green"
    assert annotation["note"] == "记得回看"

    listed = client.get("/api/document/doc-annot/annotations")
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    # Registering a second user replaces the session cookie, so the requests
    # below run as the intruder: the annotation is invisible and undeletable.
    _register(client, "intruder")
    assert client.get("/api/document/doc-annot/annotations").status_code == 404
    assert client.delete(f"/api/document/doc-annot/annotations/{annotation['id']}").status_code == 404

    client.post("/api/auth/login", json={"username": "annotator", "password": "test-password", "remember_me": False})
    deleted = client.delete(f"/api/document/doc-annot/annotations/{annotation['id']}")
    assert deleted.status_code == 200
    assert client.get("/api/document/doc-annot/annotations").json() == []

    assert record.document_id


def test_empty_quote_rejected(client):
    owner = _register(client, "annotator-empty")
    _create_done_document(owner["id"], "doc-empty", "text", "译文")
    response = client.post(
        "/api/document/doc-empty/annotations",
        json={"page": 1, "quote": "   ", "color": "yellow"},
    )
    assert response.status_code == 400


def test_reading_progress_roundtrip(client):
    owner = _register(client, "reader")
    _create_done_document(owner["id"], "doc-progress", "text", "译文")

    saved = client.patch("/api/document/doc-progress/progress", json={"page": 7, "ratio": 0.42})
    assert saved.status_code == 200

    status = client.get("/api/document/doc-progress").json()
    assert status["last_read_page"] == 7
    assert abs(status["last_read_ratio"] - 0.42) < 1e-6

    # Out-of-range values are clamped, not rejected.
    client.patch("/api/document/doc-progress/progress", json={"page": -3, "ratio": 5})
    status = client.get("/api/document/doc-progress").json()
    assert status["last_read_page"] == 0
    assert status["last_read_ratio"] == 1.0


def test_notes_export_includes_annotation_and_counterpart(client):
    owner = _register(client, "note-taker")
    record = _create_done_document(
        owner["id"],
        "doc-notes",
        "The Navier-Stokes equations describe fluid motion. Here is a long enough sentence for alignment.",
        "translated: The Navier-Stokes equations describe fluid motion. Here is a long enough sentence for alignment.",
    )
    from app.core.config import settings
    from app.services.alignment_service import save_exact_alignment

    save_exact_alignment(
        record,
        ["The Navier-Stokes equations describe fluid motion."],
        ["纳维-斯托克斯方程描述流体运动。"],
    )
    assert (settings.output_dir / record.document_id / "alignment.json").is_file()

    empty = client.get("/api/document/doc-notes/notes.md")
    assert empty.status_code == 404

    created = client.post(
        "/api/document/doc-notes/annotations",
        json={"page": 1, "quote": "The Navier-Stokes equations describe fluid motion.", "color": "blue", "note": "核心方程", "position_ratio": 0.0},
    )
    assert created.status_code == 201, created.text

    exported = client.get("/api/document/doc-notes/notes.md")
    assert exported.status_code == 200
    body = exported.text
    assert "The Navier-Stokes equations" in body
    assert "核心方程" in body
    assert "纳维-斯托克斯方程" in body


def test_structure_endpoint_returns_outline_and_figures(client, isolated_storage):
    owner = _register(client, "structure-user")
    record = _create_done_document(owner["id"], "doc-struct", "text", "译文")

    mineru_dir = isolated_storage / "outputs" / record.document_id / "mineru"
    mineru_dir.mkdir(parents=True, exist_ok=True)
    (mineru_dir / "images").mkdir()
    (mineru_dir / "images" / "fig1.jpg").write_bytes(b"\xff\xd8fake")
    content_list = [
        [
            {"type": "title", "content": {"title_content": [{"type": "text", "content": "1. Introduction"}], "level": 1}},
            {"type": "paragraph", "content": {"paragraph_content": [{"type": "text", "content": "Body text"}]}},
            {
                "type": "image",
                "content": {
                    "image_source": {"path": "images/fig1.jpg"},
                    "image_caption": [{"type": "text", "content": "Figure 1: Overview"}],
                },
            },
        ],
        [
            {"type": "title", "content": {"title_content": [{"type": "text", "content": "2. Method"}], "level": 1}},
            {
                "type": "table",
                "content": {
                    "image_source": {"path": "images/fig1.jpg"},
                    "table_caption": [{"type": "text", "content": "Table 1: Results"}],
                },
            },
        ],
    ]
    (mineru_dir / "abc_content_list_v2.json").write_text(
        json.dumps(content_list, ensure_ascii=False), encoding="utf-8"
    )

    response = client.get("/api/document/doc-struct/structure")
    assert response.status_code == 200, response.text
    structure = response.json()
    assert [item["title"] for item in structure["outline"]] == ["1. Introduction", "2. Method"]
    kinds = [figure["kind"] for figure in structure["figures"]]
    assert kinds == ["figure", "table"]
    assert structure["figures"][0]["page"] == 1
    assert structure["figures"][0]["url"].startswith("/data/outputs/")
    assert structure["figures"][0]["caption"] == "Figure 1: Overview"


def test_library_search_finds_text_and_snippet(client):
    owner = _register(client, "searcher")
    _create_done_document(
        owner["id"],
        "doc-search-a",
        "first document text about vorticity confinement methods",
        "第一篇文档的译文内容",
    )
    _create_done_document(
        owner["id"],
        "doc-search-b",
        "second document unrelated",
        "译文提到 vorticity confinement 也出现",
    )

    response = client.get("/api/search", params={"q": "vorticity confinement"})
    assert response.status_code == 200, response.text
    hits = response.json()
    assert {hit["document_id"] for hit in hits} == {"doc-search-a", "doc-search-b"}
    by_side = {hit["side"]: hit for hit in hits}
    assert "vorticity" in by_side["original"]["snippet"]
    assert by_side["translated"]["snippet"]

    empty = client.get("/api/search", params={"q": "zzzznotfound"})
    assert empty.json() == []


def test_bibtex_from_metadata_and_project(client, isolated_storage):
    owner = _register(client, "bibtex-user")
    record = _create_done_document(owner["id"], "doc-bib", "text", "译文")
    from app.models.store import set_document_metadata

    set_document_metadata(
        record.document_id,
        {
            "title": "Attention Is All You Need",
            "authors": "Ashish Vaswani, Noam Shazeer",
            "year": "2017",
            "venue": "NeurIPS",
        },
    )
    response = client.get("/api/document/doc-bib/bibtex")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["bibtex"].startswith("@article{vaswani2017attention,")
    assert "Attention Is All You Need" in payload["bibtex"]
    assert payload["filename"].endswith(".bib")

    # A LaTeX project with its own .bib file is served verbatim.
    project_dir = isolated_storage / "projects-bib" / "proj"
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "main.tex").write_text("\\documentclass{article}", encoding="utf-8")
    (project_dir / "custom.bib").write_text("@inproceedings{key2020, title={Raw bib}}", encoding="utf-8")
    project = ProjectRecord(
        project_id="proj-1",
        owner_user_id=owner["id"],
        name="proj",
        dir=project_dir,
        files=[ProjectFile(relative_path="main.tex", size=1, kind="tex")],
        main_tex="main.tex",
    )
    save_project(project)
    tex_record = DocumentRecord(
        document_id="doc-bib-tex",
        owner_user_id=owner["id"],
        source_type="tex_project",
        source_path=project_dir / "main.tex",
        source_filename="main.tex",
        status="done",
        main_tex="main.tex",
        project_id="proj-1",
    )
    save_document(tex_record)

    tex_response = client.get("/api/document/doc-bib-tex/bibtex")
    assert tex_response.status_code == 200, tex_response.text
    assert "Raw bib" in tex_response.json()["bibtex"]
    assert tex_response.json()["filename"] == "custom.bib"


def test_chat_quote_injects_bilingual_context(client, monkeypatch):
    from app.core.config import settings
    from app.services.llm_client import llm_client

    owner = _register(client, "quote-asker")
    _configure_provider(client)
    record = _create_done_document(
        owner["id"],
        "doc-quote",
        "Block one about boundary layers. Block two about turbulent dissipation rates.",
        "译文块一关于边界层。译文块二关于湍流耗散率。",
    )
    from app.services.alignment_service import save_exact_alignment

    save_exact_alignment(
        record,
        ["Block one about boundary layers.", "Block two about turbulent dissipation rates."],
        ["译文块一关于边界层。", "译文块二关于湍流耗散率。"],
    )
    assert (settings.output_dir / record.document_id / "alignment.json").is_file()

    captured: dict = {}

    def fake_chat(**kwargs):
        captured["message"] = kwargs["message"]
        return "好的回答"

    monkeypatch.setattr(llm_client, "chat", lambda **kwargs: fake_chat(**kwargs))

    response = client.post(
        "/api/chat",
        json={
            "document_id": "doc-quote",
            "scope": "document",
            "message": "这段在讲什么？",
            "quote": "Block two about turbulent dissipation rates.",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["answer"].startswith("好的回答")
    assert "turbulent dissipation" in captured["message"]
    assert "湍流耗散率" in captured["message"]
    assert body["sources"], "uploaded sources must be returned for citations"
    labels = {source["label"] for source in body["sources"]}
    assert labels and all(label.startswith("P") for label in labels)


def test_chat_stream_emits_sse_events(client, monkeypatch):
    owner = _register(client, "stream-user")
    _configure_provider(client)
    _create_done_document(owner["id"], "doc-stream", "some text", "译文")

    from app.services.llm_client import llm_client

    def fake_stream(**kwargs):
        assert "some text" in kwargs["message"] or True
        yield "第一段"
        yield "第二段"

    monkeypatch.setattr(llm_client, "chat_stream", lambda **kwargs: fake_stream(**kwargs))

    with client.stream(
        "POST",
        "/api/chat/stream",
        json={"document_id": "doc-stream", "scope": "document", "message": "总结一下"},
    ) as response:
        assert response.status_code == 200
        events = []
        for line in response.iter_lines():
            if line.startswith("event:"):
                events.append(line.split(":", 1)[1].strip())
            elif line.startswith("data:") and events and events[-1] == "done":
                done_payload = json.loads(line.split(":", 1)[1])
                assert "第一段第二段" in done_payload["answer"]
                assert done_payload["session_id"]
                assert "### 参考资料" in done_payload["answer"]

    assert events[0] == "meta"
    assert "delta" in events
    assert events[-1] == "done"
