"""Chat and model listing routes."""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

import providers.azure as azure_provider
import providers.google as google_provider
import providers.ollama as ollama_provider
from conv_client import conv_client
from dispatcher import _dispatch_stream, _resolve_provider
from kubernetes import _refresh_provider_config_from_secret
from providers.ollama import _list_ollama_models
from schemas import ChatRequest, ChatResponse, ModelInfo, ModelsResponse

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/models", response_model=ModelsResponse)
async def list_models() -> ModelsResponse:
    _refresh_provider_config_from_secret()

    models: List[ModelInfo] = []
    default_id: Optional[str] = None
    default_provider: Optional[str] = None

    if google_provider.GOOGLE_ENABLED and google_provider._GOOGLE_LIBS:
        for m in google_provider.GOOGLE_MODELS:
            models.append(ModelInfo(id=m, provider="google"))
        if not default_id:
            default_id = google_provider.GOOGLE_MODEL
            default_provider = "google"

    if azure_provider.AZURE_ENABLED and azure_provider._AZURE_LIBS:
        models.append(ModelInfo(id=azure_provider.AZURE_DEPLOYMENT, provider="azure"))
        if not default_id:
            default_id = azure_provider.AZURE_DEPLOYMENT
            default_provider = "azure"

    if ollama_provider._OLLAMA_LIBS and ollama_provider.OLLAMA_ENABLED:
        ollama_names = await _list_ollama_models()
        for m in ollama_names:
            models.append(ModelInfo(id=m, provider="ollama"))
        if not default_id and ollama_names:
            default_id = ollama_provider.OLLAMA_MODEL if ollama_provider.OLLAMA_MODEL in ollama_names else ollama_names[0]
            default_provider = "ollama"

    return ModelsResponse(models=models, default=default_id, default_provider=default_provider)


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    _refresh_provider_config_from_secret()

    message = (request.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="A message is required.")

    model = (request.model or "").strip()
    provider = _resolve_provider(request.provider, model)
    session_id = (request.session_id or f"default-{provider}").strip()

    if not model:
        if provider == "google":
            model = google_provider.GOOGLE_MODEL
        elif provider == "azure":
            model = azure_provider.AZURE_DEPLOYMENT
        elif provider == "ollama":
            model = ollama_provider.OLLAMA_MODEL

    await conv_client.ensure(session_id, model=model)
    final_content: Dict[str, str] = {"value": ""}

    async def event_generator():
        async for event in _dispatch_stream(provider, message, session_id, model):
            if event.get("type") == "done":
                final_content["value"] = event.get("content", "")
            yield f"data: {json.dumps(event)}\n\n"
        try:
            await conv_client.append_message(session_id, "user", message)
            await conv_client.append_message(session_id, "assistant", final_content["value"])
        except Exception as exc:
            logger.warning("Failed to persist conversation: %s", exc)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    _refresh_provider_config_from_secret()

    message = (request.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="A message is required.")

    model = (request.model or "").strip()
    provider = _resolve_provider(request.provider, model)
    session_id = (request.session_id or f"default-{provider}").strip()

    if not model:
        model = google_provider.GOOGLE_MODEL if provider == "google" else (
            azure_provider.AZURE_DEPLOYMENT if provider == "azure" else ollama_provider.OLLAMA_MODEL
        )

    await conv_client.ensure(session_id, model=model)

    final_response = ""
    async for event in _dispatch_stream(provider, message, session_id, model):
        if event.get("type") == "done":
            final_response = event.get("content", "")
        elif event.get("type") == "error":
            raise HTTPException(status_code=500, detail=event.get("content", "Unknown error"))

    await conv_client.append_message(session_id, "user", message)
    await conv_client.append_message(session_id, "assistant", final_response)

    return ChatResponse(content=final_response, provider=provider, session_id=session_id)
