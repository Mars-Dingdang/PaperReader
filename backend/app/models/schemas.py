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


class StageItem(BaseModel):
    key: str
    label: str
    weight: float
    status: str
    started_at: float | None = None
    ended_at: float | None = None
    duration_ms: int | None = None


class ReviewProposalItem(BaseModel):
    page_index: int
    issues: list[str] = []
    original_md: str = ""
    proposed_md: str = ""
    image_url: str | None = None


class FailureItem(BaseModel):
    stage: str
    message: str
    retryable: bool = True
    chunk: int | None = None
    retry_count: int = 0


class LatexRecoveryItem(BaseModel):
    status: str
    diagnosis: str | None = None
    repairs: list[dict] = []
    rounds: int = 0
    last_error: str | None = None


class RetryDocumentResponse(BaseModel):
    document_id: str
    status: str
    resume_from: str


class DocumentStatusResponse(BaseModel):
    document_id: str
    status: str
    source_type: str
    source_filename: str = ""
    updated_at: str | None = None
    last_opened_at: str | None = None
    original_pdf_url: str | None = None
    translated_pdf_url: str | None = None
    artifacts: list[ArtifactItem] = []
    references: list[ReferenceItem] = []
    logs: list[str] = []
    progress: int = 0
    current_stage: str | None = None
    current_stage_label: str | None = None
    eta_seconds: int | None = None
    stages: list[StageItem] = []
    pending_reviews: list[ReviewProposalItem] = []
    last_compile_warning: str | None = None
    failure: FailureItem | None = None
    latex_recovery: LatexRecoveryItem | None = None
    last_read_page: int = 0
    last_read_ratio: float = 0.0


class ChatRequest(BaseModel):
    document_id: str | None = None
    document_ids: list[str] = []
    scope: str = "document"
    session_id: str | None = None
    message: str
    quote: str | None = None
    override_api_key: str | None = None
    override_base_url: str | None = None
    override_model: str | None = None


class SourceRefItem(BaseModel):
    label: str
    title: str = ""
    content: str = ""
    document_id: str | None = None
    position_ratio: float | None = None


class ChatResponse(BaseModel):
    answer: str
    session_id: str
    sources: list[SourceRefItem] = []


class ChatMessageItem(BaseModel):
    message_id: str
    role: str
    content: str
    created_at: str


class ChatSessionItem(BaseModel):
    session_id: str
    scope: str
    document_ids: list[str] = []
    title: str
    created_at: str
    updated_at: str
    messages: list[ChatMessageItem] = []


class CreateChatSessionRequest(BaseModel):
    scope: str = "document"
    document_ids: list[str] = []
    title: str | None = None


class RenameDocumentRequest(BaseModel):
    name: str


class LocateCounterpartRequest(BaseModel):
    source_side: str
    selected_text: str
    source_page: int | None = None
    source_page_count: int | None = None


class LocateCounterpartResponse(BaseModel):
    target_text: str
    position_ratio: float
    confidence: float = 0.0
    alignment_method: str = ""
    highlight_text: str = ""


class DocumentSummary(BaseModel):
    document_id: str
    status: str
    source_type: str
    source_filename: str = ""
    size_bytes: int = 0
    created_at: str | None = None
    updated_at: str | None = None
    last_opened_at: str | None = None
    has_translated_pdf: bool = False
    title: str = ""
    year: str = ""


class AnnotationItem(BaseModel):
    id: str
    page: int
    quote: str
    color: str = "yellow"
    note: str = ""
    position_ratio: float = 0.0
    created_at: str = ""


class CreateAnnotationRequest(BaseModel):
    page: int
    quote: str
    color: str = "yellow"
    note: str = ""
    position_ratio: float = 0.0


class UpdateProgressRequest(BaseModel):
    page: int = 1
    ratio: float = 0.0
