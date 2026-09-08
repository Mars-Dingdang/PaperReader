from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from app.core.config import apply_runtime_provider_values, settings
from app.core.local_config import save_bootstrap_provider, setup_status


router = APIRouter()


class InitialSetupRequest(BaseModel):
    api_key: str = Field(min_length=1)
    base_url: str = Field(min_length=1)
    model: str = Field(min_length=1)
    pdf_parser: str = "local"
    mineru_api_key: str = ""
    mineru_base_url: str = "https://mineru.net/api/v4"
    mineru_model_version: str = "vlm"
    mineru_language: str = "en"
    mineru_enable_formula: bool = True
    mineru_enable_table: bool = True
    mineru_is_ocr: bool = False
    vision_model: str = "GLM-4.5V"


def _validate_url(value: str, label: str) -> str:
    value = value.strip().rstrip("/")
    if not value.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail=f"{label} must start with http:// or https://")
    return value


@router.get("/setup/status")
def get_setup_status() -> dict[str, object]:
    return setup_status(desktop_mode=settings.desktop_mode)


@router.put("/setup")
def put_setup(
    payload: InitialSetupRequest,
    request: Request,
    origin: str | None = Header(default=None),
) -> dict[str, object]:
    status = setup_status(desktop_mode=settings.desktop_mode)
    if not settings.desktop_mode:
        raise HTTPException(status_code=403, detail="Initial setup is available in the desktop app only")
    if not status["required"]:
        raise HTTPException(status_code=409, detail="Initial setup is already complete")
    allowed_origin = f"{request.url.scheme}://{request.url.netloc}"
    if origin and origin.rstrip("/") != allowed_origin.rstrip("/"):
        raise HTTPException(status_code=403, detail="Cross-origin setup is not allowed")
    parser = payload.pdf_parser.strip().lower()
    if parser not in {"local", "mineru"}:
        raise HTTPException(status_code=400, detail="pdf_parser must be local or mineru")
    if parser == "mineru" and not payload.mineru_api_key.strip():
        raise HTTPException(status_code=400, detail="MinerU API Key is required for MinerU parsing")
    values = payload.model_dump()
    values.update(
        api_key=payload.api_key.strip(),
        base_url=_validate_url(payload.base_url, "Base URL"),
        model=payload.model.strip(),
        pdf_parser=parser,
        mineru_api_key=payload.mineru_api_key.strip(),
        mineru_base_url=_validate_url(payload.mineru_base_url, "MinerU Base URL"),
        mineru_model_version=payload.mineru_model_version.strip() or "vlm",
        mineru_language=payload.mineru_language.strip() or "en",
        vision_model=payload.vision_model.strip() or "GLM-4.5V",
    )
    save_bootstrap_provider(values)
    apply_runtime_provider_values(values)
    return {"ok": True, "required": False}
