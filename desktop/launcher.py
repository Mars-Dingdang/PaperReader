"""Windows desktop launcher for the self-contained PaperReader backend/UI."""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
import webbrowser
from ctypes import wintypes
from pathlib import Path


APP_NAME = "PaperReader"
HOST = "127.0.0.1"
PORT = 8000
_ICON_HANDLES: list[int] = []


def _bundle_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[1]


def _portable_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def _prepare_environment() -> None:
    bundle = _bundle_root()
    portable = _portable_root()
    data_dir = portable / "data"
    frozen = bool(getattr(sys, "frozen", False))
    config_path = portable / ("config.env" if frozen else ".env")
    frontend_dir = bundle / ("frontend_dist" if frozen else "frontend/dist")
    data_dir.mkdir(parents=True, exist_ok=True)

    os.environ.setdefault("DATA_DIR", str(data_dir))
    os.environ.setdefault("PAPERREADER_FRONTEND_DIR", str(frontend_dir))
    os.environ.setdefault("PAPERREADER_ENV_FILE", str(config_path))
    os.environ.setdefault("CORS_ORIGINS", f"http://{HOST}:{PORT}")
    os.environ.setdefault("PYTHONUTF8", "1")

    if frozen and not config_path.exists():
        example = bundle / ".env.example"
        if example.exists():
            config_path.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
        ctypes.windll.user32.MessageBoxW(
            0,
            "首次运行已创建 config.env。\n\n请填写你自己的模型与 MinerU 密钥；"
            "不配置时只能使用不需要密钥的本地解析能力。",
            "PaperReader 首次运行",
            0x40,
        )


def _edge_path() -> Path | None:
    candidates = [
        Path(os.environ.get("PROGRAMFILES(X86)", ""))
        / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("PROGRAMFILES", ""))
        / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("LOCALAPPDATA", ""))
        / "Microsoft/Edge/Application/msedge.exe",
    ]
    return next((path for path in candidates if path.is_file()), None)


def _wait_until_ready(url: str, timeout: float = 45.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{url}/health", timeout=1.0) as response:
                if response.status == 200:
                    return True
        except Exception:
            time.sleep(0.25)
    return False


def _apply_edge_window_icon(process_id: int, timeout: float = 15.0) -> bool:
    """Replace Edge app-mode's generic taskbar icon with PaperReader's icon."""
    if os.name != "nt":
        return False
    icon_path = next(
        (
            path
            for path in (
                _bundle_root() / "PaperReader.ico",
                _portable_root() / "desktop" / "assets" / "PaperReader.ico",
            )
            if path.is_file()
        ),
        None,
    )
    if icon_path is None:
        return False

    user32 = ctypes.windll.user32
    image_icon = 1
    lr_load_from_file = 0x0010
    wm_seticon = 0x0080
    icon_small = 0
    icon_big = 1
    gclp_hicon = -14
    gclp_hiconsm = -34

    user32.LoadImageW.restype = wintypes.HANDLE
    user32.SendMessageW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    large_icon = user32.LoadImageW(
        None, str(icon_path), image_icon, 64, 64, lr_load_from_file
    )
    small_icon = user32.LoadImageW(
        None, str(icon_path), image_icon, 32, 32, lr_load_from_file
    )
    if not large_icon or not small_icon:
        return False
    # Keep the HICON objects alive for the lifetime of the Edge window.
    _ICON_HANDLES.extend([int(large_icon), int(small_icon)])

    enum_callback_type = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
    )

    def apply_to_matching_window(hwnd, _lparam) -> bool:
        window_process_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(window_process_id))
        if window_process_id.value != process_id or not user32.IsWindowVisible(hwnd):
            return True
        user32.SendMessageW(hwnd, wm_seticon, icon_big, large_icon)
        user32.SendMessageW(hwnd, wm_seticon, icon_small, small_icon)
        # Chromium can later ask the registered window class for its icon, so
        # update both the per-window and class-level values.
        set_class_icon = user32.SetClassLongPtrW
        set_class_icon.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
        set_class_icon.restype = ctypes.c_void_p
        set_class_icon(hwnd, gclp_hicon, ctypes.c_void_p(large_icon))
        set_class_icon(hwnd, gclp_hiconsm, ctypes.c_void_p(small_icon))
        apply_to_matching_window.applied = True
        return True

    apply_to_matching_window.applied = False
    callback = enum_callback_type(apply_to_matching_window)
    deadline = time.time() + timeout
    while time.time() < deadline:
        user32.EnumWindows(callback, 0)
        if apply_to_matching_window.applied:
            return True
        time.sleep(0.2)
    return False


def _open_window(server, url: str) -> None:
    if not _wait_until_ready(url):
        ctypes.windll.user32.MessageBoxW(
            0, "PaperReader 服务启动失败，请查看 config.env 后重试。", APP_NAME, 0x10
        )
        server.should_exit = True
        return
    if os.environ.get("PAPERREADER_NO_WINDOW") == "1":
        return
    edge = _edge_path()
    if edge:
        # A normal Edge invocation may immediately hand the app window to an
        # already-running Edge process and exit.  The old launcher interpreted
        # that short-lived hand-off process as "the PaperReader window was
        # closed" and stopped Uvicorn, leaving the visible page at
        # ERR_CONNECTION_REFUSED.  A dedicated profile keeps this app window
        # owned by the process we can reliably wait for.
        edge_profile = Path(os.environ["DATA_DIR"]) / "edge-profile"
        edge_profile.mkdir(parents=True, exist_ok=True)
        process = subprocess.Popen(
            [
                str(edge),
                f"--app={url}",
                "--start-maximized",
                f"--user-data-dir={edge_profile}",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-background-mode",
            ]
        )
        _apply_edge_window_icon(process.pid)
        process.wait()
        server.should_exit = True
    else:
        webbrowser.open(url)


def main() -> None:
    # PyInstaller's windowed bootloader intentionally provides no console
    # streams.  Uvicorn/logging still probes them during setup, so give the
    # desktop process harmless sinks instead of leaving them as None.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
    _prepare_environment()
    if not getattr(sys, "frozen", False):
        backend_dir = _portable_root() / "backend"
        if str(backend_dir) not in sys.path:
            sys.path.insert(0, str(backend_dir))
    # Imports intentionally happen after environment preparation so Pydantic
    # resolves the portable data/config paths before creating settings.
    import uvicorn
    from app.main import app

    url = f"http://{HOST}:{PORT}"
    config = uvicorn.Config(app, host=HOST, port=PORT, log_level="warning")
    server = uvicorn.Server(config)
    opener = threading.Thread(target=_open_window, args=(server, url), daemon=True)
    opener.start()
    server.run()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        error_path = _portable_root() / "PaperReader-error.log"
        error_path.write_text(traceback.format_exc(), encoding="utf-8")
        if os.environ.get("PAPERREADER_NO_WINDOW") != "1":
            ctypes.windll.user32.MessageBoxW(
                0,
                f"PaperReader 启动失败。详细信息已写入：\n{error_path}",
                APP_NAME,
                0x10,
            )
        raise
