from __future__ import annotations

import re
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app.core.config import settings
from app.models.schemas import UploadResponse
from app.models.store import (
    DOCUMENTS,
    DocumentRecord,
    PROJECTS,
    ProjectFile,
    ProjectRecord,
)
from app.services.document_pipeline import process_document


router = APIRouter()


_ALLOWED_EXT = {
    ".tex", ".bib", ".cls", ".sty", ".bst", ".bbl",
    ".png", ".jpg", ".jpeg", ".pdf", ".eps", ".svg", ".gif",
    ".csv", ".tsv", ".txt", ".md",
}
_DOCCLASS_RE = re.compile(r"\\documentclass")


def _projects_root() -> Path:
    root = settings.upload_dir / "projects"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_relative(rel: str) -> Path:
    """Sanitize a user-provided relative path; reject path traversal."""
    rel = (rel or "").replace("\\", "/").lstrip("/")
    if not rel:
        raise HTTPException(status_code=400, detail="empty relative path")
    parts = []
    for piece in rel.split("/"):
        if not piece or piece == ".":
            continue
        if piece == "..":
            raise HTTPException(status_code=400, detail="path traversal not allowed")
        parts.append(piece)
    if not parts:
        raise HTTPException(status_code=400, detail="invalid relative path")
    return Path(*parts)


def _classify(p: Path) -> str:
    suffix = p.suffix.lower()
    if suffix == ".tex":
        return "tex"
    if suffix == ".bib":
        return "bib"
    if suffix in {".cls", ".sty", ".bst", ".bbl"}:
        return "style"
    if suffix in {".png", ".jpg", ".jpeg", ".gif", ".svg", ".eps", ".pdf"}:
        return "asset"
    return "other"


def _refresh_project(project: ProjectRecord) -> None:
    files: list[ProjectFile] = []
    main_candidates: list[str] = []
    for path in project.dir.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(project.dir).as_posix()
        size = path.stat().st_size
        files.append(ProjectFile(relative_path=rel, size=size, kind=_classify(path)))
        if path.suffix.lower() == ".tex":
            try:
                head = path.read_text(encoding="utf-8", errors="ignore")[:2000]
            except Exception:
                head = ""
            if _DOCCLASS_RE.search(head):
                main_candidates.append(rel)
    files.sort(key=lambda f: f.relative_path)
    project.files = files
    if project.main_tex not in {f.relative_path for f in files}:
        project.main_tex = main_candidates[0] if main_candidates else None


class CreateProjectRequest(BaseModel):
    name: str | None = None


class CreateProjectResponse(BaseModel):
    project_id: str
    name: str


class ProjectFileItem(BaseModel):
    relative_path: str
    size: int
    kind: str


class ProjectDetail(BaseModel):
    project_id: str
    name: str
    main_tex: str | None
    files: list[ProjectFileItem]
    main_candidates: list[str]


class BuildProjectRequest(BaseModel):
    main_tex: str
    vision_check_enabled: bool = True
    vision_check_mode: str = "auto"


@router.post("/project", response_model=CreateProjectResponse)
def create_project(req: CreateProjectRequest | None = None) -> CreateProjectResponse:
    project_id = str(uuid.uuid4())
    name = (req.name if req else None) or f"project-{project_id[:8]}"
    pdir = _projects_root() / project_id
    pdir.mkdir(parents=True, exist_ok=True)
    project = ProjectRecord(project_id=project_id, name=name, dir=pdir)
    PROJECTS[project_id] = project
    return CreateProjectResponse(project_id=project_id, name=name)


@router.get("/project/{project_id}", response_model=ProjectDetail)
def get_project(project_id: str) -> ProjectDetail:
    project = PROJECTS.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    _refresh_project(project)
    main_candidates = [f.relative_path for f in project.files if f.kind == "tex"]
    return ProjectDetail(
        project_id=project.project_id,
        name=project.name,
        main_tex=project.main_tex,
        files=[ProjectFileItem(**f.__dict__) for f in project.files],
        main_candidates=main_candidates,
    )


@router.post("/project/{project_id}/files", response_model=ProjectDetail)
async def upload_project_file(
    project_id: str,
    file: UploadFile = File(...),
    relative_path: str = Form(""),
) -> ProjectDetail:
    project = PROJECTS.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    rel_path_str = relative_path or (file.filename or "")
    rel = _safe_relative(rel_path_str)
    if rel.suffix.lower() not in _ALLOWED_EXT:
        raise HTTPException(status_code=400, detail=f"unsupported file type: {rel.suffix}")

    content = await file.read()
    max_bytes = settings.project_max_file_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(status_code=413, detail=f"file exceeds {settings.project_max_file_mb}MB")

    # check total
    existing_total = sum(f.size for f in project.files)
    if existing_total + len(content) > settings.project_max_total_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail="project total size limit exceeded")

    target = project.dir / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)

    _refresh_project(project)
    main_candidates = [f.relative_path for f in project.files if f.kind == "tex"]
    return ProjectDetail(
        project_id=project.project_id,
        name=project.name,
        main_tex=project.main_tex,
        files=[ProjectFileItem(**f.__dict__) for f in project.files],
        main_candidates=main_candidates,
    )


class DeleteFilesRequest(BaseModel):
    relative_paths: list[str]


@router.post("/project/{project_id}/delete-files", response_model=ProjectDetail)
def delete_files(project_id: str, req: DeleteFilesRequest) -> ProjectDetail:
    project = PROJECTS.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    for rel in req.relative_paths:
        try:
            target = project.dir / _safe_relative(rel)
        except HTTPException:
            continue
        if target.is_file() and target.resolve().is_relative_to(project.dir.resolve()):
            target.unlink(missing_ok=True)
    _refresh_project(project)
    return ProjectDetail(
        project_id=project.project_id,
        name=project.name,
        main_tex=project.main_tex,
        files=[ProjectFileItem(**f.__dict__) for f in project.files],
        main_candidates=[f.relative_path for f in project.files if f.kind == "tex"],
    )


def _run_pipeline(record_id: str) -> None:
    record = DOCUMENTS.get(record_id)
    if record:
        process_document(record)


@router.post("/project/{project_id}/build", response_model=UploadResponse)
def build_project(
    project_id: str,
    req: BuildProjectRequest,
    background_tasks: BackgroundTasks,
) -> UploadResponse:
    project = PROJECTS.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    main_rel = _safe_relative(req.main_tex)
    main_path = project.dir / main_rel
    if not main_path.is_file() or main_path.suffix.lower() != ".tex":
        raise HTTPException(status_code=400, detail="main_tex must be an existing .tex file")
    project.main_tex = main_rel.as_posix()

    document_id = str(uuid.uuid4())
    record = DocumentRecord(
        document_id=document_id,
        source_type="tex_project",
        source_path=main_path,
        source_filename=main_path.name,
        project_id=project.project_id,
        main_tex=project.main_tex,
    )
    record.vision_check_enabled = bool(req.vision_check_enabled)
    record.vision_check_mode = req.vision_check_mode if req.vision_check_mode in ("auto", "manual") else "auto"
    DOCUMENTS[document_id] = record

    background_tasks.add_task(_run_pipeline, document_id)
    return UploadResponse(document_id=document_id, status=record.status)


@router.delete("/project/{project_id}")
def delete_project(project_id: str) -> dict:
    project = PROJECTS.pop(project_id, None)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    shutil.rmtree(project.dir, ignore_errors=True)
    return {"ok": True}
