"""In-memory conversation store."""
from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional
from uuid import uuid4


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
