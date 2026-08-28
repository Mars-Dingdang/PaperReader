from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.models.schemas import (
    ArtifactItem,
    DocumentStatusResponse,
    DocumentSummary,
    ReferenceItem,
    ReviewProposalItem,
    StageItem,
)
from app.models.store import list_documents_for_user, require_document_owner, soft_delete_document, touch_document_opened
from app.services.auth_service import User


router = APIRouter()


@router.get("/documents", response_model=list[DocumentSummary])
def list_documents(user: User = Depends(get_current_user)) -> list[DocumentSummary]:
    summaries = [
        DocumentSummary(
            document_id=record.document_id,
            status=record.status,
            source_type=record.source_type,
            source_filename=record.source_filename,
            size_bytes=record.size_bytes,
            created_at=record.created_at.isoformat() if record.created_at else None,
            updated_at=record.updated_at.isoformat() if record.updated_at else None,
            last_opened_at=record.last_opened_at.isoformat() if record.last_opened_at else None,
            has_translated_pdf=bool(record.translated_pdf_url),
        )
        for record in list_documents_for_user(user.id)
    ]
    return summaries


@router.get("/document/{document_id}", response_model=DocumentStatusResponse)
def get_document(document_id: str, user: User = Depends(get_current_user)) -> DocumentStatusResponse:
    record = touch_document_opened(require_document_owner(document_id, user.id))

    return DocumentStatusResponse(
        document_id=record.document_id,
        status=record.status,
        source_type=record.source_type,
        source_filename=record.source_filename,
        updated_at=record.updated_at.isoformat() if record.updated_at else None,
        last_opened_at=record.last_opened_at.isoformat() if record.last_opened_at else None,
        original_pdf_url=record.original_pdf_url,
        translated_pdf_url=record.translated_pdf_url,
        artifacts=[
            ArtifactItem(name=item.name, kind=item.kind, path=item.path, url=item.url)
            for item in record.artifacts
        ],
        references=[ReferenceItem(index=item.index, text=item.text) for item in record.references],
        logs=record.logs,
        progress=record.progress,
        current_stage=record.current_stage,
        current_stage_label=record.current_stage_label,
        eta_seconds=record.eta_seconds,
        stages=[
            StageItem(
                key=s.key,
                label=s.label,
                weight=s.weight,
                status=s.status,
                started_at=s.started_at,
                ended_at=s.ended_at,
                duration_ms=s.duration_ms,
            )
            for s in record.stages
        ],
        pending_reviews=[
            ReviewProposalItem(
                page_index=p.page_index,
                issues=p.issues,
                original_md=p.original_md,
                proposed_md=p.proposed_md,
                image_url=p.image_url,
            )
            for p in record.pending_reviews
        ],
        last_compile_warning=record.last_compile_warning,
    )


@router.delete("/document/{document_id}")
def delete_document(document_id: str, user: User = Depends(get_current_user)) -> dict:
    soft_delete_document(document_id, user.id)
    return {"ok": True}
