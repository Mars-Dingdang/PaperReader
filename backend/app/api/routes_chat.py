import json
from collections.abc import Iterator

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.api.deps import get_current_user
from app.models.schemas import (
    ChatRequest,
    ChatResponse,
    ChatSessionItem,
    CreateChatSessionRequest,
    SourceRefItem,
)
from app.models.store import list_documents_for_user
from app.services.alignment_service import (
    _plain_target,
    load_alignment_entries,
    locate_in_alignment,
)
from app.services.auth_service import User, ensure_user_settings, require_provider_settings
from app.services.chat_store import (
    append_message,
    create_session,
    get_session,
    list_sessions,
    update_session_documents,
)
from app.services.literature_service import (
    append_source_list,
    build_grounded_prompt,
    retrieve_uploaded_sources,
    search_online_literature,
)
from app.services.llm_client import llm_client


router = APIRouter()


def _as_session_item(session: dict) -> ChatSessionItem:
    return ChatSessionItem(**session)


@router.get("/chat/sessions", response_model=list[ChatSessionItem])
def get_chat_sessions(
    scope: str = Query("document"),
    document_id: str | None = Query(None),
    user: User = Depends(get_current_user),
) -> list[ChatSessionItem]:
    return [
        _as_session_item(session)
        for session in list_sessions(
            owner_user_id=user.id, scope=scope, document_id=document_id
        )
    ]


@router.post("/chat/sessions", response_model=ChatSessionItem)
def post_chat_session(
    payload: CreateChatSessionRequest,
    user: User = Depends(get_current_user),
) -> ChatSessionItem:
    owned = {record.document_id for record in list_documents_for_user(user.id)}
    ids = [document_id for document_id in payload.document_ids if document_id in owned]
    if payload.scope != "library" and not ids:
        raise HTTPException(status_code=400, detail="Document session requires a document")
    session = create_session(
        owner_user_id=user.id,
        scope=payload.scope,
        document_ids=ids,
        title=payload.title,
    )
    return _as_session_item(session)


@router.get("/chat/sessions/{session_id}", response_model=ChatSessionItem)
def get_chat_session(
    session_id: str, user: User = Depends(get_current_user)
) -> ChatSessionItem:
    session = get_session(session_id, owner_user_id=user.id)
    if not session:
        raise HTTPException(status_code=404, detail="Chat session not found")
    return _as_session_item(session)


def _quote_context(record, quote: str) -> str:
    """Ground a reader selection in its aligned bilingual block + neighbours."""
    entries, _ = load_alignment_entries(record)
    if not entries:
        return ""
    for side in ("original", "translated"):
        _, _, confidence, index, _ = locate_in_alignment(
            entries, source_side=side, selected_text=quote, page_ratio=0.0
        )
        if confidence < 0.55:
            continue
        entry = entries[index]
        original = _plain_target(str(entry.get("original") or ""))
        translated = _plain_target(str(entry.get("translated") or ""))
        before = _plain_target(str(entries[index - 1].get("original") or "")) if index > 0 else ""
        after = (
            _plain_target(str(entries[index + 1].get("original") or ""))
            if index + 1 < len(entries)
            else ""
        )
        lines = [
            "用户正在阅读器中选中的片段及其上下文（回答时优先参考这一段）：",
            f"- 选中片段：{quote[:600]}",
        ]
        if side == "original":
            lines.append(f"- 所在原文段落：{original}")
            if translated:
                lines.append(f"- 对应译文：{translated}")
        else:
            lines.append(f"- 所在译文段落：{translated}")
            if original:
                lines.append(f"- 对应原文：{original}")
        if before:
            lines.append(f"- 前一段原文：{before[:400]}")
        if after:
            lines.append(f"- 后一段原文：{after[:400]}")
        return "\n".join(lines)
    return ""


def _prepare_chat(payload: ChatRequest, user: User):
    scope = "library" if payload.scope == "library" else "document"
    owned_records = {
        record.document_id: record for record in list_documents_for_user(user.id)
    }
    requested_ids = payload.document_ids or ([payload.document_id] if payload.document_id else [])
    if scope == "library" and not requested_ids:
        requested_ids = list(owned_records.keys())
    document_ids = [
        document_id for document_id in requested_ids if document_id in owned_records
    ]
    if not document_ids:
        raise HTTPException(status_code=404, detail="No available documents selected")

    session = (
        get_session(payload.session_id, owner_user_id=user.id)
        if payload.session_id
        else None
    )
    if session is None:
        session = create_session(
            owner_user_id=user.id, scope=scope, document_ids=document_ids
        )
    elif session.get("scope") != scope:
        raise HTTPException(status_code=400, detail="Chat session scope mismatch")
    elif document_ids != (session.get("document_ids") or []):
        session = update_session_documents(
            session["session_id"], document_ids, owner_user_id=user.id
        )

    history = list(session.get("messages") or [])
    append_message(
        session["session_id"],
        owner_user_id=user.id,
        role="user",
        content=payload.message,
    )

    records = [owned_records[document_id] for document_id in document_ids]
    uploaded_sources = retrieve_uploaded_sources(records, payload.message)
    web_sources = search_online_literature(payload.message)
    system_prompt, user_message = build_grounded_prompt(
        question=payload.message,
        uploaded=uploaded_sources,
        web=web_sources,
        history=history,
    )

    quote_text = (payload.quote or "").strip()
    if quote_text:
        quote_record = owned_records.get(payload.document_id or "") or (
            records[0] if records else None
        )
        if quote_record:
            context = _quote_context(quote_record, quote_text)
            if context:
                user_message = f"{context}\n\n{user_message}"

    source_refs = [
        SourceRefItem(
            label=source.label,
            title=source.title,
            content=source.content[:800],
            document_id=source.document_id,
            position_ratio=source.position_ratio,
        )
        for source in uploaded_sources
    ]
    user_settings = ensure_user_settings(user.id)
    if not payload.override_api_key:
        user_settings = require_provider_settings(user.id)

    return {
        "session": session,
        "system_prompt": system_prompt,
        "user_message": user_message,
        "uploaded_sources": uploaded_sources,
        "web_sources": web_sources,
        "source_refs": source_refs,
        "settings": user_settings,
    }


def _finish_answer(answer: str, prepared: dict) -> str:
    return append_source_list(
        answer, prepared["uploaded_sources"], prepared["web_sources"]
    )


@router.post("/chat", response_model=ChatResponse)
def chat(
    payload: ChatRequest, user: User = Depends(get_current_user)
) -> ChatResponse:
    prepared = _prepare_chat(payload, user)
    answer = llm_client.chat(
        message=prepared["user_message"],
        system_prompt=prepared["system_prompt"],
        override_api_key=payload.override_api_key or prepared["settings"].api_key,
        override_base_url=payload.override_base_url or prepared["settings"].base_url,
        override_model=payload.override_model or prepared["settings"].model,
    )
    answer = _finish_answer(answer, prepared)
    append_message(
        prepared["session"]["session_id"],
        owner_user_id=user.id,
        role="assistant",
        content=answer,
    )
    return ChatResponse(
        answer=answer,
        session_id=prepared["session"]["session_id"],
        sources=prepared["source_refs"],
    )


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/chat/stream")
def chat_stream(
    payload: ChatRequest, user: User = Depends(get_current_user)
) -> StreamingResponse:
    prepared = _prepare_chat(payload, user)
    session_id = prepared["session"]["session_id"]

    def generate() -> Iterator[str]:
        yield _sse("meta", {"session_id": session_id})
        accumulated: list[str] = []
        persisted = False

        def persist(text: str) -> None:
            nonlocal persisted
            if persisted:
                return
            persisted = True
            if text.strip():
                append_message(
                    session_id, owner_user_id=user.id, role="assistant", content=text
                )

        try:
            for delta in llm_client.chat_stream(
                message=prepared["user_message"],
                system_prompt=prepared["system_prompt"],
                override_api_key=payload.override_api_key or prepared["settings"].api_key,
                override_base_url=payload.override_base_url or prepared["settings"].base_url,
                override_model=payload.override_model or prepared["settings"].model,
            ):
                accumulated.append(delta)
                yield _sse("delta", {"text": delta})
            answer = _finish_answer("".join(accumulated), prepared)
            persist(answer)
            yield _sse(
                "done",
                {"answer": answer, "session_id": session_id, "sources": [ref.model_dump() for ref in prepared["source_refs"]]},
            )
        except Exception as exc:
            partial = "".join(accumulated)
            if partial.strip():
                # The stream broke mid-answer; keep what arrived.
                persist(_finish_answer(partial, prepared))
                yield _sse(
                    "done",
                    {"answer": partial, "session_id": session_id, "sources": [ref.model_dump() for ref in prepared["source_refs"]]},
                )
            else:
                yield _sse("error", {"message": str(exc) or "聊天请求失败"})

    return StreamingResponse(generate(), media_type="text/event-stream")
