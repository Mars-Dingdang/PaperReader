"""Tests for the manual TeX edit/recompile API (routes_recompile.py)."""

from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.models import store
from app.services.latex_service import LatexCompileResult


def _register(client: TestClient, username: str) -> dict:
    response = client.post(
        "/api/auth/register", json={"username": username, "password": "test-password"}
    )
    assert response.status_code == 200, response.text
    return response.json()


def _make_document(user_id: int, doc_id: str = "doc1") -> store.DocumentRecord:
    folder = settings.output_dir / doc_id
    folder.mkdir(parents=True, exist_ok=True)
    source = folder / "source.pdf"
    source.write_bytes(b"%PDF-1.4 fixture")
    record = store.DocumentRecord(
        doc_id, user_id, "pdf", source, source_filename="source.pdf"
    )
    record.translated_tex_path = folder / "translated.tex"
    record.translated_tex_path.write_text("证毕□\n", encoding="utf-8")
    store.save_document(record)
    return record


def test_get_tex_returns_content_and_absolute_path(isolated_storage):
    with TestClient(app) as client:
        user = _register(client, "tex-owner")
        record = _make_document(user["id"])

        response = client.get(f"/api/document/{record.document_id}/tex")
        assert response.status_code == 200
        payload = response.json()
        assert payload["tex_content"] == "证毕□\n"
        assert Path(payload["path"]).is_absolute()
        assert Path(payload["path"]).name == "translated.tex"


def test_failed_recompile_returns_structured_issues(isolated_storage, monkeypatch):
    from app.api import routes_recompile

    def fake_compile(tex_path, output_dir, *, compiler=None):
        (output_dir / "translated.log").write_text(
            "! Argument of \\@sqrt has an extra }.\n<inserted text>\nl.740 broken\n"
            "Missing character: There is no □ (U+25A1) in font [lmroman12-regular]\n",
            encoding="utf-8",
        )
        raise RuntimeError("LaTeX compile failed. log=translated.log")

    monkeypatch.setattr(routes_recompile, "compile_tex_project_with_fallback", fake_compile)

    with TestClient(app) as client:
        user = _register(client, "tex-fail")
        record = _make_document(user["id"])

        response = client.post(
            f"/api/document/{record.document_id}/tex",
            json={"tex_content": "\\documentclass{article}"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is False
        assert "LaTeX compile failed" in payload["error"]
        assert payload["issues"] and payload["issues"][0]["line"] == 740
        assert payload["missing_chars"] and payload["missing_chars"][0]["char"] == "□"
        assert payload["missing_chars"][0]["suggest"] == "\\square"


def test_successful_recompile_restores_failed_status(isolated_storage, monkeypatch):
    from app.api import routes_recompile

    def fake_compile(tex_path: Path, output_dir: Path, *, compiler=None):
        pdf = output_dir / "translated.pdf"
        pdf.write_bytes(b"%PDF-1.4 fresh")
        return LatexCompileResult(pdf)

    monkeypatch.setattr(routes_recompile, "compile_tex_project_with_fallback", fake_compile)

    with TestClient(app) as client:
        user = _register(client, "tex-recover")
        record = _make_document(user["id"])
        record.status = "failed"
        store.save_document(record)

        response = client.post(
            f"/api/document/{record.document_id}/tex",
            json={"tex_content": "\\documentclass{article}\\begin{document}ok\\end{document}"},
        )
        assert response.status_code == 200
        assert response.json()["ok"] is True

        refreshed = store.get_document(record.document_id)
        assert refreshed.status == "done"
        assert refreshed.translated_pdf_url is not None


def test_reveal_folder_opens_file_manager_on_selected_file(isolated_storage, monkeypatch):
    import sys as _sys

    from app.api import routes_recompile

    captured: list[list[str]] = []

    def fake_popen(command, **kwargs):
        captured.append(command)

    monkeypatch.setattr(routes_recompile.subprocess, "Popen", fake_popen)

    with TestClient(app) as client:
        user = _register(client, "reveal-owner")
        record = _make_document(user["id"])

        response = client.post(
            f"/api/document/{record.document_id}/tex/reveal", json={"target": "folder"}
        )
        assert response.status_code == 200
        assert response.json()["ok"] is True
        assert captured, "a file-manager command must be spawned"
        command = captured[0]
        if _sys.platform == "win32":
            assert command[0] == "explorer"
            assert command[1].startswith("/select,")
            assert "translated.tex" in command[1]


def test_reveal_editor_reports_missing_vscode_cli(isolated_storage, monkeypatch):
    from app.api import routes_recompile

    monkeypatch.setattr(routes_recompile.shutil, "which", lambda name: None)

    with TestClient(app) as client:
        user = _register(client, "reveal-editor")
        record = _make_document(user["id"])

        response = client.post(
            f"/api/document/{record.document_id}/tex/reveal", json={"target": "editor"}
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is False
        assert "VS Code" in payload["error"]


def test_reveal_requires_authentication(isolated_storage):
    with TestClient(app) as client, TestClient(app) as anon:
        user = _register(client, "reveal-auth")
        record = _make_document(user["id"])

        response = anon.post(
            f"/api/document/{record.document_id}/tex/reveal", json={"target": "folder"}
        )
        assert response.status_code == 401
