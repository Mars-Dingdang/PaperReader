from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import get_current_user
from app.models.store import (
    ArtifactEntry,
    require_document_owner,
    save_document,
    translated_pdf_filename,
)
from app.services.auth_service import User
from app.services.latex_sanitizer import sanitize_latex_body
from app.services.latex_service import (
    compile_tex_project_with_fallback,
    copy_pdf_to_output,
)


router = APIRouter()


class RecompileRequest(BaseModel):
    tex_content: str


class RecompileResponse(BaseModel):
    ok: bool
    pdf_url: str | None = None
    warning: str | None = None
    error: str | None = None


def _resolve_translated_tex(record) -> Path:
    if record.translated_tex_path and record.translated_tex_path.exists():
        return record.translated_tex_path
    # Fallback: derive from output dir convention
    from app.core.config import settings as _settings  # local import to avoid cycle

    candidate = _settings.output_dir / record.document_id / "translated.tex"
    if candidate.exists():
        return candidate
    raise HTTPException(status_code=404, detail="translated.tex not found for this document")


@router.get("/document/{document_id}/tex")
def get_document_tex(document_id: str, user: User = Depends(get_current_user)) -> dict:
    record = require_document_owner(document_id, user.id)
    tex_path = _resolve_translated_tex(record)
    return {"tex_content": tex_path.read_text(encoding="utf-8", errors="ignore")}


def _ensure_artifact(record, name: str, kind: str, path: Path) -> None:
    url = f"/data/outputs/{record.document_id}/{path.name}"
    for existing in record.artifacts:
        if existing.name == name or existing.kind == kind:
            existing.name = name
            existing.kind = kind
            existing.path = str(path)
            existing.url = url
            return
    record.artifacts.append(ArtifactEntry(name=name, kind=kind, path=str(path), url=url))


@router.post("/document/{document_id}/tex", response_model=RecompileResponse)
def recompile_document_tex(
    document_id: str,
    payload: RecompileRequest,
    user: User = Depends(get_current_user),
) -> RecompileResponse:
    record = require_document_owner(document_id, user.id)
    tex_path = _resolve_translated_tex(record)
    output_dir = tex_path.parent

    sanitized = sanitize_latex_body(payload.tex_content)
    tex_path.write_text(sanitized, encoding="utf-8")

    # For tex_project sources, also mirror into the project dir so that
    # \\includegraphics paths continue to resolve.
    if record.source_type in ("tex", "tex_project"):
        mirror = record.source_path.parent / "__translated.tex"
        try:
            mirror.write_text(sanitized, encoding="utf-8")
            tex_to_compile = mirror
        except Exception:
            tex_to_compile = tex_path
    else:
        tex_to_compile = tex_path

    try:
        result = compile_tex_project_with_fallback(tex_to_compile, output_dir)
    except Exception as exc:
        record.logs.append(f"Manual recompile failed: {exc}")
        return RecompileResponse(ok=False, error=str(exc))

    translated_name = translated_pdf_filename(record.source_filename)
    translated_out = output_dir / translated_name
    copy_pdf_to_output(result.pdf_path, translated_out)
    if result.pdf_path.resolve() != translated_out.resolve():
        result.pdf_path.unlink(missing_ok=True)
    record.translated_pdf_url = f"/data/outputs/{record.document_id}/{translated_name}"
    record.translated_tex_path = tex_path
    record.last_compile_warning = result.warning
    _ensure_artifact(record, translated_name, "translated_pdf", translated_out)
    _ensure_artifact(record, "translated.tex", "translated_tex", tex_path)
    record.logs.append("Manual recompile succeeded" + (f" (warning: {result.warning})" if result.warning else ""))
    save_document(record)

    return RecompileResponse(
        ok=True,
        pdf_url=record.translated_pdf_url,
        warning=result.warning,
    )
