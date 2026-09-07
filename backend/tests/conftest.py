"""Always run the suite against disposable storage, never a developer's data."""

import os
import tempfile

_test_data = tempfile.TemporaryDirectory(prefix="paperreader-tests-")
os.environ["DATA_DIR"] = _test_data.name
os.environ["PAPERREADER_ENV_FILE"] = os.path.join(_test_data.name, "missing.env")

import pytest


@pytest.fixture
def isolated_storage(tmp_path, monkeypatch):
    from app.core.config import settings
    from app.core.database import init_database
    from app.models import store
    from app.services import chat_store

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(chat_store, "_STORE_PATH", tmp_path / "chat_sessions.json")
    monkeypatch.setattr(store, "DOCUMENTS", {})
    monkeypatch.setattr(store, "PROJECTS", {})
    settings.upload_dir.mkdir()
    settings.output_dir.mkdir()
    init_database()
    return tmp_path
