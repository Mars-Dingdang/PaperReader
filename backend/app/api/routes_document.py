from fastapi import APIRouter, HTTPException

from app.models.schemas import ArtifactItem, DocumentStatusResponse, DocumentSummary, ReferenceItem
from app.models.store import DOCUMENTS


router = APIRouter()


@router.get("/documents", response_model=list[DocumentSummary])
def list_documents() -> list[DocumentSummary]:
    summaries = [
        DocumentSummary(
            document_id=record.document_id,
            status=record.status,
            source_type=record.source_type,
            source_filename=record.source_filename,
            size_bytes=record.size_bytes,
            created_at=record.created_at.isoformat() if record.created_at else None,
            has_translated_pdf=bool(record.translated_pdf_url),
        )
        for record in DOCUMENTS.values()
    ]
    summaries.sort(key=lambda s: s.created_at or "", reverse=True)
    return summaries


@router.get("/document/{document_id}", response_model=DocumentStatusResponse)
def get_document(document_id: str) -> DocumentStatusResponse:
    record = DOCUMENTS.get(document_id)
    if not record:
        raise HTTPException(status_code=404, detail="Document not found")

    return DocumentStatusResponse(
        document_id=record.document_id,
        status=record.status,
        source_type=record.source_type,
        source_filename=record.source_filename,
        original_pdf_url=record.original_pdf_url,
        translated_pdf_url=record.translated_pdf_url,
        artifacts=[
            ArtifactItem(name=item.name, kind=item.kind, path=item.path, url=item.url)
            for item in record.artifacts
        ],
        references=[ReferenceItem(index=item.index, text=item.text) for item in record.references],
        logs=record.logs,
    )
