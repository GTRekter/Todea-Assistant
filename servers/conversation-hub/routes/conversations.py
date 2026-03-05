from typing import Dict, List

from fastapi import APIRouter, HTTPException

from schemas import (
    AppendMessageRequest,
    Conversation,
    ConversationCreateRequest,
    ConversationEnsureRequest,
    ConversationListResponse,
    ConversationMessage,
    ConversationSummary,
    ConversationUpdateRequest,
)
from store import lock, store

router = APIRouter(prefix="/conversations")


def _not_found(conversation_id: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"Conversation '{conversation_id}' not found.")


@router.get("", response_model=ConversationListResponse)
async def list_conversations() -> ConversationListResponse:
    async with lock:
        summaries = [ConversationSummary(**c) for c in store.list()]
    return ConversationListResponse(conversations=summaries)


@router.post("", response_model=Conversation)
async def create_conversation(request: ConversationCreateRequest) -> Conversation:
    async with lock:
        conversation = store.create(request.title, model=request.model, conversation_id=request.id)
        detail = store.detail(conversation["id"])
    return Conversation(**detail)


@router.post("/ensure", response_model=ConversationSummary)
async def ensure_conversation(request: ConversationEnsureRequest) -> ConversationSummary:
    async with lock:
        conversation = store.ensure(request.id, model=request.model, title=request.title)
    return ConversationSummary(**conversation)


@router.get("/{conversation_id}", response_model=Conversation)
async def get_conversation(conversation_id: str) -> Conversation:
    async with lock:
        try:
            detail = store.detail(conversation_id)
        except KeyError:
            raise _not_found(conversation_id) from None
    return Conversation(**detail)


@router.patch("/{conversation_id}", response_model=Conversation)
async def update_conversation(conversation_id: str, request: ConversationUpdateRequest) -> Conversation:
    async with lock:
        try:
            store.update_title(conversation_id, request.title)
            detail = store.detail(conversation_id)
        except KeyError:
            raise _not_found(conversation_id) from None
    return Conversation(**detail)


@router.delete("/{conversation_id}")
async def delete_conversation(conversation_id: str) -> Dict[str, str]:
    async with lock:
        if conversation_id not in store.conversations:
            raise _not_found(conversation_id)
        store.delete(conversation_id)
    return {"status": "deleted", "id": conversation_id}


@router.post("/{conversation_id}/messages", response_model=ConversationMessage)
async def append_message(conversation_id: str, request: AppendMessageRequest) -> ConversationMessage:
    async with lock:
        try:
            entry = store.append_message(conversation_id, request.role, request.content)
        except KeyError:
            raise _not_found(conversation_id) from None
    return ConversationMessage(**entry)


@router.get("/{conversation_id}/messages", response_model=List[ConversationMessage])
async def get_messages(conversation_id: str) -> List[ConversationMessage]:
    async with lock:
        try:
            messages = store.get_messages(conversation_id)
        except KeyError:
            raise _not_found(conversation_id) from None
    return [ConversationMessage(**m) for m in messages]
