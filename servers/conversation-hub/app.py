import asyncio
import os
import time
from typing import Any, Dict, List, Optional
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

load_dotenv()

PORT = int(os.getenv("PORT", "3300"))
ALLOW_ORIGINS = [o.strip() for o in os.getenv("ALLOW_ORIGINS", "*").split(",") if o.strip()]

app = FastAPI(title="Conversation Hub Service")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOW_ORIGINS or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Models ---------------------------------------------------------------------

class ConversationMessage(BaseModel):
    role: str
    content: str
    timestamp: float


class Conversation(BaseModel):
    id: str
    title: str
    model: str
    created_at: float
    updated_at: float
    message_count: int = 0
    messages: List[ConversationMessage] = Field(default_factory=list)


class ConversationSummary(BaseModel):
    id: str
    title: str
    model: str
    created_at: float
    updated_at: float
    message_count: int = 0


class ConversationListResponse(BaseModel):
    conversations: List[ConversationSummary]


class ConversationCreateRequest(BaseModel):
    title: Optional[str] = None
    model: str
    id: Optional[str] = None


class ConversationEnsureRequest(BaseModel):
    id: str
    model: str
    title: Optional[str] = None


class ConversationUpdateRequest(BaseModel):
    title: str = Field(..., min_length=1)


class AppendMessageRequest(BaseModel):
    role: str
    content: str


# Store ----------------------------------------------------------------------

class ConversationStore:
    """In-memory store for chat conversations and their message history."""

    def __init__(self) -> None:
        self.conversations: Dict[str, Dict[str, Any]] = {}
        self.messages: Dict[str, List[Dict[str, Any]]] = {}
        self._counter = 1

    def _now(self) -> float:
        return time.time()

    def _default_title(self) -> str:
        title = f"Conversation {self._counter}"
        self._counter += 1
        return title

    def create(self, title: Optional[str], model: str, conversation_id: Optional[str] = None) -> Dict[str, Any]:
        conv_id = conversation_id or str(uuid4())
        now = self._now()
        conversation = {
            "id": conv_id,
            "title": (title or "").strip() or self._default_title(),
            "model": model,
            "created_at": now,
            "updated_at": now,
            "message_count": 0,
        }
        self.conversations[conv_id] = conversation
        self.messages[conv_id] = []
        return conversation

    def ensure(self, conversation_id: str, model: str, title: Optional[str] = None) -> Dict[str, Any]:
        existing = self.conversations.get(conversation_id)
        if existing:
            existing["model"] = model
            return existing
        return self.create(title=title, model=model, conversation_id=conversation_id)

    def list(self) -> List[Dict[str, Any]]:
        return sorted(self.conversations.values(), key=lambda c: c["updated_at"], reverse=True)

    def get(self, conversation_id: str) -> Dict[str, Any]:
        conversation = self.conversations.get(conversation_id)
        if not conversation:
            raise KeyError(conversation_id)
        return conversation

    def update_title(self, conversation_id: str, title: str) -> Dict[str, Any]:
        conversation = self.get(conversation_id)
        conversation["title"] = title.strip() or conversation["title"]
        conversation["updated_at"] = self._now()
        return conversation

    def delete(self, conversation_id: str) -> None:
        self.conversations.pop(conversation_id, None)
        self.messages.pop(conversation_id, None)

    def append_message(self, conversation_id: str, role: str, content: str) -> Dict[str, Any]:
        conversation = self.get(conversation_id)
        entry = {
            "role": role,
            "content": content,
            "timestamp": self._now(),
        }
        self.messages.setdefault(conversation_id, []).append(entry)
        conversation["updated_at"] = entry["timestamp"]
        conversation["message_count"] = len(self.messages.get(conversation_id, []))
        return entry

    def detail(self, conversation_id: str) -> Dict[str, Any]:
        conversation = self.get(conversation_id)
        return {
            **conversation,
            "messages": list(self.messages.get(conversation_id, [])),
        }

    def get_messages(self, conversation_id: str) -> List[Dict[str, Any]]:
        self.get(conversation_id)  # raises KeyError if not found
        return list(self.messages.get(conversation_id, []))


store = ConversationStore()
lock = asyncio.Lock()


# Helpers --------------------------------------------------------------------

def _not_found(conversation_id: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"Conversation '{conversation_id}' not found.")


# Routes ---------------------------------------------------------------------

@app.get("/conversations", response_model=ConversationListResponse)
async def list_conversations() -> ConversationListResponse:
    async with lock:
        summaries = [ConversationSummary(**c) for c in store.list()]
    return ConversationListResponse(conversations=summaries)


@app.post("/conversations", response_model=Conversation)
async def create_conversation(request: ConversationCreateRequest) -> Conversation:
    async with lock:
        conversation = store.create(request.title, model=request.model, conversation_id=request.id)
        detail = store.detail(conversation["id"])
    return Conversation(**detail)


@app.post("/conversations/ensure", response_model=ConversationSummary)
async def ensure_conversation(request: ConversationEnsureRequest) -> ConversationSummary:
    async with lock:
        conversation = store.ensure(request.id, model=request.model, title=request.title)
    return ConversationSummary(**conversation)


@app.get("/conversations/{conversation_id}", response_model=Conversation)
async def get_conversation(conversation_id: str) -> Conversation:
    async with lock:
        try:
            detail = store.detail(conversation_id)
        except KeyError:
            raise _not_found(conversation_id) from None
    return Conversation(**detail)


@app.patch("/conversations/{conversation_id}", response_model=Conversation)
async def update_conversation(conversation_id: str, request: ConversationUpdateRequest) -> Conversation:
    async with lock:
        try:
            store.update_title(conversation_id, request.title)
            detail = store.detail(conversation_id)
        except KeyError:
            raise _not_found(conversation_id) from None
    return Conversation(**detail)


@app.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str) -> Dict[str, str]:
    async with lock:
        if conversation_id not in store.conversations:
            raise _not_found(conversation_id)
        store.delete(conversation_id)
    return {"status": "deleted", "id": conversation_id}


@app.post("/conversations/{conversation_id}/messages", response_model=ConversationMessage)
async def append_message(conversation_id: str, request: AppendMessageRequest) -> ConversationMessage:
    async with lock:
        try:
            entry = store.append_message(conversation_id, request.role, request.content)
        except KeyError:
            raise _not_found(conversation_id) from None
    return ConversationMessage(**entry)


@app.get("/conversations/{conversation_id}/messages", response_model=List[ConversationMessage])
async def get_messages(conversation_id: str) -> List[ConversationMessage]:
    async with lock:
        try:
            messages = store.get_messages(conversation_id)
        except KeyError:
            raise _not_found(conversation_id) from None
    return [ConversationMessage(**m) for m in messages]


@app.get("/healthz")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=PORT, reload=False)
