from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import HTTPException

from app.core.config import settings
from app.core.database import db_cursor


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat()


def _from_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def _secret_bytes() -> bytes:
    return settings.auth_secret_key.encode("utf-8")


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 260_000)
    return "pbkdf2_sha256$260000$%s$%s" % (salt.hex(), digest.hex())


def verify_password(password: str, encoded: str) -> bool:
    try:
        algo, rounds, salt_hex, digest_hex = encoded.split("$", 3)
    except ValueError:
        return False
    if algo != "pbkdf2_sha256":
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt_hex),
        int(rounds),
    )
    return hmac.compare_digest(digest.hex(), digest_hex)


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    blocks: list[bytes] = []
    counter = 0
    while sum(len(block) for block in blocks) < length:
        blocks.append(hmac.new(key, nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest())
        counter += 1
    return b"".join(blocks)[:length]


def encrypt_secret(value: str) -> str:
    if not value:
        return ""
    plain = value.encode("utf-8")
    nonce = secrets.token_bytes(16)
    stream = _keystream(_secret_bytes(), nonce, len(plain))
    cipher = bytes(a ^ b for a, b in zip(plain, stream))
    tag = hmac.new(_secret_bytes(), nonce + cipher, hashlib.sha256).digest()
    payload = base64.urlsafe_b64encode(nonce + tag + cipher).decode("ascii")
    return f"v1:{payload}"


def decrypt_secret(value: str | None) -> str:
    if not value:
        return ""
    if not value.startswith("v1:"):
        return ""
    raw = base64.urlsafe_b64decode(value[3:].encode("ascii"))
    nonce, tag, cipher = raw[:16], raw[16:48], raw[48:]
    expected = hmac.new(_secret_bytes(), nonce + cipher, hashlib.sha256).digest()
    if not hmac.compare_digest(tag, expected):
        return ""
    stream = _keystream(_secret_bytes(), nonce, len(cipher))
    plain = bytes(a ^ b for a, b in zip(cipher, stream))
    return plain.decode("utf-8")


@dataclass
class User:
    id: int
    username: str
    avatar_path: str | None
    created_at: str
    updated_at: str
    last_login_at: str | None

    @property
    def avatar_url(self) -> str | None:
        if not self.avatar_path:
            return None
        return self.avatar_path


@dataclass
class UserSettings:
    user_id: int
    api_key: str
    base_url: str
    model: str
    theme: str
    vision_enabled: bool
    vision_mode: str
    favorites: list[str]
    created_at: str
    updated_at: str


def _row_to_user(row) -> User:
    return User(
        id=int(row["id"]),
        username=row["username"],
        avatar_path=row["avatar_path"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        last_login_at=row["last_login_at"],
    )


def _default_settings(user_id: int) -> UserSettings:
    now = _to_iso(_utcnow()) or ""
    return UserSettings(
        user_id=user_id,
        api_key="",
        base_url=settings.openai_base_url,
        model=settings.openai_model,
        theme="light",
        vision_enabled=True,
        vision_mode="auto",
        favorites=[],
        created_at=now,
        updated_at=now,
    )


def ensure_user_settings(user_id: int) -> UserSettings:
    with db_cursor() as conn:
        row = conn.execute(
            "SELECT * FROM user_settings WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if row:
            return UserSettings(
                user_id=int(row["user_id"]),
                api_key=decrypt_secret(row["llm_api_key_enc"]),
                base_url=row["llm_base_url"] or settings.openai_base_url,
                model=row["llm_model"] or settings.openai_model,
                theme=row["theme"] or "light",
                vision_enabled=bool(row["vision_enabled"]),
                vision_mode=row["vision_mode"] or "auto",
                favorites=json.loads(row["favorites_json"] or "[]"),
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )

        settings_row = _default_settings(user_id)
        conn.execute(
            """
            INSERT INTO user_settings (
                user_id, llm_api_key_enc, llm_base_url, llm_model, theme,
                vision_enabled, vision_mode, favorites_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                "",
                settings_row.base_url,
                settings_row.model,
                settings_row.theme,
                1,
                settings_row.vision_mode,
                json.dumps(settings_row.favorites),
                settings_row.created_at,
                settings_row.updated_at,
            ),
        )
        return settings_row


def register_user(username: str, password: str) -> User:
    username = username.strip()
    if len(username) < 3:
        raise HTTPException(status_code=400, detail="Username must be at least 3 characters")
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    now = _to_iso(_utcnow()) or ""
    with db_cursor() as conn:
        existing = conn.execute(
            "SELECT id FROM users WHERE lower(username) = lower(?)",
            (username,),
        ).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail="Username already exists")

        cur = conn.execute(
            """
            INSERT INTO users (username, password_hash, avatar_path, created_at, updated_at, last_login_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (username, hash_password(password), None, now, now, None),
        )
        user_id = int(cur.lastrowid)

    ensure_user_settings(user_id)
    return get_user_by_id(user_id)


def authenticate_user(username: str, password: str) -> User:
    with db_cursor() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE lower(username) = lower(?)",
            (username.strip(),),
        ).fetchone()
        if not row or not verify_password(password, row["password_hash"]):
            raise HTTPException(status_code=401, detail="Invalid username or password")

        now = _to_iso(_utcnow()) or ""
        conn.execute(
            "UPDATE users SET last_login_at = ?, updated_at = ? WHERE id = ?",
            (now, now, row["id"]),
        )
    return get_user_by_id(int(row["id"]))


def get_user_by_id(user_id: int) -> User:
    with db_cursor() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    return _row_to_user(row)


def create_session(user_id: int, remember_me: bool) -> str:
    token = secrets.token_urlsafe(32)
    now = _utcnow()
    expiry = now + timedelta(days=settings.remember_me_days if remember_me else settings.session_days)
    session_id = str(uuid.uuid4())
    with db_cursor() as conn:
        conn.execute(
            """
            INSERT INTO sessions (id, user_id, token_hash, expires_at, created_at, last_seen_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                user_id,
                _token_hash(token),
                _to_iso(expiry),
                _to_iso(now),
                _to_iso(now),
            ),
        )
    return token


def get_user_by_session_token(token: str | None) -> User | None:
    if not token:
        return None
    now = _utcnow()
    with db_cursor() as conn:
        row = conn.execute(
            """
            SELECT sessions.user_id, sessions.expires_at, users.*
            FROM sessions
            JOIN users ON users.id = sessions.user_id
            WHERE sessions.token_hash = ?
            """,
            (_token_hash(token),),
        ).fetchone()
        if not row:
            return None

        expires_at = _from_iso(row["expires_at"])
        if expires_at is None or expires_at <= now:
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))
            return None

        conn.execute(
            "UPDATE sessions SET last_seen_at = ? WHERE token_hash = ?",
            (_to_iso(now), _token_hash(token)),
        )
        return _row_to_user(row)


def revoke_session(token: str | None) -> None:
    if not token:
        return
    with db_cursor() as conn:
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))


def update_profile(user_id: int, username: str | None = None) -> User:
    user = get_user_by_id(user_id)
    new_username = user.username if username is None else username.strip()
    if len(new_username) < 3:
        raise HTTPException(status_code=400, detail="Username must be at least 3 characters")

    now = _to_iso(_utcnow()) or ""
    with db_cursor() as conn:
        existing = conn.execute(
            "SELECT id FROM users WHERE lower(username) = lower(?) AND id != ?",
            (new_username, user_id),
        ).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail="Username already exists")
        conn.execute(
            "UPDATE users SET username = ?, updated_at = ? WHERE id = ?",
            (new_username, now, user_id),
        )
    return get_user_by_id(user_id)


def change_password(user_id: int, current_password: str, new_password: str) -> None:
    if len(new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    with db_cursor() as conn:
        row = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row or not verify_password(current_password, row["password_hash"]):
            raise HTTPException(status_code=400, detail="Current password is incorrect")
        conn.execute(
            "UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?",
            (hash_password(new_password), _to_iso(_utcnow()), user_id),
        )


def save_avatar(user_id: int, filename: str, content: bytes) -> User:
    suffix = Path(filename or "avatar.png").suffix.lower() or ".png"
    if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise HTTPException(status_code=400, detail="Unsupported avatar type")
    user_dir = settings.data_dir / "users" / str(user_id)
    user_dir.mkdir(parents=True, exist_ok=True)
    avatar_path = user_dir / f"avatar{suffix}"
    avatar_path.write_bytes(content)
    avatar_url = f"/data/users/{user_id}/{avatar_path.name}"
    with db_cursor() as conn:
        conn.execute(
            "UPDATE users SET avatar_path = ?, updated_at = ? WHERE id = ?",
            (avatar_url, _to_iso(_utcnow()), user_id),
        )
    return get_user_by_id(user_id)


def update_user_settings(
    user_id: int,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    theme: str | None = None,
    vision_enabled: bool | None = None,
    vision_mode: str | None = None,
    favorites: list[str] | None = None,
) -> UserSettings:
    current = ensure_user_settings(user_id)
    next_settings = UserSettings(
        user_id=user_id,
        api_key=current.api_key if api_key is None else api_key.strip(),
        base_url=current.base_url if base_url is None else base_url.strip(),
        model=current.model if model is None else model.strip(),
        theme=current.theme if theme is None else theme,
        vision_enabled=current.vision_enabled if vision_enabled is None else bool(vision_enabled),
        vision_mode=current.vision_mode if vision_mode is None else vision_mode,
        favorites=current.favorites if favorites is None else favorites,
        created_at=current.created_at,
        updated_at=_to_iso(_utcnow()) or current.updated_at,
    )

    if next_settings.theme not in {"light", "dark"}:
        next_settings.theme = "light"
    if next_settings.vision_mode not in {"auto", "manual"}:
        next_settings.vision_mode = "auto"
    if not next_settings.base_url:
        next_settings.base_url = settings.openai_base_url
    if not next_settings.model:
        next_settings.model = settings.openai_model

    with db_cursor() as conn:
        conn.execute(
            """
            UPDATE user_settings
            SET llm_api_key_enc = ?, llm_base_url = ?, llm_model = ?, theme = ?,
                vision_enabled = ?, vision_mode = ?, favorites_json = ?, updated_at = ?
            WHERE user_id = ?
            """,
            (
                encrypt_secret(next_settings.api_key),
                next_settings.base_url,
                next_settings.model,
                next_settings.theme,
                1 if next_settings.vision_enabled else 0,
                next_settings.vision_mode,
                json.dumps(next_settings.favorites),
                next_settings.updated_at,
                user_id,
            ),
        )
    return ensure_user_settings(user_id)


def serialize_me(user: User) -> dict:
    user_settings = ensure_user_settings(user.id)
    return {
        "id": user.id,
        "username": user.username,
        "avatar_url": user.avatar_url,
        "created_at": user.created_at,
        "updated_at": user.updated_at,
        "last_login_at": user.last_login_at,
        "settings": {
            "api_key": user_settings.api_key,
            "base_url": user_settings.base_url,
            "model": user_settings.model,
            "theme": user_settings.theme,
            "vision_enabled": user_settings.vision_enabled,
            "vision_mode": user_settings.vision_mode,
            "favorites": user_settings.favorites,
        },
    }
