"""Vision-model adversarial check (Phase D).

Renders pages of the original PDF and asks a multimodal LLM to verify the
extracted/translated markdown matches the page.  Returns a refined markdown
when the model proposes corrections; otherwise the original is preserved.

The check is best-effort: any failure (no API key, model unavailable, JSON
parse error, etc.) is caught upstream and reported in the document logs.
"""
from __future__ import annotations

import base64
import json
import re
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

from openai import OpenAI

from app.core.config import settings

if TYPE_CHECKING:  # avoid circular import at runtime
    from app.models.store import DocumentRecord, ReviewProposal


_REVIEW_EVENTS: dict[str, threading.Event] = {}
_REVIEW_DECISIONS: dict[str, dict] = {}


_SYSTEM_PROMPT = (
    "你是一名学术论文校对助手。给定一页 PDF 截图和对应的 markdown/LaTeX 文本，"
    "对照页面核对：标题层级、段落顺序、公式、表格、图注、引用编号是否正确。"
    "输出严格的 JSON：{\"ok\": bool, \"fixed_markdown\": str, \"issues\": [str]}。"
    "若文本与图片完全一致，ok=true 且 fixed_markdown 原样返回。"
    "若有错误，ok=false，fixed_markdown 给出修正后的全文，issues 罗列问题。"
    " 重要约束：fixed_markdown 中所有希腊字母与数学算子必须使用 LaTeX 命令"
    " (例如 \\\\varepsilon, \\\\leq, \\\\rightarrow, \\\\alpha, \\\\Sigma)，"
    " 禁止直接输出 unicode 字符如 ε / ≤ / → / α / Σ；普通文本中出现这些字符时，"
    " 请改写为行内公式 $...$。"
)


def _render_pdf_pages(pdf_path: Path, max_pages: int) -> list[Path]:
    try:
        import pypdfium2 as pdfium  # type: ignore
    except Exception:
        return []
    try:
        out_dir = pdf_path.parent / "vision_pages"
        out_dir.mkdir(parents=True, exist_ok=True)
        pdf = pdfium.PdfDocument(str(pdf_path))
        page_count = min(len(pdf), max_pages)
        results: list[Path] = []
        for i in range(page_count):
            page = pdf[i]
            pil = page.render(scale=1.5).to_pil()
            target = out_dir / f"page_{i + 1:03d}.png"
            pil.save(target, format="PNG")
            results.append(target)
        return results
    except Exception:
        return []


def _image_to_data_url(path: Path) -> str:
    raw = path.read_bytes()
    encoded = base64.b64encode(raw).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _vision_client() -> OpenAI:
    return OpenAI(
        api_key=settings.openai_api_key or "EMPTY",
        base_url=settings.openai_base_url,
    )


def _parse_json_response(content: str) -> dict | None:
    if not content:
        return None
    # strip ```json fences if present
    stripped = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.MULTILINE)
    try:
        return json.loads(stripped)
    except Exception:
        # try to locate the first {...} block
        match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except Exception:
            return None


def _check_one_page(image_path: Path, markdown: str) -> tuple[bool, str, list[str]]:
    if not settings.openai_api_key:
        return True, markdown, []
    client = _vision_client()
    user_content = [
        {"type": "text", "text": f"以下是 markdown 文本：\n\n{markdown}"},
        {"type": "image_url", "image_url": {"url": _image_to_data_url(image_path)}},
    ]
    try:
        response = client.chat.completions.create(
            model=settings.vision_model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            temperature=0.0,
        )
    except Exception as exc:
        raise RuntimeError(f"vision model call failed: {exc}") from exc

    content = response.choices[0].message.content or ""
    parsed = _parse_json_response(content)
    if not parsed:
        return True, markdown, [f"模型返回无法解析为 JSON：{content[:120]}"]
    ok = bool(parsed.get("ok", True))
    fixed = parsed.get("fixed_markdown") or markdown
    issues = parsed.get("issues") or []
    if not isinstance(issues, list):
        issues = [str(issues)]
    return ok, str(fixed), [str(i) for i in issues]


def run_vision_check_on_markdown(
    record: "DocumentRecord",
    *,
    pdf_path: Path,
    text: str,
    output_dir: Path,
) -> str:
    """Run the visual-vs-text check.

    Returns the (possibly refined) text.  Always safe: if anything goes wrong
    the original ``text`` is returned and a log entry is appended.
    """
    from app.models.store import ReviewProposal  # local import to avoid cycle

    if not text.strip():
        return text
    if not pdf_path.exists():
        record.logs.append("Vision check skipped: original PDF missing")
        return text

    pages = _render_pdf_pages(pdf_path, settings.vision_check_max_pages)
    if not pages:
        record.logs.append("Vision check skipped: pypdfium2 unavailable or render failed")
        return text

    record.logs.append(f"Vision check: {len(pages)} page(s) using {settings.vision_model}")

    # Use the same markdown for every page (segmentation by page is non-trivial
    # without coordinate metadata).  The model is instructed to focus on the
    # parts visible in the current page.
    proposals: list[ReviewProposal] = []
    refined = text
    for idx, page in enumerate(pages):
        try:
            ok, fixed, issues = _check_one_page(page, refined)
        except Exception as exc:
            record.logs.append(f"Vision check page {idx + 1} error: {exc}")
            continue
        if ok and not issues:
            continue
        record.logs.append(
            f"Vision check page {idx + 1}: {len(issues)} issue(s) — {issues[:2]}"
        )
        proposals.append(
            ReviewProposal(
                page_index=idx,
                issues=issues,
                original_md=refined,
                proposed_md=fixed,
                image_url=f"/data/outputs/{record.document_id}/vision_pages/{page.name}",
            )
        )
        if record.vision_check_mode == "auto":
            refined = fixed

    # Persist a small report
    if proposals:
        report = output_dir / "vision_check_report.md"
        try:
            report.write_text(
                "\n\n---\n\n".join(
                    f"### Page {p.page_index + 1}\n\n"
                    + "\n".join(f"- {i}" for i in p.issues)
                    for p in proposals
                ),
                encoding="utf-8",
            )
        except Exception:
            pass

    if record.vision_check_mode == "manual" and proposals:
        record.pending_reviews = proposals
        record.status = "awaiting_review"
        event = threading.Event()
        _REVIEW_EVENTS[record.document_id] = event
        record.logs.append("Awaiting user review of vision-check proposals")
        # Block this worker thread until the user decides (or 30 min timeout)
        triggered = event.wait(timeout=30 * 60)
        decision = _REVIEW_DECISIONS.pop(record.document_id, {})
        _REVIEW_EVENTS.pop(record.document_id, None)
        record.status = "processing"
        record.pending_reviews = []
        if not triggered:
            record.logs.append("Vision review timed out; keeping original text")
            return text
        if decision.get("accept"):
            refined = decision.get("edits") or proposals[-1].proposed_md
            record.logs.append("Vision review: user accepted proposal")
        else:
            record.logs.append("Vision review: user rejected proposal")
            refined = text

    return refined


def submit_review_decision(document_id: str, *, accept: bool, edits: str | None = None) -> bool:
    event = _REVIEW_EVENTS.get(document_id)
    if not event:
        return False
    _REVIEW_DECISIONS[document_id] = {"accept": accept, "edits": edits}
    event.set()
    return True
