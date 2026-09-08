from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.local_config import read_env_file
from app.main import app
from app.services.auth_service import ensure_user_settings


def _register(client: TestClient, username: str) -> dict:
    response = client.post(
        "/api/auth/register",
        json={"username": username, "password": "test-password"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_desktop_setup_claims_and_removes_bootstrap_secrets(
    isolated_storage, tmp_path, monkeypatch
):
    config_path = tmp_path / ".config.env"
    monkeypatch.setenv("PAPERREADER_ENV_FILE", str(config_path))
    monkeypatch.setattr(settings, "desktop_mode", True)
    for name in (
        "openai_api_key", "openai_base_url", "openai_model", "pdf_parser",
        "mineru_api_key", "mineru_base_url", "mineru_model_version",
        "mineru_language", "mineru_enable_formula", "mineru_enable_table",
        "mineru_is_ocr", "vision_model",
    ):
        monkeypatch.setattr(settings, name, getattr(settings, name))

    with TestClient(app) as client:
        assert client.get("/api/setup/status").json()["required"] is True
        response = client.put(
            "/api/setup",
            json={
                "api_key": "bootstrap-llm-key",
                "base_url": "https://llm.example/v1",
                "model": "paper-model",
                "pdf_parser": "mineru",
                "mineru_api_key": "bootstrap-mineru-key",
                "mineru_base_url": "https://mineru.example/api/v4",
                "mineru_model_version": "vlm",
                "mineru_language": "en",
                "vision_model": "vision-model",
            },
        )
        assert response.status_code == 200, response.text
        user = _register(client, "setup-owner")
        assert user["settings"]["api_key_configured"] is True
        assert user["settings"]["mineru_api_key_configured"] is True
        assert "api_key" not in user["settings"]

        stored = ensure_user_settings(user["id"])
        assert stored.api_key == "bootstrap-llm-key"
        assert stored.mineru_api_key == "bootstrap-mineru-key"
        env_values = read_env_file(config_path)
        assert "OPENAI_API_KEY" not in env_values
        assert "MINERU_API_KEY" not in env_values
        assert env_values["PAPERREADER_BOOTSTRAP_PENDING"] == "false"


def test_provider_settings_are_isolated_and_masked(isolated_storage):
    with TestClient(app) as first, TestClient(app) as second:
        first_user = _register(first, "provider-first")
        second_user = _register(second, "provider-second")
        response = first.put(
            "/api/settings/me/providers",
            json={
                "api_key": "first-secret",
                "base_url": "https://first.example/v1",
                "model": "first-model",
                "pdf_parser": "mineru",
                "mineru_api_key": "first-mineru-secret",
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["api_key_configured"] is True
        assert "first-secret" not in response.text

        assert ensure_user_settings(first_user["id"]).api_key == "first-secret"
        assert ensure_user_settings(second_user["id"]).api_key == ""
        second_me = second.get("/api/auth/me").json()
        assert second_me["settings"]["api_key_configured"] is False
        assert "api_key" not in second_me["settings"]


def test_new_accounts_default_vision_check_off_and_preserve_explicit_choice(isolated_storage):
    with TestClient(app) as client:
        user = _register(client, "vision-default")
        assert user["settings"]["vision_enabled"] is False

        updated = client.put("/api/settings/me", json={"vision_enabled": True})
        assert updated.status_code == 200
        assert updated.json()["vision_enabled"] is True
        assert client.get("/api/auth/me").json()["settings"]["vision_enabled"] is True


def test_upload_requires_account_provider_configuration(isolated_storage):
    with TestClient(app) as client:
        _register(client, "missing-provider")
        response = client.post("/api/upload", files={"file": ("paper.pdf", b"%PDF-1.4")})
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "config_required"
