from fastapi.testclient import TestClient

import pytest

from app.core.config import settings
from app.main import app
from app.services.llm_client import llm_client


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


def test_upload_streams_file_to_disk(isolated_storage, monkeypatch):
    from app.api import routes_upload

    launched: list[str] = []
    monkeypatch.setattr(
        routes_upload, "_run_pipeline", lambda record_id, user_id: launched.append(record_id)
    )

    with TestClient(app) as client:
        user = _register(client, "stream-uploader")
        _configure_provider(client)

        payload = b"%PDF-1.7\n" + b"x" * (256 * 1024)
        response = client.post(
            "/api/upload",
            files={"file": ("paper.pdf", payload, "application/pdf")},
            data={"vision_check_enabled": "false", "vision_check_mode": "auto"},
        )

        assert response.status_code == 200, response.text
        document_id = response.json()["document_id"]
        assert launched == [document_id]

        payload_size = len(payload)
        matches = [
            path for path in settings.upload_dir.iterdir()
            if path.name.endswith("paper.pdf") and path.stat().st_size == payload_size
        ]
        assert matches, "uploaded file must land on disk"
        assert matches[0].read_bytes() == payload


def test_chat_without_api_key_raises(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "")

    with pytest.raises(RuntimeError, match="No API key configured"):
        llm_client.chat(message="hello", system_prompt="be brief", override_api_key="")
