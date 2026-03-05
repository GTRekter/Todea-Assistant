"""Conversation Hub HTTP client and shared singleton."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx

from config import CONVERSATION_HUB_URL


class ConversationHubClient:
    def __init__(self, base_url: str) -> None:
        self._base = base_url.rstrip("/")

    async def ensure(self, conversation_id: str, model: str, title: Optional[str] = None) -> Dict[str, Any]:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._base}/conversations/ensure",
                json={"id": conversation_id, "model": model, "title": title},
            )
            resp.raise_for_status()
            return resp.json()

    async def append_message(self, conversation_id: str, role: str, content: str) -> None:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._base}/conversations/{conversation_id}/messages",
                json={"role": role, "content": content},
            )
            resp.raise_for_status()

    async def get_messages(self, conversation_id: str) -> List[Dict[str, Any]]:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{self._base}/conversations/{conversation_id}/messages")
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            return resp.json()

    async def list(self) -> Dict[str, Any]:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{self._base}/conversations")
            resp.raise_for_status()
            return resp.json()

    async def create(self, title: Optional[str], model: str) -> Dict[str, Any]:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._base}/conversations",
                json={"title": title, "model": model},
            )
            resp.raise_for_status()
            return resp.json()

    async def get(self, conversation_id: str) -> Dict[str, Any]:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{self._base}/conversations/{conversation_id}")
            if resp.status_code == 404:
                raise KeyError(conversation_id)
            resp.raise_for_status()
            return resp.json()

    async def update_title(self, conversation_id: str, title: str) -> Dict[str, Any]:
        async with httpx.AsyncClient() as client:
            resp = await client.patch(
                f"{self._base}/conversations/{conversation_id}",
                json={"title": title},
            )
            if resp.status_code == 404:
                raise KeyError(conversation_id)
            resp.raise_for_status()
            return resp.json()

    async def delete(self, conversation_id: str) -> None:
        async with httpx.AsyncClient() as client:
            resp = await client.delete(f"{self._base}/conversations/{conversation_id}")
            if resp.status_code == 404:
                raise KeyError(conversation_id)
            resp.raise_for_status()


conv_client = ConversationHubClient(CONVERSATION_HUB_URL)
