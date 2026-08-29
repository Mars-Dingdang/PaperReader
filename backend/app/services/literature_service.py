"""Retrieval helpers for uploaded-paper-first literature conversations."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import requests

from app.models.store import DocumentRecord


logger = logging.getLogger(__name__)


@dataclass
class RetrievedSource:
    label: str
    title: str
    content: str
    url: str | None = None
    source_type: str = "uploaded"
    year: int | None = None


_WORD_RE = re.compile(r"[A-Za-z0-9_]{2,}|[\u4e00-\u9fff]")


def _tokens(text: str) -> set[str]:
    return {token.lower() for token in _WORD_RE.findall(text)}


def _blocks(text: str) -> list[str]:
    parts = re.split(r"\n\s*\n+", text or "")
    return [" ".join(part.split()) for part in parts if len(part.strip()) >= 20]


def _rank_blocks(text: str, question: str, limit: int = 3) -> list[str]:
    blocks = _blocks(text)
    if not blocks:
        return []
    query_tokens = _tokens(question)
    ranked: list[tuple[float, int, str]] = []
    for index, block in enumerate(blocks):
        block_tokens = _tokens(block)
        overlap = len(query_tokens & block_tokens)
        density = overlap / max(1, len(query_tokens))
        heading_bonus = 0.25 if block.startswith(("#", "摘要", "Abstract")) else 0.0
        ranked.append((overlap + density + heading_bonus, -index, block))
    ranked.sort(reverse=True)
    selected = [block for _, _, block in ranked[:limit]]
    if blocks[0] not in selected:
        selected.insert(0, blocks[0])
    return selected[: limit + 1]


def retrieve_uploaded_sources(
    records: list[DocumentRecord], question: str, max_chars: int = 26000
) -> list[RetrievedSource]:
    sources: list[RetrievedSource] = []
    remaining = max_chars
    for index, record in enumerate(records, start=1):
        bilingual = "\n\n".join(
            part for part in (record.translated_text, record.extracted_text) if part
        )
        chunks = _rank_blocks(bilingual, question, limit=3)
        if not chunks:
            continue
        content = "\n\n".join(chunks)
        if len(content) > 4200:
            content = content[:4200]
        if len(content) > remaining:
            content = content[: max(0, remaining)]
        if not content:
            break
        remaining -= len(content)
        sources.append(
            RetrievedSource(
                label=f"P{index}",
                title=record.source_filename or record.document_id,
                content=content,
            )
        )
        if remaining <= 0:
            break
    return sources


def search_online_literature(question: str, limit: int = 3) -> list[RetrievedSource]:
    """Fetch supplementary scholarly metadata from Semantic Scholar.

    Search failure is intentionally non-fatal: uploaded papers remain the
    primary and fully local source of truth.
    """
    query = " ".join(question.replace("-", " ").split())[:240]
    if len(query) < 3:
        return []
    try:
        response = requests.get(
            "https://api.semanticscholar.org/graph/v1/paper/search",
            params={
                "query": query,
                "limit": max(1, min(limit, 5)),
                "fields": "title,url,abstract,year,authors,externalIds",
            },
            timeout=8,
            headers={"User-Agent": "PaperReader/0.2 literature-chat"},
        )
        response.raise_for_status()
        data = response.json().get("data") or []
    except Exception as exc:
        logger.info("Online literature search unavailable: %s", exc)
        return []

    sources: list[RetrievedSource] = []
    for index, paper in enumerate(data[:limit], start=1):
        title = str(paper.get("title") or "Untitled paper")
        abstract = str(paper.get("abstract") or "No abstract available.")
        authors = ", ".join(
            str(author.get("name") or "") for author in (paper.get("authors") or [])[:8]
        )
        content = f"Authors: {authors}\nAbstract: {abstract}"
        sources.append(
            RetrievedSource(
                label=f"W{index}",
                title=title,
                content=content[:5000],
                url=paper.get("url"),
                source_type="web",
                year=paper.get("year"),
            )
        )
    return sources


def build_grounded_prompt(
    *,
    question: str,
    uploaded: list[RetrievedSource],
    web: list[RetrievedSource],
    history: list[dict],
) -> tuple[str, str]:
    source_sections: list[str] = []
    for source in [*uploaded, *web]:
        source_sections.append(
            f"[{source.label}] {source.title}\n{source.content}"
        )
    history_text = "\n".join(
        f"{item.get('role', 'user')}: {item.get('content', '')}"
        for item in history[-8:]
    )
    system_prompt = (
        "你是严谨的学术论文助手。优先依据用户上传的论文来源 [P#] 回答，"
        "网络学术资料 [W#] 只能作为补充。比较论文时明确区分各论文，不要把"
        "来源之间的观点混在一起。每个重要事实或判断后使用 [P1]、[W1] 这种"
        "标签引用；没有证据时明确说不知道。回答使用用户提问的语言。"
    )
    sources_text = "\n\n".join(source_sections) or "（没有可用资料）"
    user_message = (
        f"已有会话：\n{history_text or '（无）'}\n\n"
        f"检索到的资料：\n{sources_text}\n\n"
        f"当前问题：\n{question}"
    )
    return system_prompt, user_message


def append_source_list(
    answer: str, uploaded: list[RetrievedSource], web: list[RetrievedSource]
) -> str:
    lines = ["\n\n### 参考资料"]
    for source in uploaded:
        lines.append(f"- [{source.label}] {source.title}（用户上传论文）")
    for source in web:
        year = f" ({source.year})" if source.year else ""
        url = f" — {source.url}" if source.url else ""
        lines.append(f"- [{source.label}] {source.title}{year}{url}")
    if len(lines) == 1:
        lines.append("- 本次未检索到可引用资料。")
    return answer.rstrip() + "\n" + "\n".join(lines)
