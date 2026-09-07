from __future__ import annotations

from fastapi import Cookie, HTTPException

from app.services.auth_service import User, get_user_by_session_token


def get_current_user(session_token: str | None = Cookie(default=None)) -> User:
    user = get_user_by_session_token(session_token)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user
