"""Google ADK provider — configuration, session management, and streaming chat."""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, AsyncIterator, Dict, Optional

from config import DEFAULT_INSTRUCTION, GOOGLE_MODEL, MCP_SERVER_URL

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration globals (may be updated by kubernetes._refresh_provider_config_from_secret)
# ---------------------------------------------------------------------------

GOOGLE_API_KEY: Optional[str] = os.getenv("GOOGLE_API_KEY") or os.getenv("GOOGLE_GENAI_API_KEY")
GOOGLE_VERTEX_PROJECT: Optional[str] = os.getenv("GOOGLE_VERTEX_PROJECT") or os.getenv("VERTEX_PROJECT")
GOOGLE_VERTEX_LOCATION: Optional[str] = os.getenv("GOOGLE_VERTEX_LOCATION") or os.getenv("VERTEX_LOCATION")
GOOGLE_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.5-pro",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-1.5-pro",
    "gemini-1.5-flash",
]
GOOGLE_ENABLED: bool = bool(GOOGLE_API_KEY or (GOOGLE_VERTEX_PROJECT and GOOGLE_VERTEX_LOCATION))

try:
    from google.adk.agents import Agent as GoogleAgent
    from google.adk.runners import Runner as GoogleRunner
    from google.adk.sessions.in_memory_session_service import InMemorySessionService as GoogleSessionService
    from google.adk.tools.mcp_tool import MCPToolset as GoogleMCPToolset
    from google.adk.tools.mcp_tool import StreamableHTTPConnectionParams as GoogleHTTPParams
    from google.genai import types as GoogleTypes
    _GOOGLE_LIBS = True
except ImportError:
    _GOOGLE_LIBS = False
    logger.warning("google-adk not installed; Google provider unavailable.")

# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------

_google_session_service: Optional[Any] = None
_google_runners: Dict[str, Any] = {}
_google_lock = asyncio.Lock()
_GOOGLE_APP_NAME = "todea-google"


def _build_google_agent(model: str) -> Any:
    if not GOOGLE_ENABLED:
        raise RuntimeError(
            "Google credentials are missing. Set GOOGLE_API_KEY or configure GOOGLE_VERTEX_PROJECT/LOCATION."
        )
    tool_set = GoogleMCPToolset(
        connection_params=GoogleHTTPParams(url=MCP_SERVER_URL.rstrip("/"))
    )
    return GoogleAgent(
        name="google_agent",
        model=model,
        description="Google agent with MCP tools",
        instruction=DEFAULT_INSTRUCTION,
        tools=[tool_set],
    )


def _get_google_runner(model: str) -> Any:
    global _google_session_service, _google_runners
    if _google_session_service is None:
        _google_session_service = GoogleSessionService()
    if model not in _google_runners:
        _google_runners[model] = GoogleRunner(
            app_name=_GOOGLE_APP_NAME,
            agent=_build_google_agent(model),
            session_service=_google_session_service,
        )
    return _google_runners[model]


async def _ensure_google_session(session_id: str) -> None:
    existing = await _google_session_service.get_session(
        app_name=_GOOGLE_APP_NAME, user_id="web-ui", session_id=session_id
    )
    if not existing:
        await _google_session_service.create_session(
            app_name=_GOOGLE_APP_NAME, user_id="web-ui", session_id=session_id
        )


def _google_content_to_text(content: Optional[Any]) -> str:
    if not content:
        return ""
    parts = []
    for part in (content.parts or []):
        if getattr(part, "text", None):
            parts.append(part.text)
        elif getattr(part, "function_call", None):
            parts.append(f"[function call] {part.function_call.name}")
        elif getattr(part, "function_response", None):
            fn = part.function_response
            parts.append(f"[function response] {fn.name}: {fn.response}")
        elif getattr(part, "code_execution_result", None):
            result = part.code_execution_result
            output = getattr(result, "output", None) or getattr(result, "stdout", None)
            if output:
                parts.append(str(output))
    return "\n".join(p for p in parts if p) or (getattr(content, "text", "") or "")


async def stream_google_chat(message: str, session_id: str, model: str) -> AsyncIterator[Dict[str, Any]]:
    if not _GOOGLE_LIBS:
        yield {"type": "error", "content": "google-adk library not installed."}
        return
    try:
        runner = _get_google_runner(model)
    except RuntimeError as exc:
        yield {"type": "error", "content": str(exc)}
        return

    await _ensure_google_session(session_id)
    final_response = ""
    user_message = GoogleTypes.Content(role="user", parts=[GoogleTypes.Part(text=message)])

    try:
        async for event in runner.run_async(
            user_id="web-ui", session_id=session_id, new_message=user_message
        ):
            if not event.content or not event.content.parts:
                continue
            for part in event.content.parts:
                if getattr(part, "text", None):
                    if event.is_final_response():
                        final_response = part.text
                    else:
                        yield {"type": "thinking", "content": part.text}
                elif getattr(part, "function_call", None):
                    fc = part.function_call
                    yield {"type": "tool_call", "name": fc.name, "args": dict(fc.args) if fc.args else {}}
                elif getattr(part, "function_response", None):
                    fr = part.function_response
                    yield {"type": "tool_result", "name": fr.name, "content": str(fr.response) if fr.response is not None else ""}
    except Exception as exc:
        logger.warning("stream_google_chat error: %s", exc)
        yield {"type": "error", "content": str(exc)}
        return

    yield {"type": "done", "content": final_response or "The agent did not return any text."}
