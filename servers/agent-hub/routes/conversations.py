from typing import Dict

from fastapi import APIRouter, HTTPException

from config import GOOGLE_MODEL, GOOGLE_MODELS
from conversation_hub import conv_client
from models import (
    Conversation,
    ConversationCreateRequest,
    ConversationListResponse,
    ConversationUpdateRequest,
)

router = APIRouter()


def _conversation_not_found(conversation_id: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"Conversation '{conversation_id}' not found.")


@router.get("/conversations", response_model=ConversationListResponse)
async def list_conversations() -> ConversationListResponse:
    data = await conv_client.list()
    return ConversationListResponse(**data)


@router.post("/conversations", response_model=Conversation)
async def create_conversation(request: ConversationCreateRequest) -> Conversation:
    model = (request.model or GOOGLE_MODEL).strip() or GOOGLE_MODEL
    if model not in GOOGLE_MODELS:
        raise HTTPException(status_code=400, detail=f"Unknown model '{model}'. Available: {GOOGLE_MODELS}")

    data = await conv_client.create(request.title, model=model)
    return Conversation(**data)


@router.get("/conversations/{conversation_id}", response_model=Conversation)
async def get_conversation(conversation_id: str) -> Conversation:
    try:
        data = await conv_client.get(conversation_id)
    except KeyError:
        raise _conversation_not_found(conversation_id) from None
    return Conversation(**data)


@router.patch("/conversations/{conversation_id}", response_model=Conversation)
async def update_conversation(conversation_id: str, request: ConversationUpdateRequest) -> Conversation:
    try:
        data = await conv_client.update_title(conversation_id, request.title)
    except KeyError:
        raise _conversation_not_found(conversation_id) from None
    return Conversation(**data)


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str) -> Dict[str, str]:
    try:
        await conv_client.delete(conversation_id)
    except KeyError:
        raise _conversation_not_found(conversation_id) from None
    return {"status": "deleted", "id": conversation_id}
