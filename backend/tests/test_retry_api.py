from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.models import store
from app.core.database import init_database
from app.services.stage_tracker import init_stages, with_stage


def _register(client: TestClient, username: str) -> dict:
    response = client.post(
        "/api/auth/register",
        json={"username": username, "password": "test-password"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_failed_owner_can_queue_retry_once_and_status_exposes_recovery(
    isolated_storage, monkeypatch
):
    dispatched: list[tuple[str, int, str]] = []

    def fake_retry(document_id: str, user_id: int, resume_from: str) -> None:
        dispatched.append((document_id, user_id, resume_from))

    from app.api import routes_document

    monkeypatch.setattr(routes_document, "_run_retry_pipeline", fake_retry)
    with TestClient(app) as owner, TestClient(app) as other:
        user = _register(owner, "retry-owner")
        _register(other, "retry-other")
        source = settings.upload_dir / "failed.pdf"
        source.write_bytes(b"pdf")
        record = store.DocumentRecord(
            "failed-doc",
            user["id"],
            "pdf",
            source,
            status="failed",
            failure=store.FailureEntry(
                stage="translate", message="chunk 7 translation failed", chunk=7
            ),
            latex_recovery=store.LatexRecoveryEntry(
                status="failed", diagnosis="invalid section title", rounds=2
            ),
        )
        init_stages(record)
        record.current_stage = "translate"
        next(stage for stage in record.stages if stage.key == "translate").status = "failed"
        store.save_document(record)

        assert other.post("/api/document/failed-doc/retry").status_code == 404
        response = owner.post("/api/document/failed-doc/retry")
        assert response.status_code == 202, response.text
        assert response.json() == {
            "document_id": "failed-doc",
            "status": "queued",
            "resume_from": "translate",
        }
        assert dispatched == [("failed-doc", user["id"], "translate")]

        status = owner.get("/api/document/failed-doc").json()
        assert status["failure"]["chunk"] == 7
        assert status["failure"]["retry_count"] == 1
        assert status["latex_recovery"]["diagnosis"] == "invalid section title"
        assert owner.post("/api/document/failed-doc/retry").status_code == 409


def test_retry_rejects_non_failed_and_non_retryable_documents(isolated_storage):
    with TestClient(app) as client:
        user = _register(client, "retry-invalid")
        source = settings.upload_dir / "queued.pdf"
        source.write_bytes(b"pdf")
        store.save_document(store.DocumentRecord("queued-doc", user["id"], "pdf", source))
        assert client.post("/api/document/queued-doc/retry").status_code == 409

        failed = store.DocumentRecord(
            "unsafe-doc",
            user["id"],
            "pdf",
            source,
            status="failed",
            failure=store.FailureEntry(stage="parse", message="bad input", retryable=False),
        )
        store.save_document(failed)
        assert client.post("/api/document/unsafe-doc/retry").status_code == 409


def test_startup_converts_interrupted_work_into_retryable_failure(isolated_storage):
    source = settings.upload_dir / "interrupted.pdf"
    source.write_bytes(b"pdf")
    record = store.DocumentRecord(
        "interrupted-doc", 1, "pdf", source, status="recovering", current_stage="latex_repair"
    )
    store.save_document(record)
    store.DOCUMENTS.clear()

    init_database()

    recovered = store.get_document("interrupted-doc")
    assert recovered is not None
    assert recovered.status == "failed"
    assert recovered.failure is not None
    assert recovered.failure.stage == "latex_repair"
    assert recovered.failure.retryable is True


def test_stage_transitions_are_persisted_even_when_stage_raises(isolated_storage):
    source = settings.upload_dir / "stage.pdf"
    source.write_bytes(b"pdf")
    record = store.DocumentRecord("stage-doc", 1, "pdf", source)
    init_stages(record)
    store.save_document(record)

    try:
        with with_stage(record, "parse"):
            raise RuntimeError("parser unavailable")
    except RuntimeError:
        pass
    store.DOCUMENTS.clear()

    persisted = store.get_document("stage-doc")
    assert persisted is not None
    parse = next(stage for stage in persisted.stages if stage.key == "parse")
    assert parse.status == "failed"
    assert persisted.current_stage == "parse"
