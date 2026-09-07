from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import get_current_user
from app.models.store import require_document_owner
from app.services.auth_service import User
from app.services.vision_check_service import submit_review_decision


router = APIRouter()


class ReviewDecision(BaseModel):
    accept: bool
    edits: str | None = None


@router.get("/document/{document_id}/review")
def get_review(document_id: str, user: User = Depends(get_current_user)) -> dict:
    record = require_document_owner(document_id, user.id)
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
def post_review(
    document_id: str,
    decision: ReviewDecision,
    user: User = Depends(get_current_user),
) -> dict:
    require_document_owner(document_id, user.id)
    triggered = submit_review_decision(
        document_id, accept=decision.accept, edits=decision.edits
    )
    if not triggered:
        raise HTTPException(status_code=409, detail="No pending review for this document")
    return {"ok": True}
