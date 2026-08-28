from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.models.schemas import ChatRequest, ChatResponse
from app.models.store import require_document_owner
from app.services.auth_service import User, ensure_user_settings
from app.services.llm_client import llm_client


router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest, user: User = Depends(get_current_user)) -> ChatResponse:
    record = require_document_owner(payload.document_id, user.id)
    user_settings = ensure_user_settings(user.id)

    context = record.translated_text or record.extracted_text
    system_prompt = "You are a research paper assistant. Use provided paper context to answer accurately and concisely."
    user_message = f"Paper context:\n{context[:12000]}\n\nQuestion:\n{payload.message}"

    answer = llm_client.chat(
        message=user_message,
        system_prompt=system_prompt,
        override_api_key=payload.override_api_key or user_settings.api_key,
        override_base_url=payload.override_base_url or user_settings.base_url,
        override_model=payload.override_model or user_settings.model,
    )
    return ChatResponse(answer=answer)
