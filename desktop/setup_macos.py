from __future__ import annotations

import sys
import json
from pathlib import Path

from setuptools import setup


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.setrecursionlimit(10_000)
VERSION = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))["version"]


def frontend_data_files() -> list[tuple[str, list[str]]]:
    dist = ROOT / "frontend" / "dist"
    grouped: dict[str, list[str]] = {}
    for path in dist.rglob("*"):
        if path.is_file():
            relative_parent = path.parent.relative_to(dist)
            destination = str(Path("frontend_dist") / relative_parent)
            grouped.setdefault(destination, []).append(str(path))
    return sorted(grouped.items())

setup(
    name="PaperReader",
    version=VERSION,
    app=[str(ROOT / "desktop" / "launcher.py")],
    data_files=frontend_data_files(),
    options={
        "py2app": {
            "argv_emulation": False,
            "iconfile": str(ROOT / "desktop" / "assets" / "PaperReader.icns"),
            "arch": "arm64",
            "packages": ["webview", "uvicorn", "h11", "anyio", "charset_normalizer"],
            "includes": ["webview.platforms.cocoa"],
            "excludes": [
                "pypdfium2", "pypdfium2_raw", "numpy", "scipy", "torch",
                "torchaudio", "torchvision", "matplotlib", "pandas", "IPython",
                "ipykernel", "jupyter", "sklearn", "sympy", "tkinter", "PyQt5",
                "PyQt6", "PySide2", "PySide6", "gi", "gtk",
            ],
            "plist": {
                "CFBundleIdentifier": "io.github.mars-dingdang.paperreader",
                "CFBundleName": "PaperReader",
                "CFBundleDisplayName": "PaperReader",
                "CFBundleShortVersionString": VERSION,
                "CFBundleVersion": VERSION,
                "LSMinimumSystemVersion": "13.0",
                "NSHighResolutionCapable": True,
            },
        }
    },
)
