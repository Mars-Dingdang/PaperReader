from pydantic import BaseModel


class UploadResponse(BaseModel):
    document_id: str
    status: str


class ArtifactItem(BaseModel):
    name: str
    kind: str
    path: str
    url: str | None = None


class ReferenceItem(BaseModel):
    index: int
    text: str


class DocumentStatusResponse(BaseModel):
    document_id: str
    status: str
    source_type: str
    source_filename: str = ""
    original_pdf_url: str | None = None
    translated_pdf_url: str | None = None
    artifacts: list[ArtifactItem] = []
    references: list[ReferenceItem] = []
    logs: list[str] = []


class ChatRequest(BaseModel):
    document_id: str
    message: str
    override_api_key: str | None = None
    override_base_url: str | None = None
    override_model: str | None = None


class ChatResponse(BaseModel):
    answer: str


class DocumentSummary(BaseModel):
    document_id: str
    status: str
    source_type: str
    source_filename: str = ""
    size_bytes: int = 0
    created_at: str | None = None
    has_translated_pdf: bool = False
