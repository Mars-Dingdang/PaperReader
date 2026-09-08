from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, File, Response, UploadFile, Cookie
from pydantic import BaseModel

from app.api.deps import get_current_user
from app.core.config import settings
from app.services.auth_service import (
    User,
    authenticate_user,
    change_password,
    create_session,
    register_user,
    revoke_session,
    save_avatar,
    serialize_settings,
    serialize_me,
    update_profile,
    update_user_settings,
)


router = APIRouter()


class RegisterRequest(BaseModel):
    username: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str
    remember_me: bool = False


class UpdateProfileRequest(BaseModel):
    username: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class UpdateSettingsRequest(BaseModel):
    # Kept for clients from PaperReader 2.0; new clients use /providers.
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None
    theme: str | None = None
    vision_enabled: bool | None = None
    vision_mode: str | None = None
    favorites: list[str] | None = None


class UpdateProviderSettingsRequest(BaseModel):
    api_key: str | None = None
    clear_api_key: bool = False
    base_url: str | None = None
    model: str | None = None
    pdf_parser: str | None = None
    mineru_api_key: str | None = None
    clear_mineru_api_key: bool = False
    mineru_base_url: str | None = None
    mineru_model_version: str | None = None
    mineru_language: str | None = None
    mineru_enable_formula: bool | None = None
    mineru_enable_table: bool | None = None
    mineru_is_ocr: bool | None = None
    vision_model: str | None = None


def _set_session_cookie(response: Response, token: str, remember_me: bool) -> None:
    max_age_days = settings.remember_me_days if remember_me else settings.session_days
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=int(timedelta(days=max_age_days).total_seconds()),
    )


@router.post("/auth/register")
def register(payload: RegisterRequest, response: Response) -> dict:
    user = register_user(payload.username, payload.password)
    token = create_session(user.id, remember_me=True)
    _set_session_cookie(response, token, remember_me=True)
    return serialize_me(user)


@router.post("/auth/login")
def login(payload: LoginRequest, response: Response) -> dict:
    user = authenticate_user(payload.username, payload.password)
    token = create_session(user.id, remember_me=payload.remember_me)
    _set_session_cookie(response, token, remember_me=payload.remember_me)
    return serialize_me(user)


@router.post("/auth/logout")
def logout(response: Response, session_token: str | None = Cookie(default=None)) -> dict:
    revoke_session(session_token)
    response.delete_cookie("session_token")
    return {"ok": True}


@router.get("/auth/me")
def me(user: User = Depends(get_current_user)) -> dict:
    return serialize_me(user)


@router.patch("/auth/profile")
def patch_profile(payload: UpdateProfileRequest, user: User = Depends(get_current_user)) -> dict:
    updated = update_profile(user.id, payload.username)
    return serialize_me(updated)


@router.post("/auth/change-password")
def post_change_password(payload: ChangePasswordRequest, user: User = Depends(get_current_user)) -> dict:
    change_password(user.id, payload.current_password, payload.new_password)
    return {"ok": True}


@router.post("/auth/avatar")
async def post_avatar(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
) -> dict:
    content = await file.read()
    updated = save_avatar(user.id, file.filename or "avatar.png", content)
    return serialize_me(updated)


@router.put("/settings/me")
def put_settings(payload: UpdateSettingsRequest, user: User = Depends(get_current_user)) -> dict:
    settings_row = update_user_settings(
        user.id,
        api_key=payload.api_key,
        base_url=payload.base_url,
        model=payload.model,
        theme=payload.theme,
        vision_enabled=payload.vision_enabled,
        vision_mode=payload.vision_mode,
        favorites=payload.favorites,
    )
    return serialize_settings(settings_row)


@router.put("/settings/me/providers")
def put_provider_settings(
    payload: UpdateProviderSettingsRequest,
    user: User = Depends(get_current_user),
) -> dict:
    settings_row = update_user_settings(
        user.id,
        api_key=payload.api_key,
        clear_api_key=payload.clear_api_key,
        base_url=payload.base_url,
        model=payload.model,
        pdf_parser=payload.pdf_parser,
        mineru_api_key=payload.mineru_api_key,
        clear_mineru_api_key=payload.clear_mineru_api_key,
        mineru_base_url=payload.mineru_base_url,
        mineru_model_version=payload.mineru_model_version,
        mineru_language=payload.mineru_language,
        mineru_enable_formula=payload.mineru_enable_formula,
        mineru_enable_table=payload.mineru_enable_table,
        mineru_is_ocr=payload.mineru_is_ocr,
        vision_model=payload.vision_model,
    )
    return serialize_settings(settings_row)
