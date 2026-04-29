from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


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
