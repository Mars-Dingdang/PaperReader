from pathlib import Path
import uuid

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.core.config import settings
from app.models.schemas import UploadResponse
from app.services.document_pipeline import create_document_record, process_document


router = APIRouter()


@router.post("/upload", response_model=UploadResponse)
async def upload(file: UploadFile = File(...)) -> UploadResponse:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".pdf", ".tex"}:
        raise HTTPException(status_code=400, detail="Only .pdf and .tex are supported in MVP")

    safe_name = Path(file.filename or "uploaded_file").name
    target_path = settings.upload_dir / f"{uuid.uuid4()}_{safe_name}"
    content = await file.read()
    target_path.write_bytes(content)

    source_type = "tex" if suffix == ".tex" else "pdf"
    record = create_document_record(target_path, source_type)
    process_document(record)

    return UploadResponse(document_id=record.document_id, status=record.status)
