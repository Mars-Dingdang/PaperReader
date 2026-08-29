import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from app.core.config import settings


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
    status: str = "pending"  # pending | running | done | failed | skipped
    started_at: float | None = None  # epoch seconds
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
    created_at: datetime = field(default_factory=datetime.utcnow)
    size_bytes: int = 0
    # Progress / stage tracking
    progress: int = 0
    current_stage: str | None = None
    current_stage_label: str | None = None
    stage_started_at: float | None = None
    eta_seconds: int | None = None
    stages: list[StageEntry] = field(default_factory=list)
    # Optional metadata for project-based uploads (Phase B)
    project_id: str | None = None
    main_tex: str | None = None
    # Vision-check review (Phase D)
    vision_check_enabled: bool = True
    vision_check_mode: str = "auto"  # auto | manual
    pending_reviews: list[ReviewProposal] = field(default_factory=list)
    # Last lenient-fallback compile warning (set when strict pass failed but
    # `latexmk -f` still produced a PDF). Surfaced to the UI so the user knows
    # the document may have rendering issues that warrant manual review.
    last_compile_warning: str | None = None
    # Path on disk to the translated.tex source (used by the recompile route).
    translated_tex_path: Path | None = None


@dataclass
class ProjectFile:
    relative_path: str
    size: int
    kind: str


@dataclass
class ProjectRecord:
    project_id: str
    name: str
    dir: Path
    files: list[ProjectFile] = field(default_factory=list)
    main_tex: str | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)


DOCUMENTS: dict[str, DocumentRecord] = {}
PROJECTS: dict[str, ProjectRecord] = {}

_META_FILENAME = "meta.json"


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
    stem = Path(source_filename or "document.pdf").stem
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", stem).strip(" .") or "document"
    return f"{stem[:120]}_Chinese_ver.pdf"


def persist_record(record: DocumentRecord) -> None:
    """Write a document's metadata next to its outputs so the document list can
    be rebuilt after a backend restart (the in-memory DOCUMENTS dict is
    volatile). Best-effort: a persistence failure must never break the pipeline.
    """
    try:
        out_dir = settings.output_dir / record.document_id
        out_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "document_id": record.document_id,
            "source_type": record.source_type,
            "source_path": str(record.source_path),
            "source_filename": record.source_filename,
            "status": record.status,
            "created_at": record.created_at.isoformat() if record.created_at else None,
            "size_bytes": record.size_bytes,
            "original_pdf_url": record.original_pdf_url,
            "translated_pdf_url": record.translated_pdf_url,
            "translated_text": record.translated_text,
            "extracted_text": record.extracted_text,
            "logs": list(record.logs),
            "references": [{"index": r.index, "text": r.text} for r in record.references],
            "artifacts": [
                {"name": a.name, "kind": a.kind, "path": a.path, "url": a.url}
                for a in record.artifacts
            ],
            "last_compile_warning": record.last_compile_warning,
        }
        (out_dir / _META_FILENAME).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        pass


def load_records() -> int:
    """Rebuild DOCUMENTS from persisted meta.json files on disk. Returns the
    number of records loaded. Called once at startup.
    """
    if not settings.output_dir.is_dir():
        return 0
    loaded = 0
    for meta_path in settings.output_dir.glob(f"*/{_META_FILENAME}"):
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        document_id = data.get("document_id") or meta_path.parent.name
        if document_id in DOCUMENTS:
            continue
        source_path_raw = data.get("source_path")
        source_path = Path(source_path_raw) if source_path_raw else (meta_path.parent / "original.pdf")
        record = DocumentRecord(
            document_id=document_id,
            source_type=data.get("source_type") or "pdf",
            source_path=source_path,
            source_filename=data.get("source_filename") or "",
            status=data.get("status") or "done",
        )
        record.size_bytes = int(data.get("size_bytes") or 0)
        record.original_pdf_url = data.get("original_pdf_url")
        record.translated_pdf_url = data.get("translated_pdf_url")
        record.translated_text = data.get("translated_text") or ""
        record.extracted_text = data.get("extracted_text") or ""
        record.logs = [str(item) for item in (data.get("logs") or [])]
        record.last_compile_warning = data.get("last_compile_warning")
        try:
            if data.get("created_at"):
                record.created_at = datetime.fromisoformat(data["created_at"])
        except Exception:
            pass
        record.references = [
            ReferenceEntry(index=int(r.get("index") or 0), text=r.get("text") or "")
            for r in (data.get("references") or [])
        ]
        record.artifacts = [
            ArtifactEntry(
                name=a.get("name") or "",
                kind=a.get("kind") or "",
                path=a.get("path") or "",
                url=a.get("url"),
            )
            for a in (data.get("artifacts") or [])
        ]
        # Migrate legacy ``translated.pdf`` outputs to the source-derived
        # filename requested by the UI, without requiring a retranslation.
        translated_name = translated_pdf_filename(record.source_filename)
        translated_target = meta_path.parent / translated_name
        translated_items = [a for a in record.artifacts if a.kind == "translated_pdf"]
        translated_current: Path | None = None
        for item in translated_items:
            candidate = Path(item.path)
            if candidate.is_file():
                translated_current = candidate
                break
        legacy = meta_path.parent / "translated.pdf"
        if translated_current is None and legacy.is_file():
            translated_current = legacy
        if translated_current and translated_current.resolve() != translated_target.resolve():
            if not translated_target.exists():
                translated_current.replace(translated_target)
            translated_current = translated_target
        if translated_current and translated_current.exists():
            translated_url = f"/data/outputs/{document_id}/{translated_name}"
            record.translated_pdf_url = translated_url
            for item in translated_items:
                item.name = translated_name
                item.path = str(translated_current)
                item.url = translated_url
        tex_path = meta_path.parent / "translated.tex"
        if tex_path.exists():
            record.translated_tex_path = tex_path
        DOCUMENTS[document_id] = record
        persist_record(record)
        loaded += 1
    return loaded
