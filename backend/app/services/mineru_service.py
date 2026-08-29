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
import shutil
import subprocess
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

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
    two_column: bool = False


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
# Local structured extraction (no MinerU / cloud dependency)
# ---------------------------------------------------------------------------

# Section-heading heuristics for text extracted from a PDF text layer.
_HEADING_NUMBERED_PATTERN = re.compile(r"^\d+(?:\.\d+)*\s+[A-Z0-9]")
_HEADING_KEYWORDS = {
    "abstract", "introduction", "related work", "related works", "background",
    "method", "methods", "methodology", "approach", "experiment", "experiments",
    "experimental setup", "results", "evaluation", "discussion", "conclusion",
    "conclusions", "future work", "references", "acknowledgments",
    "acknowledgements", "appendix", "limitations", "overview",
}


def _is_heading_line(line: str) -> bool:
    s = line.strip()
    if not s or len(s) > 90:
        return False
    if _HEADING_NUMBERED_PATTERN.match(s):
        return True
    if s.lower() in _HEADING_KEYWORDS:
        return True
    if s.isupper() and len(s) > 3:
        return True
    return False


def _title_block(text: str, level: int) -> dict:
    return {
        "type": "title",
        "content": {"title_content": [{"type": "text", "content": text}], "level": level},
    }


def _paragraph_block(lines: list[str]) -> dict:
    return {
        "type": "paragraph",
        "content": {"paragraph_content": [{"type": "text", "content": " ".join(lines)}]},
    }


def _page_text_blocks(text: str, first_page: bool) -> tuple[list[dict], str, str]:
    """Split a page's text into IR-style title/paragraph block dicts.

    Returns (blocks, remaining_text, title). On the first page the first short
    non-heading line is treated as the paper title (level 1) and removed from
    `remaining_text`; other headings become level-2 title blocks.
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    blocks: list[dict] = []
    title = ""
    if first_page and lines and len(lines[0]) <= 120 and not _is_heading_line(lines[0]):
        title = lines[0]
        blocks.append(_title_block(title, 1))
        lines = lines[1:]

    current: list[str] = []
    for line in lines:
        if _is_heading_line(line):
            if current:
                blocks.append(_paragraph_block(current))
                current = []
            blocks.append(_title_block(line, 2))
        else:
            current.append(line)
    if current:
        blocks.append(_paragraph_block(current))

    return blocks, "\n".join(lines), title


def _extract_page_images(page, page_index: int, images_dir: Path) -> list[dict]:
    """Save embedded raster images from a page and return IR image blocks."""
    images_dir.mkdir(parents=True, exist_ok=True)
    blocks: list[dict] = []
    try:
        images = page.images
    except Exception:
        return blocks
    saved = 0
    for img in images:
        if saved >= 12:  # safety cap per page
            break
        try:
            pil = img.image
            w, h = pil.size
            if w < 40 or h < 40:  # skip tiny logos / icons
                continue
            name = f"page_{page_index + 1:03d}_img_{saved:02d}.png"
            target = images_dir / name
            pil.convert("RGB").save(target, format="PNG")
            blocks.append({
                "type": "image",
                "content": {"image_source": {"path": f"images/{name}"}, "image_caption": []},
            })
            saved += 1
        except Exception:
            continue
    return blocks


def _extract_with_pypdfium2(pdf_path: str) -> str:
    try:
        import pypdfium2 as pdfium
    except Exception:
        return ""
    try:
        pdf = pdfium.PdfDocument(pdf_path)
        pages: list[str] = []
        for page in pdf:
            textpage = page.get_textpage()
            try:
                page_text = textpage.get_text_range()
            finally:
                textpage.close()
            cleaned = _clean_pdf_layer_text(page_text)
            if cleaned:
                pages.append(cleaned)
        return "\n\n".join(pages).strip()
    except Exception:
        return ""


def extract_structured_from_pdf_local(
    pdf_path: str,
    output_dir: Path,
    log_sink: list[str] | None = None,
) -> MinerUResult:
    """Extract a PDF's embedded text layer + raster images locally (no cloud).

    Produces MinerU-compatible `content_blocks` (list of pages) and an
    `images/` dir so the existing IR -> translation -> LaTeX pipeline runs
    unchanged. Falls back to pypdfium2 for text if pypdf yields nothing, and
    degrades to `content_blocks=None` when there is no extractable text at all.
    """
    if log_sink is not None:
        log_sink.append("Local PDF parse: reading text layer + images")

    output_dir.mkdir(parents=True, exist_ok=True)
    images_dir = output_dir / "images"

    try:
        from pypdf import PdfReader
    except Exception:
        raise RuntimeError("pypdf is required for local PDF parsing (pip install pypdf)")

    try:
        reader = PdfReader(pdf_path)
    except Exception as exc:
        raise RuntimeError(f"Could not open PDF for local parsing: {exc}") from exc

    content_blocks: list[list[dict]] = []
    markdown_parts: list[str] = []
    images_saved = False

    for page_index, page in enumerate(reader.pages):
        try:
            raw = page.extract_text() or ""
        except Exception:
            raw = ""
        cleaned = _clean_pdf_layer_text(raw)

        blocks, remaining, title = _page_text_blocks(cleaned, first_page=(page_index == 0))
        image_blocks = _extract_page_images(page, page_index, images_dir)
        if image_blocks:
            images_saved = True

        if title:
            markdown_parts.append(f"# {title}")
            if remaining.strip():
                markdown_parts.append(remaining)
        elif cleaned.strip():
            markdown_parts.append(cleaned)

        page_blocks = blocks + image_blocks
        if page_blocks:
            content_blocks.append(page_blocks)

    markdown = "\n\n".join(markdown_parts).strip()

    # Graceful text-only fallback via pypdfium2 when pypdf found no text.
    if not markdown:
        markdown = _extract_with_pypdfium2(pdf_path)
        if markdown:
            content_blocks = []

    extracted_files: list[Path] = []
    if markdown:
        md_path = output_dir / "extracted.md"
        md_path.write_text(markdown, encoding="utf-8", errors="ignore")
        extracted_files.append(md_path)

    return MinerUResult(
        markdown=markdown,
        mode_label="local:text-layer",
        extracted_files=extracted_files,
        content_blocks=content_blocks if content_blocks else None,
        images_dir=images_dir if images_saved else None,
    )


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


def _poll_batch(
    batch_id: str,
    log_sink: list[str] | None = None,
    progress_cb: Callable[[float, str], None] | None = None,
) -> str:
    """Poll until the (single) extract result is done. Returns full_zip_url."""
    url = f"{settings.mineru_base_url.rstrip('/')}/extract-results/batch/{batch_id}"
    headers = _auth_headers()
    interval = max(1.0, float(settings.mineru_poll_interval))
    deadline = time.time() + max(30.0, float(settings.mineru_timeout))
    last_state = ""

    # Map MinerU's coarse states onto sub-stage fractions so the progress bar
    # keeps moving during the (often tens of seconds) cloud extraction.
    _STATE_PROGRESS = {
        "waiting-file": (0.55, "MinerU 接收文件"),
        "running": (0.75, "MinerU 解析中"),
        "done": (0.95, "MinerU 解析完成"),
    }

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
            if progress_cb is not None and state in _STATE_PROGRESS:
                frac, label = _STATE_PROGRESS[state]
                progress_cb(frac, label)
        if state == "done":
            zip_url = result.get("full_zip_url")
            if not zip_url:
                raise RuntimeError(f"MinerU done but full_zip_url missing: {result}")
            return zip_url
        if state == "failed":
            raise RuntimeError(f"MinerU parsing failed: {result.get('err_msg', 'unknown')}")
        time.sleep(interval)

    raise RuntimeError(f"MinerU polling timed out after {settings.mineru_timeout}s (last state: {last_state})")


def _download_and_extract_zip(
    zip_url: str,
    output_dir: Path,
    log_sink: list[str] | None = None,
    max_attempts: int = 4,
) -> tuple[str, list[Path]]:
    """Download and unpack MinerU's result with retries for flaky CDN/TLS links.

    The MinerU control-plane request may succeed while its CDN closes a large
    ZIP transfer early (commonly ``SSL UNEXPECTED_EOF``). A partial archive is
    never accepted: each retry overwrites it and must pass ZipFile validation
    before extraction.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    zip_path = output_dir / "mineru_result.zip"
    attempts = max(1, int(max_attempts))
    extracted: list[Path] = []
    last_error: Exception | None = None

    def extract_downloaded_archive() -> list[Path]:
        current_extracted: list[Path] = [zip_path]
        with zipfile.ZipFile(zip_path) as zf:
            bad_member = zf.testzip()
            if bad_member:
                raise zipfile.BadZipFile(f"CRC check failed for {bad_member}")
            zf.extractall(output_dir)
            for name in zf.namelist():
                target = output_dir / name
                if target.is_file():
                    current_extracted.append(target)
        return current_extracted

    for attempt in range(attempts):
        try:
            with requests.get(zip_url, stream=True, timeout=(30, 300)) as resp:
                if resp.status_code != 200:
                    detail = f"MinerU zip download HTTP {resp.status_code}"
                    if resp.status_code not in (408, 425, 429) and resp.status_code < 500:
                        raise RuntimeError(detail)
                    raise requests.HTTPError(detail, response=resp)
                with open(zip_path, "wb") as fp:
                    for chunk in resp.iter_content(chunk_size=64 * 1024):
                        if chunk:
                            fp.write(chunk)

            extracted = extract_downloaded_archive()
            break
        except (requests.RequestException, OSError, zipfile.BadZipFile) as exc:
            last_error = exc
            if attempt >= attempts - 1:
                break
            delay = min(8.0, 1.5 * (2**attempt))
            if log_sink is not None:
                log_sink.append(
                    f"MinerU result download interrupted; retry {attempt + 2}/{attempts} "
                    f"in {delay:.1f}s: {exc}"
                )
            time.sleep(delay)

    # Some Windows Python/OpenSSL builds repeatedly fail against MinerU's CDN
    # with SSL UNEXPECTED_EOF while the native Schannel-based curl succeeds.
    # Use curl as a transport fallback, still validating the resulting ZIP.
    if not extracted and zip_url.lower().startswith("https://"):
        curl_path = shutil.which("curl")
        if curl_path:
            if log_sink is not None:
                log_sink.append("Python TLS download failed; retrying MinerU result with curl")
            completed = subprocess.run(
                [
                    curl_path,
                    "--fail",
                    "--location",
                    "--silent",
                    "--show-error",
                    "--retry",
                    "3",
                    "--retry-all-errors",
                    "--connect-timeout",
                    "30",
                    "--max-time",
                    "600",
                    "--output",
                    str(zip_path),
                    zip_url,
                ],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if completed.returncode == 0:
                try:
                    extracted = extract_downloaded_archive()
                except (OSError, zipfile.BadZipFile) as exc:
                    last_error = exc
            else:
                detail = (completed.stderr or completed.stdout or "").strip()
                last_error = RuntimeError(
                    f"curl exited with {completed.returncode}: {detail[-300:]}"
                )

    if not extracted:
        raise RuntimeError(
            f"MinerU result download failed after {attempts} attempts: {last_error}"
        ) from last_error

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
    progress_cb: Callable[[float, str], None] | None = None,
) -> tuple[str, str, list[Path]]:
    """Submit `pdf_path` to MinerU and return (markdown_text, mode_label, artifacts).

    `output_dir` will receive `mineru_result.zip` plus the unpacked contents
    (including `full.md` and any image assets). The shape of the return tuple
    matches the legacy `nougat_service.extract_text_from_pdf` so the rest of
    the pipeline does not need to change.

    `progress_cb(fraction, label)` is called at key milestones (0.0..1.0 of the
    parse stage) so the UI can show progress during the slow upload/poll phases.
    """
    file_name = Path(pdf_path).name
    batch_id, upload_url = _request_upload_url(file_name)
    if log_sink is not None:
        log_sink.append(f"MinerU batch_id: {batch_id}")
    if progress_cb is not None:
        progress_cb(0.05, "提交解析任务")
    _upload_file(upload_url, pdf_path)
    if log_sink is not None:
        log_sink.append("MinerU upload complete; polling for result")
    if progress_cb is not None:
        progress_cb(0.5, "文件上传完成，等待解析")
    zip_url = _poll_batch(batch_id, log_sink=log_sink, progress_cb=progress_cb)
    md_text, extracted = _download_and_extract_zip(zip_url, output_dir, log_sink=log_sink)
    mode_label = f"mineru:{settings.mineru_model_version}"
    return md_text, mode_label, extracted


def _detect_two_column(content_blocks: list[dict] | None) -> bool:
    """Heuristically detect a two-column layout from block bounding boxes.

    MinerU normalises each page to a fixed coordinate width. A two-column paper
    has many *text* blocks starting on the right half of the page, while a
    single-column paper keeps every text block on the left half (full-width
    figures and tables are ignored — they can straddle the centre line).
    """
    if not content_blocks:
        return False

    _TEXT_BLOCK_TYPES = ("paragraph", "title", "equation_interline")
    text_x0: list[float] = []
    max_x1 = 0.0

    for page in content_blocks:
        blocks = page if isinstance(page, list) else [page]
        for block in blocks:
            if not isinstance(block, dict):
                continue
            if block.get("type") not in _TEXT_BLOCK_TYPES:
                continue
            bbox = block.get("bbox")
            if not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
                continue
            try:
                x0, x1 = float(bbox[0]), float(bbox[2])
            except (TypeError, ValueError):
                continue
            if x1 - x0 < 60:  # ignore tiny fragments (superscripts, page numbers)
                continue
            text_x0.append(x0)
            max_x1 = max(max_x1, x1)

    if len(text_x0) < 6 or max_x1 <= 0:
        return False

    mid = max_x1 / 2.0
    right = sum(1 for x0 in text_x0 if x0 >= mid)
    # Two columns iff a meaningful share of text blocks start on the right half
    # (>=3 blocks and >=15%), so a lone right-aligned heading/header can't
    # flip a single-column paper into two columns.
    return right >= 3 and right >= 0.15 * len(text_x0)


def extract_structured_from_pdf(
    pdf_path: str,
    output_dir: Path,
    log_sink: list[str] | None = None,
    progress_cb: Callable[[float, str], None] | None = None,
) -> MinerUResult:
    """Same as `extract_text_from_pdf` but also surfaces structured artifacts.

    Looks for `content_list_v2.json` (preferred) and an `images/` directory
    inside the unpacked zip. Both are optional — when missing the caller
    should fall back to the markdown-only path.
    """
    md_text, mode_label, extracted = extract_text_from_pdf(
        pdf_path, output_dir, log_sink=log_sink, progress_cb=progress_cb
    )

    content_blocks: list[dict] | None = None
    # MinerU names the structured files with a batch-uuid prefix, e.g.
    # `{uuid}_content_list_v2.json`, so match on the suffix.
    json_candidates = list(output_dir.rglob("*content_list_v2.json"))
    if not json_candidates:
        json_candidates = list(output_dir.rglob("*content_list.json"))
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

    two_column = _detect_two_column(content_blocks)

    return MinerUResult(
        markdown=md_text,
        mode_label=mode_label,
        extracted_files=extracted,
        content_blocks=content_blocks,
        images_dir=images_dir,
        two_column=two_column,
    )
