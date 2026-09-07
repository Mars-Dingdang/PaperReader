import io
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.core.config import settings
from app.services import mineru_service


def _make_zip_bytes(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


def _json_resp(status: int, payload: dict) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = payload
    resp.text = str(payload)
    return resp


def _bytes_resp(status: int, data: bytes) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.iter_content.return_value = [data]
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def test_extract_text_from_pdf_happy_path(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "mineru_api_key", "test-token")
    monkeypatch.setattr(settings, "mineru_poll_interval", 0)

    pdf = tmp_path / "demo.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")

    zip_bytes = _make_zip_bytes({"full.md": "# hello\n\nworld", "images/a.png": "fake"})

    post_resp = _json_resp(200, {"code": 0, "data": {"batch_id": "B1", "file_urls": ["https://oss/up"]}})
    put_resp = MagicMock(status_code=200, text="ok")

    poll_running = _json_resp(200, {"code": 0, "data": {"extract_result": [{"state": "running"}]}})
    poll_done = _json_resp(200, {"code": 0, "data": {"extract_result": [{"state": "done", "full_zip_url": "https://cdn/x.zip"}]}})

    download_resp = _bytes_resp(200, zip_bytes)

    with patch.object(mineru_service.requests, "post", return_value=post_resp), \
         patch.object(mineru_service.requests, "put", return_value=put_resp), \
         patch.object(mineru_service.requests, "get", side_effect=[poll_running, poll_done, download_resp]):
        out_dir = tmp_path / "out"
        text, mode, files = mineru_service.extract_text_from_pdf(str(pdf), out_dir, log_sink=[])

    assert "hello" in text and "world" in text
    assert mode.startswith("mineru:")
    names = {p.name for p in files}
    assert "mineru_result.zip" in names and "full.md" in names


def test_extract_text_from_pdf_failed_state(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "mineru_api_key", "test-token")
    monkeypatch.setattr(settings, "mineru_poll_interval", 0)

    pdf = tmp_path / "demo.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")

    post_resp = _json_resp(200, {"code": 0, "data": {"batch_id": "B1", "file_urls": ["https://oss/up"]}})
    put_resp = MagicMock(status_code=200, text="ok")
    poll_failed = _json_resp(200, {"code": 0, "data": {"extract_result": [{"state": "failed", "err_msg": "bad pdf"}]}})

    with patch.object(mineru_service.requests, "post", return_value=post_resp), \
         patch.object(mineru_service.requests, "put", return_value=put_resp), \
         patch.object(mineru_service.requests, "get", return_value=poll_failed):
        with pytest.raises(RuntimeError, match="bad pdf"):
            mineru_service.extract_text_from_pdf(str(pdf), tmp_path / "out")


def test_missing_api_key_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "mineru_api_key", "")
    pdf = tmp_path / "demo.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    with pytest.raises(RuntimeError, match="MINERU_API_KEY"):
        mineru_service.extract_text_from_pdf(str(pdf), tmp_path / "out")


def test_result_zip_download_retries_after_ssl_disconnect(tmp_path, monkeypatch):
    zip_bytes = _make_zip_bytes({"full.md": "# complete\n\ncontent"})
    success = _bytes_resp(200, zip_bytes)
    calls = 0

    def flaky_get(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise mineru_service.requests.exceptions.SSLError("unexpected EOF")
        return success

    monkeypatch.setattr(mineru_service.requests, "get", flaky_get)
    monkeypatch.setattr(mineru_service.time, "sleep", lambda _seconds: None)
    logs: list[str] = []

    text, files = mineru_service._download_and_extract_zip(
        "https://cdn.example/result.zip", tmp_path / "out", log_sink=logs
    )

    assert calls == 2
    assert "complete" in text
    assert any(path.name == "full.md" for path in files)
    assert any("retry 2/4" in line for line in logs)
