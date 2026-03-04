import json
import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from agent import get_runner, lock, run_agent_chat, stream_agent_chat
from config import GOOGLE_MODEL, GOOGLE_MODELS, PROVIDER_ID
from conversation_hub import conv_client
from models import ChatRequest, ChatResponse

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/models")
async def list_models() -> Dict[str, Any]:
    return {"models": GOOGLE_MODELS, "default": GOOGLE_MODEL}


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    message = (request.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="A message is required.")

    model = (request.model or GOOGLE_MODEL).strip() or GOOGLE_MODEL
    if model not in GOOGLE_MODELS:
        raise HTTPException(status_code=400, detail=f"Unknown model '{model}'. Available: {GOOGLE_MODELS}")

    session_id = (request.session_id or f"default-{PROVIDER_ID}").strip() or f"default-{PROVIDER_ID}"
    await conv_client.ensure(session_id, model=model)

    try:
        get_runner(model)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    async with lock:
        content = await run_agent_chat(message, session_id, model)

    await conv_client.append_message(session_id, "user", message)
    await conv_client.append_message(session_id, "assistant", content)

    return ChatResponse(content=content, provider=PROVIDER_ID, session_id=session_id)


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    message = (request.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="A message is required.")

    model = (request.model or GOOGLE_MODEL).strip() or GOOGLE_MODEL
    if model not in GOOGLE_MODELS:
        raise HTTPException(status_code=400, detail=f"Unknown model '{model}'. Available: {GOOGLE_MODELS}")

    session_id = (request.session_id or f"default-{PROVIDER_ID}").strip() or f"default-{PROVIDER_ID}"
    await conv_client.ensure(session_id, model=model)

    final_content: Dict[str, str] = {"value": ""}

    async def event_generator():
        async for event in stream_agent_chat(message, session_id, model):
            if event.get("type") == "done":
                final_content["value"] = event.get("content", "")
            yield f"data: {json.dumps(event)}\n\n"
        try:
            await conv_client.append_message(session_id, "user", message)
            await conv_client.append_message(session_id, "assistant", final_content["value"])
        except Exception as exc:
            logger.warning("Failed to save conversation after stream: %s", exc)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/healthz")
async def health() -> Dict[str, str]:
    return {"status": "ok"}
