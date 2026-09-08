"""Cross-platform native desktop launcher for PaperReader."""

from __future__ import annotations

import json
import os
import shutil
import sys
import threading
import time
import traceback
import urllib.request
from pathlib import Path


APP_NAME = "PaperReader"
HOST = "127.0.0.1"
PORT = int(os.environ.get("PAPERREADER_PORT", "8000"))


def _bundle_root() -> Path:
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    if getattr(sys, "frozen", False) and sys.platform == "darwin":
        return Path(sys.executable).resolve().parents[1] / "Resources"
    return Path(__file__).resolve().parents[1]


def _executable_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def _app_root() -> Path:
    override = os.environ.get("PAPERREADER_APP_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    configured = os.environ.get("PAPERREADER_ENV_FILE", "").strip()
    if configured:
        return Path(configured).expanduser().resolve().parent
    configured_data = os.environ.get("DATA_DIR", "").strip()
    if configured_data:
        return Path(configured_data).expanduser().resolve().parent
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / APP_NAME


def _prepare_python_path() -> None:
    backend = _bundle_root() / "backend"
    if not backend.is_dir():
        backend = Path(__file__).resolve().parents[1] / "backend"
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))


def _migrate_legacy_install(app_root: Path, config_path: Path) -> None:
    """Copy v2.0 portable state once, leaving the original fully recoverable."""
    if os.environ.get("PAPERREADER_ENV_FILE"):
        return
    portable = _executable_root()
    legacy_config = portable / "config.env"
    legacy_data = portable / "data"
    if not config_path.exists() and legacy_config.is_file():
        config_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(legacy_config, config_path)
    target_data = app_root / "data"
    if legacy_data.is_dir() and not target_data.exists():
        shutil.copytree(legacy_data, target_data)


def _prepare_environment() -> Path:
    _prepare_python_path()
    app_root = _app_root()
    app_root.mkdir(parents=True, exist_ok=True)
    config_path = Path(os.environ.get("PAPERREADER_ENV_FILE") or app_root / ".config.env")
    _migrate_legacy_install(app_root, config_path)

    os.environ.setdefault("PAPERREADER_APP_DIR", str(app_root))
    os.environ.setdefault("PAPERREADER_ENV_FILE", str(config_path))
    from app.core.local_config import ensure_desktop_config, read_env_file

    ensure_desktop_config(config_path)
    values = read_env_file(config_path)
    data_dir = Path(os.environ.get("DATA_DIR") or values.get("DATA_DIR") or app_root / "data")
    if not data_dir.is_absolute():
        data_dir = (app_root / data_dir).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)

    frontend_dir = _bundle_root() / "frontend_dist"
    if not frontend_dir.is_dir():
        frontend_dir = Path(__file__).resolve().parents[1] / "frontend" / "dist"
    os.environ["DATA_DIR"] = str(data_dir)
    os.environ.setdefault("PAPERREADER_FRONTEND_DIR", str(frontend_dir))
    os.environ.setdefault("PAPERREADER_DESKTOP", "1")
    os.environ.setdefault("CORS_ORIGINS", f"http://{HOST}:{PORT}")
    os.environ.setdefault("PYTHONUTF8", "1")
    if sys.platform == "darwin" and "LATEXMK_PATH" not in os.environ:
        mac_latexmk = Path("/Library/TeX/texbin/latexmk")
        if mac_latexmk.is_file():
            os.environ["LATEXMK_PATH"] = str(mac_latexmk)
    return app_root


def _wait_until_ready(url: str, timeout: float = 45.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{url}/health", timeout=1.0) as response:
                if response.status == 200 and json.load(response).get("app") == APP_NAME:
                    return True
        except Exception:
            time.sleep(0.25)
    return False


def _show_error(message: str) -> None:
    if os.environ.get("PAPERREADER_NO_WINDOW") == "1":
        return
    if os.name == "nt":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(0, message, APP_NAME, 0x10)
            return
        except Exception:
            pass
    print(message, file=sys.stderr)


def main() -> None:
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
    app_root = _prepare_environment()

    import uvicorn
    from app.main import app

    url = f"http://{HOST}:{PORT}"
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host=HOST,
            port=PORT,
            log_level="warning",
            loop="asyncio",
            http="h11",
        )
    )
    if os.environ.get("PAPERREADER_NO_WINDOW") == "1":
        server.run()
        return

    backend_thread = threading.Thread(target=server.run, name="paperreader-backend", daemon=True)
    backend_thread.start()
    if not _wait_until_ready(url):
        server.should_exit = True
        raise RuntimeError(f"PaperReader backend did not become ready. Port {PORT} may already be in use.")

    import webview

    webview.settings["ALLOW_DOWNLOADS"] = True
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
    webview.create_window(
        APP_NAME,
        url,
        width=1280,
        height=800,
        min_size=(1024, 700),
        confirm_close=False,
        text_select=True,
    )
    try:
        webview.start(private_mode=False, storage_path=str(app_root / "webview"))
    finally:
        server.should_exit = True
        backend_thread.join(timeout=10)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        try:
            root = _app_root()
            root.mkdir(parents=True, exist_ok=True)
            error_path = root / "PaperReader-error.log"
            error_path.write_text(traceback.format_exc(), encoding="utf-8")
            _show_error(f"PaperReader 启动失败。详细信息已写入：\n{error_path}")
        finally:
            raise
