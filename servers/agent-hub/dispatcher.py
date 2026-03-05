"""Provider routing — infer provider from model name and dispatch to the right stream function."""
from __future__ import annotations

from typing import Any, AsyncIterator, Dict, Optional

import providers.azure as azure_provider
import providers.google as google_provider
import providers.ollama as ollama_provider
from providers.google import stream_google_chat
from providers.ollama import stream_ollama_chat
from providers.azure import stream_azure_chat


def _infer_provider(model: str) -> str:
    """Infer provider from model name when not explicitly provided."""
    if model.startswith("gemini"):
        return "google"
    if model.startswith("gpt") or model == azure_provider.AZURE_DEPLOYMENT:
        return "azure"
    return "ollama"


def _resolve_provider(request_provider: Optional[str], model: str) -> str:
    return (request_provider or "").strip() or _infer_provider(model)


async def _dispatch_stream(provider: str, message: str, session_id: str, model: str) -> AsyncIterator[Dict[str, Any]]:
    if provider == "google":
        async for event in stream_google_chat(message, session_id, model):
            yield event
    elif provider == "ollama":
        async for event in stream_ollama_chat(message, session_id, model):
            yield event
    elif provider == "azure":
        async for event in stream_azure_chat(message, session_id, model):
            yield event
    else:
        yield {"type": "error", "content": f"Unknown provider '{provider}'."}
