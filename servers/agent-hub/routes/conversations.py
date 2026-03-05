"""Conversation CRUD routes (proxy to conversation-hub)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

import providers.google as google_provider
from conv_client import conv_client
from schemas import (
    Conversation,
    ConversationCreateRequest,
    ConversationListResponse,
    ConversationUpdateRequest,
)

router = APIRouter(prefix="/conversations")


def _not_found(conversation_id: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"Conversation '{conversation_id}' not found.")


@router.get("", response_model=ConversationListResponse)
async def list_conversations() -> ConversationListResponse:
    data = await conv_client.list()
    return ConversationListResponse(**data)


@router.post("", response_model=Conversation)
async def create_conversation(request: ConversationCreateRequest) -> Conversation:
    model = (request.model or google_provider.GOOGLE_MODEL).strip() or google_provider.GOOGLE_MODEL
    data = await conv_client.create(request.title, model=model)
    return Conversation(**data)


@router.get("/{conversation_id}", response_model=Conversation)
async def get_conversation(conversation_id: str) -> Conversation:
    try:
        data = await conv_client.get(conversation_id)
    except KeyError:
        raise _not_found(conversation_id) from None
    return Conversation(**data)


@router.patch("/{conversation_id}", response_model=Conversation)
async def update_conversation(conversation_id: str, request: ConversationUpdateRequest) -> Conversation:
    try:
        data = await conv_client.update_title(conversation_id, request.title)
    except KeyError:
        raise _not_found(conversation_id) from None
    return Conversation(**data)


@router.delete("/{conversation_id}")
async def delete_conversation(conversation_id: str) -> dict:
    try:
        await conv_client.delete(conversation_id)
    except KeyError:
        raise _not_found(conversation_id) from None
    return {"status": "deleted", "id": conversation_id}
