from fastapi import APIRouter, HTTPException

from app.models.schemas import ChatRequest, ChatResponse
from app.models.store import DOCUMENTS
from app.services.llm_client import llm_client


router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest) -> ChatResponse:
    record = DOCUMENTS.get(payload.document_id)
    if not record:
        raise HTTPException(status_code=404, detail="Document not found")

    context = record.translated_text or record.extracted_text
    system_prompt = "You are a research paper assistant. Use provided paper context to answer accurately and concisely."
    user_message = f"Paper context:\n{context[:12000]}\n\nQuestion:\n{payload.message}"

    answer = llm_client.chat(
        message=user_message,
        system_prompt=system_prompt,
        override_api_key=payload.override_api_key,
        override_base_url=payload.override_base_url,
        override_model=payload.override_model,
    )
    return ChatResponse(answer=answer)
