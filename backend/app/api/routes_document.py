import re
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user
from app.core.config import settings
from app.models.schemas import (
    ArtifactItem,
    DocumentStatusResponse,
    DocumentSummary,
    LocateCounterpartRequest,
    LocateCounterpartResponse,
    RenameDocumentRequest,
    ReferenceItem,
    ReviewProposalItem,
    StageItem,
)
from app.models.store import (
    list_documents_for_user,
    normalized_source_filename,
    require_document_owner,
    save_document,
    soft_delete_document,
    touch_document_opened,
    translated_pdf_filename,
)
from app.services.alignment_service import load_alignment_entries, locate_in_alignment
from app.services.auth_service import User


router = APIRouter()


def _alignment_blocks(text: str) -> list[str]:
    return [
        " ".join(part.split())
        for part in re.split(r"\n\s*\n+", text or "")
        if len(part.strip()) >= 12 and not part.lstrip().startswith("![](")
    ]


def _normalize_for_match(text: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", (text or "").lower())


def _best_block_index(blocks: list[str], selected: str, fallback_ratio: float) -> int:
    if not blocks:
        return 0
    needle = _normalize_for_match(selected)[:1200]
    if needle:
        for index, block in enumerate(blocks):
            normalized = _normalize_for_match(block)
            if needle in normalized or (len(normalized) > 20 and normalized in needle):
                return index
        scored = [
            SequenceMatcher(None, needle[:400], _normalize_for_match(block)[:1200]).ratio()
            for block in blocks
        ]
        best = max(range(len(scored)), key=scored.__getitem__)
        if scored[best] >= 0.18:
            return best
    return round(max(0.0, min(1.0, fallback_ratio)) * (len(blocks) - 1))


@router.get("/documents", response_model=list[DocumentSummary])
def list_documents(
    user: User = Depends(get_current_user),
) -> list[DocumentSummary]:
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
        for record in list_documents_for_user(user.id)
    ]
    summaries.sort(key=lambda s: s.created_at or "", reverse=True)
    return summaries


@router.get("/document/{document_id}", response_model=DocumentStatusResponse)
def get_document(
    document_id: str, user: User = Depends(get_current_user)
) -> DocumentStatusResponse:
    record = touch_document_opened(require_document_owner(document_id, user.id))

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


@router.patch("/document/{document_id}", response_model=DocumentStatusResponse)
def rename_document(
    document_id: str,
    payload: RenameDocumentRequest,
    user: User = Depends(get_current_user),
) -> DocumentStatusResponse:
    record = require_document_owner(document_id, user.id)
    try:
        record.source_filename = normalized_source_filename(
            payload.name, record.source_filename or "document.pdf"
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    out_dir = settings.output_dir / document_id
    new_pdf_name = translated_pdf_filename(record.source_filename)
    target = out_dir / new_pdf_name
    translated_artifacts = [item for item in record.artifacts if item.kind == "translated_pdf"]
    current: Path | None = None
    if translated_artifacts:
        candidate = Path(translated_artifacts[-1].path)
        if candidate.is_file():
            current = candidate
    if current is None and record.translated_pdf_url:
        legacy = out_dir / Path(record.translated_pdf_url).name
        if legacy.is_file():
            current = legacy
    if current and current.resolve() != target.resolve():
        current.replace(target)
    if target.exists():
        url = f"/data/outputs/{document_id}/{quote(new_pdf_name)}"
        record.translated_pdf_url = url
        for artifact in translated_artifacts:
            artifact.name = new_pdf_name
            artifact.path = str(target)
            artifact.url = url
    save_document(record)
    return get_document(document_id, user)


@router.post(
    "/document/{document_id}/locate-counterpart",
    response_model=LocateCounterpartResponse,
)
def locate_counterpart(
    document_id: str,
    payload: LocateCounterpartRequest,
    user: User = Depends(get_current_user),
) -> LocateCounterpartResponse:
    record = require_document_owner(document_id, user.id)
    if payload.source_side not in {"original", "translated"}:
        raise HTTPException(status_code=400, detail="source_side must be original or translated")

    original_blocks = _alignment_blocks(record.extracted_text)
    translated_blocks = _alignment_blocks(record.translated_text)
    if not original_blocks or not translated_blocks:
        raise HTTPException(status_code=409, detail="Document text is not ready for alignment")
    page_ratio = 0.0
    if payload.source_page and payload.source_page_count and payload.source_page_count > 1:
        page_ratio = (payload.source_page - 1) / (payload.source_page_count - 1)

    entries, alignment_method = load_alignment_entries(record)
    if entries:
        target_text, position_ratio, confidence, _ = locate_in_alignment(
            entries,
            source_side=payload.source_side,
            selected_text=payload.selected_text,
            page_ratio=page_ratio,
        )
        if target_text and confidence >= 0.55:
            return LocateCounterpartResponse(
                target_text=target_text,
                position_ratio=position_ratio,
                confidence=confidence,
                alignment_method=alignment_method,
            )
        raise HTTPException(
            status_code=422,
            detail="未找到可靠的双语对应位置，请多选择一句完整文本后重试",
        )

    if payload.source_side == "original":
        source_blocks, target_blocks = original_blocks, translated_blocks
    else:
        source_blocks, target_blocks = translated_blocks, original_blocks
    source_index = _best_block_index(source_blocks, payload.selected_text, page_ratio)
    block_ratio = source_index / max(1, len(source_blocks) - 1)
    target_index = round(block_ratio * max(0, len(target_blocks) - 1))
    target_text = target_blocks[target_index]
    # Strip lightweight Markdown so PDF text-layer matching is more reliable.
    target_text = re.sub(r"[#*_`]+", "", target_text)
    target_text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", target_text)
    return LocateCounterpartResponse(
        target_text=" ".join(target_text.split())[:1200],
        position_ratio=max(0.0, min(1.0, block_ratio)),
        confidence=0.0,
        alignment_method="legacy_ratio",
    )


@router.delete("/document/{document_id}")
def delete_document(
    document_id: str, user: User = Depends(get_current_user)
) -> dict:
    soft_delete_document(document_id, user.id)
    return {"ok": True, "document_id": document_id}
