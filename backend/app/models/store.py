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


DOCUMENTS: dict[str, DocumentRecord] = {}
