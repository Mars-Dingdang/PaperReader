from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_current_user
from app.models.schemas import (
    ChatRequest,
    ChatResponse,
    ChatSessionItem,
    CreateChatSessionRequest,
)
from app.models.store import list_documents_for_user
from app.services.auth_service import User, ensure_user_settings
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


@router.post("/chat", response_model=ChatResponse)
def chat(
    payload: ChatRequest, user: User = Depends(get_current_user)
) -> ChatResponse:
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

    user_settings = ensure_user_settings(user.id)
    answer = llm_client.chat(
        message=user_message,
        system_prompt=system_prompt,
        override_api_key=payload.override_api_key or user_settings.api_key,
        override_base_url=payload.override_base_url or user_settings.base_url,
        override_model=payload.override_model or user_settings.model,
    )
    answer = append_source_list(answer, uploaded_sources, web_sources)
    append_message(
        session["session_id"],
        owner_user_id=user.id,
        role="assistant",
        content=answer,
    )
    return ChatResponse(answer=answer, session_id=session["session_id"])
