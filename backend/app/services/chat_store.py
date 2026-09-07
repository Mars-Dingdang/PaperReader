"""Persistent chat sessions shared by document and library-wide chat UIs."""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import settings


_STORE_PATH = settings.data_dir / "chat_sessions.json"
_LOCK = threading.RLock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load() -> dict[str, dict]:
    if not _STORE_PATH.exists():
        return {}
    try:
        raw = json.loads(_STORE_PATH.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _save(sessions: dict[str, dict]) -> None:
    _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = _STORE_PATH.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(sessions, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(_STORE_PATH)


def create_session(
    *,
    owner_user_id: int,
    scope: str,
    document_ids: list[str] | None = None,
    title: str | None = None,
) -> dict:
    session_id = str(uuid.uuid4())
    created = _now()
    session = {
        "session_id": session_id,
        "owner_user_id": owner_user_id,
        "scope": "library" if scope == "library" else "document",
        "document_ids": list(dict.fromkeys(document_ids or [])),
        "title": (title or "新会话").strip()[:80] or "新会话",
        "created_at": created,
        "updated_at": created,
        "messages": [],
    }
    with _LOCK:
        sessions = _load()
        sessions[session_id] = session
        _save(sessions)
    return session


def get_session(session_id: str, *, owner_user_id: int) -> dict | None:
    with _LOCK:
        session = _load().get(session_id)
        if not session or session.get("owner_user_id") != owner_user_id:
            return None
        return dict(session)


def list_sessions(
    *, owner_user_id: int, scope: str, document_id: str | None = None
) -> list[dict]:
    with _LOCK:
        sessions = list(_load().values())
    wanted_scope = "library" if scope == "library" else "document"
    filtered = [
        item
        for item in sessions
        if item.get("owner_user_id") == owner_user_id
        and item.get("scope") == wanted_scope
    ]
    if wanted_scope == "document" and document_id:
        filtered = [
            item for item in filtered if document_id in (item.get("document_ids") or [])
        ]
    filtered.sort(key=lambda item: item.get("updated_at") or "", reverse=True)
    return filtered


def append_message(
    session_id: str, *, owner_user_id: int, role: str, content: str
) -> dict:
    with _LOCK:
        sessions = _load()
        session = sessions.get(session_id)
        if not session or session.get("owner_user_id") != owner_user_id:
            raise KeyError(session_id)
        message = {
            "message_id": str(uuid.uuid4()),
            "role": role,
            "content": content,
            "created_at": _now(),
        }
        session.setdefault("messages", []).append(message)
        session["updated_at"] = message["created_at"]
        if role == "user" and session.get("title") == "新会话":
            compact = " ".join(content.split())
            session["title"] = compact[:36] + ("…" if len(compact) > 36 else "")
        sessions[session_id] = session
        _save(sessions)
        return message


def update_session_documents(
    session_id: str, document_ids: list[str], *, owner_user_id: int
) -> dict:
    with _LOCK:
        sessions = _load()
        session = sessions.get(session_id)
        if not session or session.get("owner_user_id") != owner_user_id:
            raise KeyError(session_id)
        session["document_ids"] = list(dict.fromkeys(document_ids))
        session["updated_at"] = _now()
        sessions[session_id] = session
        _save(sessions)
        return session
