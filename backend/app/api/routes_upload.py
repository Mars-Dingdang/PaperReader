from pathlib import Path
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile

from app.api.deps import get_current_user
from app.core.config import settings
from app.models.schemas import UploadResponse
from app.models.store import get_document
from app.services.auth_service import User
from app.services.document_pipeline import create_document_record, process_document


router = APIRouter()


def _run_pipeline(record_id: str) -> None:
    record = get_document(record_id)
    if record:
        process_document(record)


@router.post("/upload", response_model=UploadResponse)
async def upload(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    vision_check_enabled: bool = Form(False),
    vision_check_mode: str = Form("auto"),
    user: User = Depends(get_current_user),
) -> UploadResponse:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".pdf", ".tex"}:
        raise HTTPException(status_code=400, detail="Only .pdf and .tex are supported in MVP")

    safe_name = Path(file.filename or "uploaded_file").name
    target_path = settings.upload_dir / f"{uuid.uuid4()}_{safe_name}"
    content = await file.read()
    target_path.write_bytes(content)

    source_type = "tex" if suffix == ".tex" else "pdf"
    record = create_document_record(target_path, source_type, owner_user_id=user.id)
    record.vision_check_enabled = bool(vision_check_enabled)
    record.vision_check_mode = vision_check_mode if vision_check_mode in ("auto", "manual") else "auto"

    background_tasks.add_task(_run_pipeline, record.document_id)
    return UploadResponse(document_id=record.document_id, status=record.status)
