from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException

from app.core.database import db_cursor


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat()


def _from_iso(value: str | None) -> datetime:
    if not value:
        return _utcnow()
    return datetime.fromisoformat(value)


@dataclass
class ArtifactEntry:
    name: str
    kind: str
    path: str
    url: str | None = None


@dataclass
class ReferenceEntry:
    index: int
    text: str


@dataclass
class StageEntry:
    key: str
    label: str
    weight: float
    status: str = "pending"
    started_at: float | None = None
    ended_at: float | None = None
    duration_ms: int | None = None


@dataclass
class ReviewProposal:
    page_index: int
    issues: list[str] = field(default_factory=list)
    original_md: str = ""
    proposed_md: str = ""
    image_url: str | None = None


@dataclass
class DocumentRecord:
    document_id: str
    owner_user_id: int
    source_type: str
    source_path: Path
    source_filename: str = ""
    status: str = "queued"
    original_pdf_url: str | None = None
    translated_pdf_url: str | None = None
    extracted_text: str = ""
    translated_text: str = ""
    artifacts: list[ArtifactEntry] = field(default_factory=list)
    references: list[ReferenceEntry] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)
    last_opened_at: datetime | None = None
    size_bytes: int = 0
    progress: int = 0
    current_stage: str | None = None
    current_stage_label: str | None = None
    stage_started_at: float | None = None
    eta_seconds: int | None = None
    stages: list[StageEntry] = field(default_factory=list)
    project_id: str | None = None
    main_tex: str | None = None
    vision_check_enabled: bool = True
    vision_check_mode: str = "auto"
    pending_reviews: list[ReviewProposal] = field(default_factory=list)
    last_compile_warning: str | None = None
    translated_tex_path: Path | None = None
    deleted_at: datetime | None = None


@dataclass
class ProjectFile:
    relative_path: str
    size: int
    kind: str


@dataclass
class ProjectRecord:
    project_id: str
    owner_user_id: int
    name: str
    dir: Path
    files: list[ProjectFile] = field(default_factory=list)
    main_tex: str | None = None
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)
    deleted_at: datetime | None = None


DOCUMENTS: dict[str, DocumentRecord] = {}
PROJECTS: dict[str, ProjectRecord] = {}


def normalized_source_filename(name: str, original_name: str = "document.pdf") -> str:
    """Return a safe display filename while preserving the source file type."""
    raw = (name or "").strip()
    if not raw or Path(raw).name != raw or "/" in raw or "\\" in raw:
        raise ValueError("invalid document name")
    original_suffix = Path(original_name).suffix.lower()
    suffix = Path(raw).suffix.lower()
    stem = Path(raw).stem if suffix else raw
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", stem).strip(" .")
    if not stem:
        raise ValueError("invalid document name")
    if original_suffix in {".pdf", ".tex"}:
        suffix = original_suffix
    elif not suffix:
        suffix = ".pdf"
    return f"{stem[:120]}{suffix}"


def translated_pdf_filename(source_filename: str) -> str:
    """Return the user-facing translated PDF filename for a source document."""
    stem = Path(source_filename or "document.pdf").stem
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", stem).strip(" .") or "document"
    return f"{stem[:120]}_Chinese_ver.pdf"


def _serialize_items(items: list) -> str:
    return json.dumps([asdict(item) for item in items], ensure_ascii=False)


def _document_from_row(row) -> DocumentRecord:
    return DocumentRecord(
        document_id=row["document_id"],
        owner_user_id=int(row["owner_user_id"]),
        source_type=row["source_type"],
        source_path=Path(row["source_path"]),
        source_filename=row["source_filename"] or "",
        status=row["status"],
        original_pdf_url=row["original_pdf_url"],
        translated_pdf_url=row["translated_pdf_url"],
        extracted_text=row["extracted_text"] or "",
        translated_text=row["translated_text"] or "",
        artifacts=[ArtifactEntry(**item) for item in json.loads(row["artifacts_json"] or "[]")],
        references=[ReferenceEntry(**item) for item in json.loads(row["references_json"] or "[]")],
        logs=json.loads(row["logs_json"] or "[]"),
        created_at=_from_iso(row["created_at"]),
        updated_at=_from_iso(row["updated_at"]),
        last_opened_at=_from_iso(row["last_opened_at"]) if row["last_opened_at"] else None,
        size_bytes=int(row["size_bytes"] or 0),
        progress=int(row["progress"] or 0),
        current_stage=row["current_stage"],
        current_stage_label=row["current_stage_label"],
        stage_started_at=row["stage_started_at"],
        eta_seconds=row["eta_seconds"],
        stages=[StageEntry(**item) for item in json.loads(row["stages_json"] or "[]")],
        project_id=row["project_id"],
        main_tex=row["main_tex"],
        vision_check_enabled=bool(row["vision_check_enabled"]),
        vision_check_mode=row["vision_check_mode"] or "auto",
        pending_reviews=[ReviewProposal(**item) for item in json.loads(row["pending_reviews_json"] or "[]")],
        last_compile_warning=row["last_compile_warning"],
        translated_tex_path=Path(row["translated_tex_path"]) if row["translated_tex_path"] else None,
        deleted_at=_from_iso(row["deleted_at"]) if row["deleted_at"] else None,
    )


def _project_from_row(row) -> ProjectRecord:
    return ProjectRecord(
        project_id=row["project_id"],
        owner_user_id=int(row["owner_user_id"]),
        name=row["name"],
        dir=Path(row["dir"]),
        files=[ProjectFile(**item) for item in json.loads(row["files_json"] or "[]")],
        main_tex=row["main_tex"],
        created_at=_from_iso(row["created_at"]),
        updated_at=_from_iso(row["updated_at"]),
        deleted_at=_from_iso(row["deleted_at"]) if row["deleted_at"] else None,
    )


def save_document(record: DocumentRecord) -> DocumentRecord:
    record.updated_at = _utcnow()
    DOCUMENTS[record.document_id] = record
    with db_cursor() as conn:
        conn.execute(
            """
            INSERT INTO documents (
                document_id, owner_user_id, source_type, source_path, source_filename, status,
                original_pdf_url, translated_pdf_url, extracted_text, translated_text,
                artifacts_json, references_json, logs_json, created_at, updated_at, last_opened_at,
                size_bytes, progress, current_stage, current_stage_label, stage_started_at,
                eta_seconds, stages_json, project_id, main_tex, vision_check_enabled,
                vision_check_mode, pending_reviews_json, last_compile_warning, translated_tex_path, deleted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(document_id) DO UPDATE SET
                owner_user_id = excluded.owner_user_id,
                source_type = excluded.source_type,
                source_path = excluded.source_path,
                source_filename = excluded.source_filename,
                status = excluded.status,
                original_pdf_url = excluded.original_pdf_url,
                translated_pdf_url = excluded.translated_pdf_url,
                extracted_text = excluded.extracted_text,
                translated_text = excluded.translated_text,
                artifacts_json = excluded.artifacts_json,
                references_json = excluded.references_json,
                logs_json = excluded.logs_json,
                updated_at = excluded.updated_at,
                last_opened_at = excluded.last_opened_at,
                size_bytes = excluded.size_bytes,
                progress = excluded.progress,
                current_stage = excluded.current_stage,
                current_stage_label = excluded.current_stage_label,
                stage_started_at = excluded.stage_started_at,
                eta_seconds = excluded.eta_seconds,
                stages_json = excluded.stages_json,
                project_id = excluded.project_id,
                main_tex = excluded.main_tex,
                vision_check_enabled = excluded.vision_check_enabled,
                vision_check_mode = excluded.vision_check_mode,
                pending_reviews_json = excluded.pending_reviews_json,
                last_compile_warning = excluded.last_compile_warning,
                translated_tex_path = excluded.translated_tex_path,
                deleted_at = excluded.deleted_at
            """,
            (
                record.document_id,
                record.owner_user_id,
                record.source_type,
                str(record.source_path),
                record.source_filename,
                record.status,
                record.original_pdf_url,
                record.translated_pdf_url,
                record.extracted_text,
                record.translated_text,
                _serialize_items(record.artifacts),
                _serialize_items(record.references),
                json.dumps(record.logs, ensure_ascii=False),
                _to_iso(record.created_at),
                _to_iso(record.updated_at),
                _to_iso(record.last_opened_at),
                record.size_bytes,
                record.progress,
                record.current_stage,
                record.current_stage_label,
                record.stage_started_at,
                record.eta_seconds,
                _serialize_items(record.stages),
                record.project_id,
                record.main_tex,
                1 if record.vision_check_enabled else 0,
                record.vision_check_mode,
                _serialize_items(record.pending_reviews),
                record.last_compile_warning,
                str(record.translated_tex_path) if record.translated_tex_path else None,
                _to_iso(record.deleted_at),
            ),
        )
    return record


def save_project(project: ProjectRecord) -> ProjectRecord:
    project.updated_at = _utcnow()
    PROJECTS[project.project_id] = project
    with db_cursor() as conn:
        conn.execute(
            """
            INSERT INTO projects (
                project_id, owner_user_id, name, dir, files_json, main_tex, created_at, updated_at, deleted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_id) DO UPDATE SET
                owner_user_id = excluded.owner_user_id,
                name = excluded.name,
                dir = excluded.dir,
                files_json = excluded.files_json,
                main_tex = excluded.main_tex,
                updated_at = excluded.updated_at,
                deleted_at = excluded.deleted_at
            """,
            (
                project.project_id,
                project.owner_user_id,
                project.name,
                str(project.dir),
                _serialize_items(project.files),
                project.main_tex,
                _to_iso(project.created_at),
                _to_iso(project.updated_at),
                _to_iso(project.deleted_at),
            ),
        )
    return project


def get_document(document_id: str) -> DocumentRecord | None:
    cached = DOCUMENTS.get(document_id)
    if cached and not cached.deleted_at:
        return cached
    with db_cursor() as conn:
        row = conn.execute(
            "SELECT * FROM documents WHERE document_id = ? AND deleted_at IS NULL",
            (document_id,),
        ).fetchone()
    if not row:
        return None
    record = _document_from_row(row)
    DOCUMENTS[document_id] = record
    return record


def get_project(project_id: str) -> ProjectRecord | None:
    cached = PROJECTS.get(project_id)
    if cached and not cached.deleted_at:
        return cached
    with db_cursor() as conn:
        row = conn.execute(
            "SELECT * FROM projects WHERE project_id = ? AND deleted_at IS NULL",
            (project_id,),
        ).fetchone()
    if not row:
        return None
    project = _project_from_row(row)
    PROJECTS[project_id] = project
    return project


def list_documents_for_user(owner_user_id: int) -> list[DocumentRecord]:
    results: dict[str, DocumentRecord] = {
        doc_id: doc
        for doc_id, doc in DOCUMENTS.items()
        if doc.owner_user_id == owner_user_id and not doc.deleted_at
    }
    with db_cursor() as conn:
        rows = conn.execute(
            """
            SELECT * FROM documents
            WHERE owner_user_id = ? AND deleted_at IS NULL
            ORDER BY COALESCE(last_opened_at, updated_at, created_at) DESC
            """,
            (owner_user_id,),
        ).fetchall()
    for row in rows:
        if row["document_id"] not in results:
            results[row["document_id"]] = _document_from_row(row)
    return sorted(
        results.values(),
        key=lambda item: (
            item.last_opened_at or item.updated_at or item.created_at,
            item.created_at,
        ),
        reverse=True,
    )


def touch_document_opened(record: DocumentRecord) -> DocumentRecord:
    record.last_opened_at = _utcnow()
    return save_document(record)


def require_document_owner(document_id: str, owner_user_id: int) -> DocumentRecord:
    record = get_document(document_id)
    if not record or record.owner_user_id != owner_user_id:
        raise HTTPException(status_code=404, detail="Document not found")
    return record


def require_project_owner(project_id: str, owner_user_id: int) -> ProjectRecord:
    project = get_project(project_id)
    if not project or project.owner_user_id != owner_user_id:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def soft_delete_document(document_id: str, owner_user_id: int) -> None:
    record = require_document_owner(document_id, owner_user_id)
    record.deleted_at = _utcnow()
    save_document(record)
    DOCUMENTS.pop(document_id, None)


def delete_project(project_id: str, owner_user_id: int) -> ProjectRecord:
    project = require_project_owner(project_id, owner_user_id)
    project.deleted_at = _utcnow()
    save_project(project)
    PROJECTS.pop(project_id, None)
    return project
