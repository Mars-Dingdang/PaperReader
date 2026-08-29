"""MinerU 精准解析 API client.

Replaces the previous local Nougat OCR pipeline. Submits a PDF via the
local-file batch upload flow (apply for signed URL → PUT raw bytes →
poll batch status → download result zip → extract `full.md`).

Public surface mirrors the old `nougat_service` so `document_pipeline`
can keep working unchanged:

    extract_text_from_pdf(pdf_path, output_dir)
        -> (markdown_text, mode_label, list_of_artifact_paths)
    extract_text_from_pdf_text_layer(pdf_path, max_pages=3) -> str
"""

from __future__ import annotations

import json
import re
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import requests

from app.core.config import settings


@dataclass
class MinerUResult:
    """Structured result of a MinerU extraction.

    `markdown` is always populated. `content_blocks` and `images_dir` are
    populated when MinerU returns the v2 structured output (preferred path);
    otherwise the consumer should fall back to markdown rendering.
    """

    markdown: str
    mode_label: str
    extracted_files: list[Path] = field(default_factory=list)
    content_blocks: list[dict] | None = None
    images_dir: Path | None = None


_PDF_LAYER_WHITESPACE_PATTERN = re.compile(r"[ \t]+")


# ---------------------------------------------------------------------------
# pypdf text-layer fallback (used by document_pipeline for leading-page repair)
# ---------------------------------------------------------------------------

def _clean_pdf_layer_text(text: str) -> str:
    lines = [_PDF_LAYER_WHITESPACE_PATTERN.sub(" ", line).strip() for line in text.splitlines()]
    kept = [line for line in lines if line]
    return "\n".join(kept).strip()


def extract_text_from_pdf_text_layer(pdf_path: str, max_pages: int = 3) -> str:
    try:
        from pypdf import PdfReader
    except Exception:
        return ""

    reader = PdfReader(pdf_path)
    pages = reader.pages[: max(max_pages, 1)]
    extracted_pages: list[str] = []

    for page in pages:
        try:
            page_text = page.extract_text() or ""
        except Exception:
            page_text = ""
        cleaned = _clean_pdf_layer_text(page_text)
        if cleaned:
            extracted_pages.append(cleaned)

    return "\n\n".join(extracted_pages).strip()


# ---------------------------------------------------------------------------
# MinerU client
# ---------------------------------------------------------------------------

def _auth_headers() -> dict[str, str]:
    if not settings.mineru_api_key:
        raise RuntimeError(
            "MINERU_API_KEY is not configured. Set it in your .env to enable PDF parsing via MinerU."
        )
    return {
        "Authorization": f"Bearer {settings.mineru_api_key}",
        "Accept": "*/*",
    }


def _check_mineru_response(resp: requests.Response, action: str) -> dict:
    if resp.status_code != 200:
        raise RuntimeError(f"MinerU {action} HTTP {resp.status_code}: {resp.text[:300]}")
    try:
        payload = resp.json()
    except ValueError as exc:
        raise RuntimeError(f"MinerU {action} returned non-JSON body: {resp.text[:300]}") from exc
    if payload.get("code") != 0:
        raise RuntimeError(
            f"MinerU {action} failed (code={payload.get('code')}): {payload.get('msg', '')}"
        )
    return payload


def _request_upload_url(file_name: str) -> tuple[str, str]:
    """Apply for a signed OSS upload URL. Returns (batch_id, upload_url)."""
    url = f"{settings.mineru_base_url.rstrip('/')}/file-urls/batch"
    body = {
        "files": [{"name": file_name}],
        "model_version": settings.mineru_model_version,
        "language": settings.mineru_language,
        "enable_formula": settings.mineru_enable_formula,
        "enable_table": settings.mineru_enable_table,
        "is_ocr": settings.mineru_is_ocr,
    }
    headers = {**_auth_headers(), "Content-Type": "application/json"}
    resp = requests.post(url, json=body, headers=headers, timeout=60)
    payload = _check_mineru_response(resp, "apply upload URL")
    data = payload.get("data") or {}
    batch_id = data.get("batch_id")
    file_urls = data.get("file_urls") or []
    if not batch_id or not file_urls:
        raise RuntimeError(f"MinerU apply upload URL: missing batch_id/file_urls in {data}")
    return batch_id, file_urls[0]


def _upload_file(upload_url: str, pdf_path: str) -> None:
    with open(pdf_path, "rb") as fp:
        resp = requests.put(upload_url, data=fp, timeout=300)
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"MinerU OSS upload failed: HTTP {resp.status_code}: {resp.text[:300]}")


def _poll_batch(batch_id: str, log_sink: list[str] | None = None) -> str:
    """Poll until the (single) extract result is done. Returns full_zip_url."""
    url = f"{settings.mineru_base_url.rstrip('/')}/extract-results/batch/{batch_id}"
    headers = _auth_headers()
    interval = max(1.0, float(settings.mineru_poll_interval))
    deadline = time.time() + max(30.0, float(settings.mineru_timeout))
    last_state = ""

    while time.time() < deadline:
        resp = requests.get(url, headers=headers, timeout=30)
        payload = _check_mineru_response(resp, "poll batch")
        results = ((payload.get("data") or {}).get("extract_result")) or []
        if not results:
            time.sleep(interval)
            continue
        result = results[0]
        state = result.get("state", "")
        if state != last_state:
            last_state = state
            if log_sink is not None:
                log_sink.append(f"MinerU state: {state}")
        if state == "done":
            zip_url = result.get("full_zip_url")
            if not zip_url:
                raise RuntimeError(f"MinerU done but full_zip_url missing: {result}")
            return zip_url
        if state == "failed":
            raise RuntimeError(f"MinerU parsing failed: {result.get('err_msg', 'unknown')}")
        time.sleep(interval)

    raise RuntimeError(f"MinerU polling timed out after {settings.mineru_timeout}s (last state: {last_state})")


def _download_and_extract_zip(zip_url: str, output_dir: Path) -> tuple[str, list[Path]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    zip_path = output_dir / "mineru_result.zip"
    with requests.get(zip_url, stream=True, timeout=300) as resp:
        if resp.status_code != 200:
            raise RuntimeError(f"MinerU zip download HTTP {resp.status_code}")
        with open(zip_path, "wb") as fp:
            for chunk in resp.iter_content(chunk_size=64 * 1024):
                if chunk:
                    fp.write(chunk)

    extracted: list[Path] = [zip_path]
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(output_dir)
        for name in zf.namelist():
            target = output_dir / name
            if target.is_file():
                extracted.append(target)

    md_candidates = list(output_dir.rglob("full.md")) or list(output_dir.rglob("*.md"))
    if not md_candidates:
        raise RuntimeError(f"MinerU zip did not contain a markdown file under {output_dir}")
    md_candidates.sort(key=lambda p: (0 if p.name == "full.md" else 1, len(p.parts)))
    md_text = md_candidates[0].read_text(encoding="utf-8", errors="ignore").strip()
    if not md_text:
        raise RuntimeError(f"MinerU markdown file is empty: {md_candidates[0]}")
    return md_text, extracted


def extract_text_from_pdf(
    pdf_path: str,
    output_dir: Path,
    log_sink: list[str] | None = None,
) -> tuple[str, str, list[Path]]:
    """Submit `pdf_path` to MinerU and return (markdown_text, mode_label, artifacts).

    `output_dir` will receive `mineru_result.zip` plus the unpacked contents
    (including `full.md` and any image assets). The shape of the return tuple
    matches the legacy `nougat_service.extract_text_from_pdf` so the rest of
    the pipeline does not need to change.
    """
    file_name = Path(pdf_path).name
    batch_id, upload_url = _request_upload_url(file_name)
    if log_sink is not None:
        log_sink.append(f"MinerU batch_id: {batch_id}")
    _upload_file(upload_url, pdf_path)
    if log_sink is not None:
        log_sink.append("MinerU upload complete; polling for result")
    zip_url = _poll_batch(batch_id, log_sink=log_sink)
    md_text, extracted = _download_and_extract_zip(zip_url, output_dir)
    mode_label = f"mineru:{settings.mineru_model_version}"
    return md_text, mode_label, extracted


def extract_structured_from_pdf(
    pdf_path: str,
    output_dir: Path,
    log_sink: list[str] | None = None,
) -> MinerUResult:
    """Same as `extract_text_from_pdf` but also surfaces structured artifacts.

    Looks for `content_list_v2.json` (preferred) and an `images/` directory
    inside the unpacked zip. Both are optional — when missing the caller
    should fall back to the markdown-only path.
    """
    md_text, mode_label, extracted = extract_text_from_pdf(
        pdf_path, output_dir, log_sink=log_sink
    )

    content_blocks: list[dict] | None = None
    json_candidates = list(output_dir.rglob("content_list_v2.json"))
    if json_candidates:
        json_candidates.sort(key=lambda p: len(p.parts))
        try:
            content_blocks = json.loads(
                json_candidates[0].read_text(encoding="utf-8", errors="ignore")
            )
            if not isinstance(content_blocks, list):
                content_blocks = None
        except (ValueError, OSError):
            content_blocks = None

    images_dir: Path | None = None
    image_candidates = [p for p in output_dir.rglob("images") if p.is_dir()]
    if image_candidates:
        image_candidates.sort(key=lambda p: len(p.parts))
        images_dir = image_candidates[0]

    return MinerUResult(
        markdown=md_text,
        mode_label=mode_label,
        extracted_files=extracted,
        content_blocks=content_blocks,
        images_dir=images_dir,
    )
