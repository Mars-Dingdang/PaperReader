from __future__ import annotations

import sqlite3
import json
from contextlib import contextmanager
from pathlib import Path

from app.core.config import settings


def _db_path() -> Path:
    path = settings.data_dir / settings.sqlite_db_name
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    _initialize_schema(conn)
    return conn


@contextmanager
def db_cursor():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _initialize_schema(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                avatar_path TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_login_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id INTEGER PRIMARY KEY,
                llm_api_key_enc TEXT,
                llm_base_url TEXT,
                llm_model TEXT,
                pdf_parser TEXT NOT NULL DEFAULT 'local',
                mineru_api_key_enc TEXT,
                mineru_base_url TEXT,
                mineru_model_version TEXT,
                mineru_language TEXT,
                mineru_enable_formula INTEGER NOT NULL DEFAULT 1,
                mineru_enable_table INTEGER NOT NULL DEFAULT 1,
                mineru_is_ocr INTEGER NOT NULL DEFAULT 0,
                vision_model TEXT,
                theme TEXT NOT NULL DEFAULT 'light',
                vision_enabled INTEGER NOT NULL DEFAULT 0,
                vision_mode TEXT NOT NULL DEFAULT 'auto',
                favorites_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )
        existing_settings_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(user_settings)").fetchall()
        }
        settings_migrations = {
            "pdf_parser": "TEXT NOT NULL DEFAULT 'local'",
            "mineru_api_key_enc": "TEXT",
            "mineru_base_url": "TEXT",
            "mineru_model_version": "TEXT",
            "mineru_language": "TEXT",
            "mineru_enable_formula": "INTEGER NOT NULL DEFAULT 1",
            "mineru_enable_table": "INTEGER NOT NULL DEFAULT 1",
            "mineru_is_ocr": "INTEGER NOT NULL DEFAULT 0",
            "vision_model": "TEXT",
        }
        for column, declaration in settings_migrations.items():
            if column not in existing_settings_columns:
                conn.execute(f"ALTER TABLE user_settings ADD COLUMN {column} {declaration}")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS documents (
                document_id TEXT PRIMARY KEY,
                owner_user_id INTEGER NOT NULL,
                source_type TEXT NOT NULL,
                source_path TEXT NOT NULL,
                source_filename TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                original_pdf_url TEXT,
                translated_pdf_url TEXT,
                extracted_text TEXT NOT NULL DEFAULT '',
                translated_text TEXT NOT NULL DEFAULT '',
                artifacts_json TEXT NOT NULL DEFAULT '[]',
                references_json TEXT NOT NULL DEFAULT '[]',
                logs_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_opened_at TEXT,
                size_bytes INTEGER NOT NULL DEFAULT 0,
                progress INTEGER NOT NULL DEFAULT 0,
                current_stage TEXT,
                current_stage_label TEXT,
                stage_started_at REAL,
                eta_seconds INTEGER,
                stages_json TEXT NOT NULL DEFAULT '[]',
                project_id TEXT,
                main_tex TEXT,
                vision_check_enabled INTEGER NOT NULL DEFAULT 0,
                vision_check_mode TEXT NOT NULL DEFAULT 'auto',
                pending_reviews_json TEXT NOT NULL DEFAULT '[]',
                last_compile_warning TEXT,
                translated_tex_path TEXT,
                failure_json TEXT,
                retry_count INTEGER NOT NULL DEFAULT 0,
                latex_recovery_json TEXT,
                deleted_at TEXT
            )
            """
        )
        existing_document_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(documents)").fetchall()
        }
        document_migrations = {
            "failure_json": "TEXT",
            "retry_count": "INTEGER NOT NULL DEFAULT 0",
            "latex_recovery_json": "TEXT",
        }
        for column, declaration in document_migrations.items():
            if column not in existing_document_columns:
                conn.execute(f"ALTER TABLE documents ADD COLUMN {column} {declaration}")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS projects (
                project_id TEXT PRIMARY KEY,
                owner_user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                dir TEXT NOT NULL,
                files_json TEXT NOT NULL DEFAULT '[]',
                main_tex TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                deleted_at TEXT
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_documents_owner ON documents(owner_user_id, updated_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_projects_owner ON projects(owner_user_id, updated_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)"
        )


def init_database() -> None:
    conn = sqlite3.connect(_db_path(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        _initialize_schema(conn)
        rows = conn.execute(
            """
            SELECT document_id, current_stage, retry_count, stages_json
            FROM documents WHERE status IN ('queued', 'processing', 'recovering')
            """
        ).fetchall()
        for row in rows:
            stage = row["current_stage"] or "upload"
            try:
                stages = json.loads(row["stages_json"] or "[]")
            except json.JSONDecodeError:
                stages = []
            for entry in stages:
                if entry.get("status") == "running":
                    entry["status"] = "failed"
            failure = {
                "stage": stage,
                "message": "The application exited before this queued or running stage completed",
                "retryable": True,
                "chunk": None,
                "retry_count": int(row["retry_count"] or 0),
            }
            conn.execute(
                """
                UPDATE documents
                SET status = 'failed', failure_json = ?, stages_json = ?, stage_started_at = NULL
                WHERE document_id = ?
                """,
                (
                    json.dumps(failure, ensure_ascii=False),
                    json.dumps(stages, ensure_ascii=False),
                    row["document_id"],
                ),
            )
        conn.commit()
    finally:
        conn.close()


init_database()
