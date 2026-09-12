import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from app.api.deps import get_current_user
from app.models.schemas import (
    AnnotationItem,
    CreateAnnotationRequest,
    UpdateProgressRequest,
)
from app.models.store import (
    AnnotationEntry,
    create_annotation,
    delete_annotation,
    list_annotations_for_document,
    require_document_owner,
    update_reading_progress,
)
from app.services.alignment_service import load_alignment_entries, locate_in_alignment
from app.services.auth_service import User

router = APIRouter()

_ALLOWED_COLORS = {"yellow", "green", "blue", "pink"}


def _as_item(entry: AnnotationEntry) -> AnnotationItem:
    return AnnotationItem(
        id=entry.id,
        page=entry.page,
        quote=entry.quote,
        color=entry.color,
        note=entry.note,
        position_ratio=entry.position_ratio,
        created_at=entry.created_at,
    )


@router.get("/document/{document_id}/annotations", response_model=list[AnnotationItem])
def get_annotations(
    document_id: str, user: User = Depends(get_current_user)
) -> list[AnnotationItem]:
    record = require_document_owner(document_id, user.id)
    return [
        _as_item(entry) for entry in list_annotations_for_document(record.document_id, user.id)
    ]


@router.post(
    "/document/{document_id}/annotations",
    response_model=AnnotationItem,
    status_code=201,
)
def add_annotation(
    document_id: str,
    payload: CreateAnnotationRequest,
    user: User = Depends(get_current_user),
) -> AnnotationItem:
    record = require_document_owner(document_id, user.id)
    if not payload.quote.strip():
        raise HTTPException(status_code=400, detail="Annotation quote must not be empty")
    color = payload.color if payload.color in _ALLOWED_COLORS else "yellow"
    entry = AnnotationEntry(
        id=uuid.uuid4().hex,
        document_id=record.document_id,
        owner_user_id=user.id,
        page=max(1, int(payload.page)),
        quote=payload.quote.strip()[:2000],
        color=color,
        note=payload.note.strip()[:2000],
        position_ratio=max(0.0, min(1.0, float(payload.position_ratio or 0.0))),
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    return _as_item(create_annotation(entry))


@router.delete("/document/{document_id}/annotations/{annotation_id}")
def remove_annotation(
    document_id: str, annotation_id: str, user: User = Depends(get_current_user)
) -> dict:
    record = require_document_owner(document_id, user.id)
    if not delete_annotation(annotation_id, record.document_id, user.id):
        raise HTTPException(status_code=404, detail="Annotation not found")
    return {"ok": True}


@router.patch("/document/{document_id}/progress")
def save_progress(
    document_id: str,
    payload: UpdateProgressRequest,
    user: User = Depends(get_current_user),
) -> dict:
    record = require_document_owner(document_id, user.id)
    update_reading_progress(record.document_id, payload.page, payload.ratio)
    return {"ok": True, "page": max(0, int(payload.page))}


@router.get("/document/{document_id}/notes.md")
def export_notes(document_id: str, user: User = Depends(get_current_user)) -> Response:
    record = require_document_owner(document_id, user.id)
    annotations = list_annotations_for_document(record.document_id, user.id)
    if not annotations:
        raise HTTPException(status_code=404, detail="This document has no notes yet")

    entries, _ = load_alignment_entries(record)
    lines = [
        f"# 阅读笔记 · {record.source_filename or record.document_id}",
        "",
        f"> 导出时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
    ]
    for order, entry in enumerate(annotations, start=1):
        lines.append(f"## {order}. 第 {entry.page} 页")
        lines.append("")
        lines.append(f"> {entry.quote}")
        counterpart = ""
        if entries:
            counterpart, _, confidence, _, _ = locate_in_alignment(
                entries,
                source_side="original",
                selected_text=entry.quote,
                page_ratio=entry.position_ratio,
            )
            if confidence < 0.55:
                counterpart = ""
        if counterpart:
            lines.append("")
            lines.append(f"译文：{counterpart}")
        if entry.note:
            lines.append("")
            lines.append(f"**笔记**：{entry.note}")
        lines.append("")

    content = "\n".join(lines)
    return Response(
        content=content,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="notes-{record.document_id[:8]}.md"'},
    )
