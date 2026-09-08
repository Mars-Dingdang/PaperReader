from __future__ import annotations

import os
import secrets
import stat
import tempfile
import threading
from pathlib import Path


_LOCK = threading.RLock()
_TRUE_VALUES = {"1", "true", "yes", "on"}


def desktop_app_root() -> Path:
    """Return the per-user, cross-platform PaperReader application directory."""
    override = os.environ.get("PAPERREADER_APP_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / "PaperReader"
    if sys_platform() == "darwin":
        return Path.home() / "Library" / "Application Support" / "PaperReader"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "PaperReader"


def sys_platform() -> str:
    import sys

    return sys.platform


def desktop_config_path() -> Path:
    configured = os.environ.get("PAPERREADER_ENV_FILE", "").strip()
    return Path(configured).expanduser().resolve() if configured else desktop_app_root() / ".config.env"


def read_env_file(path: Path | None = None) -> dict[str, str]:
    target = path or desktop_config_path()
    if not target.is_file():
        return {}
    values: dict[str, str] = {}
    for raw_line in target.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def _encode(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value)
    if any(char.isspace() for char in text) or any(char in text for char in "#='\""):
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return text


def _hide_on_windows(path: Path) -> None:
    if os.name != "nt":
        return
    try:
        import ctypes

        ctypes.windll.kernel32.SetFileAttributesW(str(path), 0x02)
    except Exception:
        pass


def write_env_values(
    updates: dict[str, object],
    *,
    clear: set[str] | None = None,
    path: Path | None = None,
) -> Path:
    """Atomically update the hidden env file while preserving unrelated keys."""
    target = path or desktop_config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        values = read_env_file(target)
        for key in clear or set():
            values.pop(key, None)
        values.update({key: str(value) if not isinstance(value, bool) else _encode(value) for key, value in updates.items()})
        lines = [
            "# PaperReader local configuration. Provider secrets move to the encrypted user database after sign-in.",
            *[f"{key}={_encode(value)}" for key, value in sorted(values.items())],
            "",
        ]
        fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=str(target.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write("\n".join(lines))
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, stat.S_IRUSR | stat.S_IWUSR)
            os.replace(temporary, target)
            os.chmod(target, stat.S_IRUSR | stat.S_IWUSR)
            _hide_on_windows(target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return target


def ensure_desktop_config(path: Path | None = None) -> Path:
    """Create a secure first-run config containing only machine-level settings."""
    target = path or desktop_config_path()
    values = read_env_file(target)
    updates: dict[str, object] = {}
    if not values.get("AUTH_SECRET_KEY"):
        updates["AUTH_SECRET_KEY"] = secrets.token_urlsafe(48)
    if not values.get("DATA_DIR"):
        updates["DATA_DIR"] = str(desktop_app_root() / "data")
    if not values.get("APP_ENV"):
        updates["APP_ENV"] = "desktop"
    if not values.get("PAPERREADER_SETUP_COMPLETE"):
        updates["PAPERREADER_SETUP_COMPLETE"] = "false"
    return write_env_values(updates, path=target) if updates or not target.exists() else target


def setup_status(*, desktop_mode: bool) -> dict[str, object]:
    if not desktop_mode:
        return {"required": False, "desktop": False}
    values = read_env_file()
    completed = values.get("PAPERREADER_SETUP_COMPLETE", "").lower() in _TRUE_VALUES
    # A legacy portable config with an API key is already usable and should be
    # imported at the next successful sign-in instead of blocking on the wizard.
    legacy_ready = bool(values.get("OPENAI_API_KEY"))
    return {
        "required": not (completed or legacy_ready),
        "desktop": True,
        "defaults": {
            "base_url": values.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            "model": values.get("OPENAI_MODEL", "gpt-4o-mini"),
            "pdf_parser": values.get("PDF_PARSER", "local") or "local",
            "mineru_base_url": values.get("MINERU_BASE_URL", "https://mineru.net/api/v4"),
            "mineru_model_version": values.get("MINERU_MODEL_VERSION", "vlm"),
            "mineru_language": values.get("MINERU_LANGUAGE", "en"),
            "mineru_enable_formula": values.get("MINERU_ENABLE_FORMULA", "true").lower() in _TRUE_VALUES,
            "mineru_enable_table": values.get("MINERU_ENABLE_TABLE", "true").lower() in _TRUE_VALUES,
            "mineru_is_ocr": values.get("MINERU_IS_OCR", "false").lower() in _TRUE_VALUES,
            "vision_model": values.get("VISION_MODEL", "GLM-4.5V"),
        },
    }


def save_bootstrap_provider(values: dict[str, object]) -> None:
    write_env_values(
        {
            "OPENAI_API_KEY": values["api_key"],
            "OPENAI_BASE_URL": values["base_url"],
            "OPENAI_MODEL": values["model"],
            "PDF_PARSER": values["pdf_parser"],
            "MINERU_API_KEY": values.get("mineru_api_key", ""),
            "MINERU_BASE_URL": values["mineru_base_url"],
            "MINERU_MODEL_VERSION": values["mineru_model_version"],
            "MINERU_LANGUAGE": values["mineru_language"],
            "MINERU_ENABLE_FORMULA": values["mineru_enable_formula"],
            "MINERU_ENABLE_TABLE": values["mineru_enable_table"],
            "MINERU_IS_OCR": values["mineru_is_ocr"],
            "VISION_MODEL": values["vision_model"],
            "PAPERREADER_SETUP_COMPLETE": "true",
            "PAPERREADER_BOOTSTRAP_PENDING": "true",
        }
    )


def pending_bootstrap_provider() -> dict[str, object] | None:
    values = read_env_file()
    if values.get("PAPERREADER_BOOTSTRAP_PENDING", "").lower() not in _TRUE_VALUES:
        # Legacy configs have no marker but should still migrate once.
        if not values.get("OPENAI_API_KEY"):
            return None
    return {
        "api_key": values.get("OPENAI_API_KEY", ""),
        "base_url": values.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        "model": values.get("OPENAI_MODEL", "gpt-4o-mini"),
        "pdf_parser": values.get("PDF_PARSER", "local") or "local",
        "mineru_api_key": values.get("MINERU_API_KEY", ""),
        "mineru_base_url": values.get("MINERU_BASE_URL", "https://mineru.net/api/v4"),
        "mineru_model_version": values.get("MINERU_MODEL_VERSION", "vlm"),
        "mineru_language": values.get("MINERU_LANGUAGE", "en"),
        "mineru_enable_formula": values.get("MINERU_ENABLE_FORMULA", "true").lower() in _TRUE_VALUES,
        "mineru_enable_table": values.get("MINERU_ENABLE_TABLE", "true").lower() in _TRUE_VALUES,
        "mineru_is_ocr": values.get("MINERU_IS_OCR", "false").lower() in _TRUE_VALUES,
        "vision_model": values.get("VISION_MODEL", "GLM-4.5V"),
    }


def clear_bootstrap_secrets() -> None:
    write_env_values(
        {"PAPERREADER_BOOTSTRAP_PENDING": "false"},
        clear={"OPENAI_API_KEY", "MINERU_API_KEY"},
    )
