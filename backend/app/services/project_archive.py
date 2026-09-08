from __future__ import annotations

import io
import os
import re
import shutil
import stat
import tarfile
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Iterable


SUPPORTED_ARCHIVE_SUFFIXES = (".zip", ".tar", ".tar.gz", ".tgz")


class ArchiveImportError(ValueError):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def is_supported_archive_name(filename: str) -> bool:
    lowered = (filename or "").lower()
    return any(lowered.endswith(suffix) for suffix in SUPPORTED_ARCHIVE_SUFFIXES)


def _safe_member_path(name: str) -> Path:
    normalized = (name or "").replace("\\", "/")
    if not normalized or "\x00" in normalized or normalized.startswith("/"):
        raise ArchiveImportError(f"unsafe archive path: {name!r}")
    if re.match(r"^[A-Za-z]:", normalized):
        raise ArchiveImportError(f"unsafe archive path: {name!r}")
    path = PurePosixPath(normalized)
    if path.is_absolute() or any(part == ".." for part in path.parts):
        raise ArchiveImportError(f"unsafe archive path: {name!r}")
    parts = tuple(part for part in path.parts if part not in ("", "."))
    if not parts:
        raise ArchiveImportError(f"invalid archive path: {name!r}")
    if any(re.search(r'[:<>"|?*]', part) or part.endswith((" ", ".")) for part in parts):
        raise ArchiveImportError(f"unsafe archive path: {name!r}")
    return Path(*parts)


def _ignore_metadata(path: Path) -> bool:
    return path.name == ".DS_Store" or "__MACOSX" in path.parts


def _validate_members(
    members: Iterable[tuple[Path, int]],
    project_dir: Path,
    *,
    max_file_bytes: int,
    max_total_bytes: int,
    max_members: int,
) -> list[tuple[Path, int]]:
    accepted: list[tuple[Path, int]] = []
    seen: set[str] = set()
    total = sum(path.stat().st_size for path in project_dir.rglob("*") if path.is_file())

    for relative, size in members:
        if _ignore_metadata(relative):
            continue
        key = relative.as_posix()
        normalized_key = key.casefold()
        if normalized_key in seen:
            raise ArchiveImportError(f"duplicate archive path: {key}")
        for parent in relative.parents:
            if parent == Path("."):
                break
            if parent.as_posix().casefold() in seen:
                raise ArchiveImportError(f"archive path conflicts with a file: {key}")
        prefix = normalized_key + "/"
        if any(existing.startswith(prefix) for existing in seen):
            raise ArchiveImportError(f"archive path conflicts with a directory: {key}")
        seen.add(normalized_key)
        if len(accepted) >= max_members:
            raise ArchiveImportError(
                f"archive contains more than {max_members} files", status_code=413
            )
        if size < 0 or size > max_file_bytes:
            raise ArchiveImportError(
                f"archive member exceeds the {max_file_bytes // (1024 * 1024)}MB limit: {key}",
                status_code=413,
            )
        total += size
        if total > max_total_bytes:
            raise ArchiveImportError("project total size limit exceeded", status_code=413)

        target = project_dir / relative
        if target.exists():
            raise ArchiveImportError(f"project already contains: {key}")
        for parent in relative.parents:
            if parent == Path("."):
                break
            existing_parent = project_dir / parent
            if existing_parent.exists() and not existing_parent.is_dir():
                raise ArchiveImportError(f"project path conflicts with a file: {parent.as_posix()}")
        accepted.append((relative, size))

    if not accepted:
        raise ArchiveImportError("archive does not contain any usable files")
    if not any(path.suffix.lower() == ".tex" for path, _ in accepted):
        raise ArchiveImportError("archive does not contain a .tex file")
    return accepted


def _copy_member(source: BinaryIO, target: Path, expected_size: int, max_file_bytes: int) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with target.open("xb") as output:
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            written += len(chunk)
            if written > max_file_bytes or written > expected_size:
                raise ArchiveImportError("archive member expanded beyond its declared size", status_code=413)
            output.write(chunk)
    if written != expected_size:
        raise ArchiveImportError("archive member size does not match its metadata")


def _commit_staged_files(staging: Path, project_dir: Path, paths: list[Path]) -> None:
    moved: list[Path] = []
    created_dirs: set[Path] = set()
    try:
        for relative in paths:
            source = staging / relative
            target = project_dir / relative
            missing_parents = [
                parent for parent in target.parents if parent != project_dir and not parent.exists()
            ]
            target.parent.mkdir(parents=True, exist_ok=True)
            created_dirs.update(missing_parents)
            os.replace(source, target)
            moved.append(target)
    except Exception:
        for target in reversed(moved):
            target.unlink(missing_ok=True)
        for directory in sorted(created_dirs, key=lambda path: len(path.parts), reverse=True):
            try:
                directory.rmdir()
            except OSError:
                pass
        raise


def _extract_zip(
    content: bytes,
    project_dir: Path,
    staging: Path,
    *,
    max_file_bytes: int,
    max_total_bytes: int,
    max_members: int,
) -> list[Path]:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            raw_members: list[tuple[Path, int, zipfile.ZipInfo]] = []
            infos = archive.infolist()
            if len(infos) > max_members:
                raise ArchiveImportError(
                    f"archive contains more than {max_members} members", status_code=413
                )
            for info in infos:
                directory_name = info.filename.replace("\\", "/").rstrip("/")
                if info.is_dir() and directory_name in ("", "."):
                    continue
                relative = _safe_member_path(info.filename)
                mode = info.external_attr >> 16
                if info.is_dir():
                    continue
                if info.flag_bits & 0x1:
                    raise ArchiveImportError(f"encrypted ZIP members are not supported: {relative}")
                file_type = stat.S_IFMT(mode)
                if file_type == stat.S_IFLNK:
                    raise ArchiveImportError(f"archive links are not allowed: {relative}")
                if file_type and file_type != stat.S_IFREG:
                    raise ArchiveImportError(f"only regular files are allowed: {relative}")
                raw_members.append((relative, info.file_size, info))
            accepted = _validate_members(
                ((path, size) for path, size, _ in raw_members),
                project_dir,
                max_file_bytes=max_file_bytes,
                max_total_bytes=max_total_bytes,
                max_members=max_members,
            )
            accepted_paths = {path for path, _ in accepted}
            for relative, size, info in raw_members:
                if relative not in accepted_paths:
                    continue
                with archive.open(info) as source:
                    _copy_member(source, staging / relative, size, max_file_bytes)
            return [path for path, _ in accepted]
    except ArchiveImportError:
        raise
    except (OSError, RuntimeError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise ArchiveImportError(f"invalid ZIP archive: {exc}") from exc


def _extract_tar(
    content: bytes,
    project_dir: Path,
    staging: Path,
    *,
    max_file_bytes: int,
    max_total_bytes: int,
    max_members: int,
) -> list[Path]:
    try:
        with tarfile.open(fileobj=io.BytesIO(content), mode="r:*") as archive:
            raw_members: list[tuple[Path, int, tarfile.TarInfo]] = []
            for member_index, info in enumerate(archive, start=1):
                if member_index > max_members:
                    raise ArchiveImportError(
                        f"archive contains more than {max_members} members", status_code=413
                    )
                directory_name = info.name.replace("\\", "/").rstrip("/")
                if info.isdir() and directory_name in ("", "."):
                    continue
                relative = _safe_member_path(info.name)
                if info.isdir():
                    continue
                if not info.isreg():
                    raise ArchiveImportError(f"only regular files are allowed: {relative}")
                raw_members.append((relative, info.size, info))
            accepted = _validate_members(
                ((path, size) for path, size, _ in raw_members),
                project_dir,
                max_file_bytes=max_file_bytes,
                max_total_bytes=max_total_bytes,
                max_members=max_members,
            )
            accepted_paths = {path for path, _ in accepted}
            for relative, size, info in raw_members:
                if relative not in accepted_paths:
                    continue
                source = archive.extractfile(info)
                if source is None:
                    raise ArchiveImportError(f"could not read archive member: {relative}")
                with source:
                    _copy_member(source, staging / relative, size, max_file_bytes)
            return [path for path, _ in accepted]
    except ArchiveImportError:
        raise
    except (OSError, tarfile.TarError) as exc:
        raise ArchiveImportError(f"invalid TAR archive: {exc}") from exc


def extract_project_archive(
    content: bytes,
    filename: str,
    project_dir: Path,
    *,
    max_file_bytes: int,
    max_total_bytes: int,
    max_members: int = 2000,
) -> list[Path]:
    if not is_supported_archive_name(filename):
        raise ArchiveImportError("supported archives are .zip, .tar, .tar.gz, and .tgz")
    if len(content) > max_total_bytes:
        raise ArchiveImportError("archive upload exceeds the project size limit", status_code=413)

    lowered = filename.lower()
    is_zip_name = lowered.endswith(".zip")
    is_zip_content = zipfile.is_zipfile(io.BytesIO(content))
    if is_zip_name != is_zip_content:
        raise ArchiveImportError("archive extension does not match its contents")

    project_dir = project_dir.resolve()
    project_dir.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".paperreader-import-", dir=str(project_dir.parent)))
    try:
        extractor = _extract_zip if is_zip_content else _extract_tar
        paths = extractor(
            content,
            project_dir,
            staging,
            max_file_bytes=max_file_bytes,
            max_total_bytes=max_total_bytes,
            max_members=max_members,
        )
        _commit_staged_files(staging, project_dir, paths)
        return paths
    finally:
        shutil.rmtree(staging, ignore_errors=True)
