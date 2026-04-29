from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.models.store import DOCUMENTS
from app.services.vision_check_service import submit_review_decision


router = APIRouter()


class ReviewDecision(BaseModel):
    accept: bool
    edits: str | None = None


@router.get("/document/{document_id}/review")
def get_review(document_id: str) -> dict:
    record = DOCUMENTS.get(document_id)
    if not record:
        raise HTTPException(status_code=404, detail="Document not found")
    return {
        "status": record.status,
        "pending_reviews": [
            {
                "page_index": p.page_index,
                "issues": p.issues,
                "original_md": p.original_md,
                "proposed_md": p.proposed_md,
                "image_url": p.image_url,
            }
            for p in record.pending_reviews
        ],
    }


@router.post("/document/{document_id}/review")
def post_review(document_id: str, decision: ReviewDecision) -> dict:
    if document_id not in DOCUMENTS:
        raise HTTPException(status_code=404, detail="Document not found")
    triggered = submit_review_decision(
        document_id, accept=decision.accept, edits=decision.edits
    )
    if not triggered:
        raise HTTPException(status_code=409, detail="No pending review for this document")
    return {"ok": True}
