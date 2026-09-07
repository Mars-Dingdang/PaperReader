"""Serve existing artifact URLs while enforcing the account's ownership."""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.database import db_cursor
from app.models.store import list_documents_for_user
from app.services.auth_service import User

router = APIRouter()


@router.api_route("/data/{file_path:path}", methods=["GET", "HEAD"])
def get_data_file(file_path: str, user: User = Depends(get_current_user)) -> FileResponse:
    root = settings.data_dir.resolve()
    target = (root / file_path).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    allowed = bool(user.avatar_path and f"/data/{file_path}" == user.avatar_path)
    for record in list_documents_for_user(user.id):
        if target == record.source_path.resolve() or target.is_relative_to(
            (settings.output_dir / record.document_id).resolve()
        ):
            allowed = True
            break
    if not allowed:
        with db_cursor() as conn:
            projects = conn.execute(
                "SELECT dir FROM projects WHERE owner_user_id = ? AND deleted_at IS NULL",
                (user.id,),
            ).fetchall()
        allowed = any(target.is_relative_to(Path(row["dir"]).resolve()) for row in projects)
    if not allowed:
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(target, headers={"Cache-Control": "private, no-store"})
