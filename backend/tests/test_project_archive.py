from __future__ import annotations

import io
import stat
import tarfile
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.project_archive import ArchiveImportError, extract_project_archive


def _zip_bytes(files: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return output.getvalue()


def _tar_bytes(files: dict[str, bytes], *, compressed: bool = False) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz" if compressed else "w") as archive:
        for name, content in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
    return output.getvalue()


@pytest.mark.parametrize(
    ("filename", "content"),
    [
        ("paper.zip", _zip_bytes({"source/main.tex": b"\\documentclass{article}"})),
        ("paper.tar", _tar_bytes({"source/main.tex": b"\\documentclass{article}"})),
        ("paper.tar.gz", _tar_bytes({"source/main.tex": b"\\documentclass{article}"}, compressed=True)),
        ("paper.tgz", _tar_bytes({"source/main.tex": b"\\documentclass{article}"}, compressed=True)),
    ],
    ids=["zip", "tar", "tar-gz", "tgz"],
)
def test_extract_supported_archives(filename: str, content: bytes, tmp_path: Path) -> None:
    project = tmp_path / "project"
    extracted = extract_project_archive(
        content,
        filename,
        project,
        max_file_bytes=1024,
        max_total_bytes=20_000,
    )

    assert extracted == [Path("source/main.tex")]
    assert (project / "source/main.tex").read_bytes() == b"\\documentclass{article}"


@pytest.mark.parametrize(
    ("filename", "content", "message"),
    [
        ("paper.zip", _zip_bytes({"../escape.tex": b"bad"}), "unsafe archive path"),
        ("paper.zip", _zip_bytes({"/absolute.tex": b"bad"}), "unsafe archive path"),
        ("paper.zip", _zip_bytes({"readme.txt": b"no source"}), "does not contain a .tex"),
        ("paper.zip", b"not a zip", "extension does not match"),
        ("paper.tar", _zip_bytes({"main.tex": b"source"}), "extension does not match"),
        ("paper.tgz", b"not a tar", "invalid TAR archive"),
    ],
    ids=["traversal", "absolute", "no-tex", "corrupt-zip", "mismatched-tar", "corrupt-tar"],
)
def test_invalid_archives_are_rejected_atomically(
    filename: str, content: bytes, message: str, tmp_path: Path
) -> None:
    project = tmp_path / "project"
    with pytest.raises(ArchiveImportError, match=message):
        extract_project_archive(
            content,
            filename,
            project,
            max_file_bytes=1024,
            max_total_bytes=4096,
        )
    assert not list(project.rglob("*"))
    assert not (tmp_path / "escape.tex").exists()


def test_archive_rejects_links_limits_and_existing_conflicts(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()

    symlink_zip = io.BytesIO()
    with zipfile.ZipFile(symlink_zip, "w") as archive:
        info = zipfile.ZipInfo("linked.tex")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, "target.tex")
    with pytest.raises(ArchiveImportError, match="links are not allowed"):
        extract_project_archive(
            symlink_zip.getvalue(),
            "linked.zip",
            project,
            max_file_bytes=1024,
            max_total_bytes=4096,
        )

    tar_output = io.BytesIO()
    with tarfile.open(fileobj=tar_output, mode="w") as archive:
        link = tarfile.TarInfo("linked.tex")
        link.type = tarfile.SYMTYPE
        link.linkname = "target.tex"
        archive.addfile(link)
    with pytest.raises(ArchiveImportError, match="only regular files"):
        extract_project_archive(
            tar_output.getvalue(),
            "linked.tar",
            project,
            max_file_bytes=1024,
            max_total_bytes=20_000,
        )

    with pytest.raises(ArchiveImportError, match="exceeds"):
        extract_project_archive(
            _zip_bytes({"main.tex": b"x" * 20}),
            "large.zip",
            project,
            max_file_bytes=10,
            max_total_bytes=1000,
        )
    with pytest.raises(ArchiveImportError, match="total size"):
        extract_project_archive(
            _zip_bytes({"main.tex": b"x" * 10_000, "other.tex": b"y" * 10_000}),
            "total.zip",
            project,
            max_file_bytes=10_000,
            max_total_bytes=15_000,
        )
    with pytest.raises(ArchiveImportError, match="more than 1"):
        extract_project_archive(
            _zip_bytes({"main.tex": b"x", "other.tex": b"y"}),
            "many.zip",
            project,
            max_file_bytes=10,
            max_total_bytes=1000,
            max_members=1,
        )
    with pytest.raises(ArchiveImportError, match="conflicts"):
        extract_project_archive(
            _zip_bytes({"source": b"file", "source/main.tex": b"content"}),
            "conflict.zip",
            project,
            max_file_bytes=1024,
            max_total_bytes=4096,
        )

    (project / "main.tex").write_text("existing", encoding="utf-8")
    with pytest.raises(ArchiveImportError, match="already contains"):
        extract_project_archive(
            _zip_bytes({"main.tex": b"replacement"}),
            "conflict.zip",
            project,
            max_file_bytes=1024,
            max_total_bytes=4096,
        )
    assert (project / "main.tex").read_text(encoding="utf-8") == "existing"


def test_archive_api_imports_and_prioritizes_main_tex(isolated_storage) -> None:
    archive = _zip_bytes(
        {
            "source/appendix.tex": b"Supplemental material",
            "source/paper.tex": b"\\documentclass{article}\\begin{document}Paper\\end{document}",
            "source/notes.txt": b"notes",
        }
    )
    with TestClient(app) as client:
        registered = client.post(
            "/api/auth/register",
            json={"username": "archive-owner", "password": "test-password"},
        )
        assert registered.status_code == 200
        project_id = client.post("/api/project", json={"name": "arxiv-source"}).json()["project_id"]
        response = client.post(
            f"/api/project/{project_id}/archive",
            files={"file": ("source.zip", archive, "application/zip")},
        )

    assert response.status_code == 200, response.text
    detail = response.json()
    assert detail["main_tex"] == "source/paper.tex"
    assert detail["main_candidates"] == ["source/paper.tex", "source/appendix.tex"]
    assert [item["relative_path"] for item in detail["files"]] == [
        "source/appendix.tex",
        "source/notes.txt",
        "source/paper.tex",
    ]
