import asyncio
import logging
from typing import Any, AsyncIterator, Dict, Optional

from google.adk.agents import Agent as GoogleAgent
from google.adk.runners import Runner as GoogleRunner
from google.adk.sessions.in_memory_session_service import InMemorySessionService as GoogleInMemorySessionService
from google.adk.tools.mcp_tool import MCPToolset as GoogleMCPToolset
from google.adk.tools.mcp_tool import StreamableHTTPConnectionParams as GoogleStreamableHTTPConnectionParams
from google.genai import types

from config import (
    APP_NAME,
    DEFAULT_INSTRUCTION,
    GOOGLE_API_KEY,
    GOOGLE_VERTEX_LOCATION,
    GOOGLE_VERTEX_PROJECT,
    MCP_SERVER_URL,
    PROVIDER_ID,
)

logger = logging.getLogger(__name__)

session_service: Optional[Any] = None
_runners: Dict[str, Any] = {}
lock = asyncio.Lock()


def ensure_google_credentials() -> None:
    if not GOOGLE_API_KEY and not (GOOGLE_VERTEX_PROJECT and GOOGLE_VERTEX_LOCATION):
        raise RuntimeError(
            "Google credentials are missing. Set GOOGLE_API_KEY (or GOOGLE_GENAI_API_KEY) "
            "or configure GOOGLE_VERTEX_PROJECT and GOOGLE_VERTEX_LOCATION."
        )


def build_agent(model: str) -> Any:
    ensure_google_credentials()
    tool_set = GoogleMCPToolset(
        connection_params=GoogleStreamableHTTPConnectionParams(url=MCP_SERVER_URL.rstrip("/"))
    )
    return GoogleAgent(
        name=f"{PROVIDER_ID}_agent",
        model=model,
        description="Google agent that calls MCP tools",
        instruction=DEFAULT_INSTRUCTION,
        tools=[tool_set],
    )


def get_runner(model: str) -> Any:
    global session_service, _runners
    if session_service is None:
        session_service = GoogleInMemorySessionService()
    if model not in _runners:
        agent = build_agent(model)
        _runners[model] = GoogleRunner(
            app_name=APP_NAME,
            agent=agent,
            session_service=session_service,
        )
    return _runners[model]


async def ensure_session(session_id: str) -> None:
    existing = await session_service.get_session(
        app_name=APP_NAME,
        user_id="web-ui",
        session_id=session_id,
    )
    if existing:
        return
    await session_service.create_session(
        app_name=APP_NAME,
        user_id="web-ui",
        session_id=session_id,
    )


def content_to_text(content: Optional[types.Content]) -> str:
    if not content:
        return ""
    parts = []
    if content.parts:
        for part in content.parts:
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
    return "\n".join([p for p in parts if p]) or (getattr(content, "text", "") or "")


async def run_agent_chat(message: str, session_id: str, model: str) -> str:
    runner = get_runner(model)
    await ensure_session(session_id)

    final_response = ""
    user_message = types.Content(role="user", parts=[types.Part(text=message)])

    async for event in runner.run_async(
        user_id="web-ui",
        session_id=session_id,
        new_message=user_message,
    ):
        if event.author != "web-ui" and event.is_final_response():
            final_response = content_to_text(event.content) or final_response

    return final_response or "The agent did not return any text."


async def stream_agent_chat(message: str, session_id: str, model: str) -> AsyncIterator[Dict[str, Any]]:
    """Async generator that yields SSE-style event dicts as the agent processes a request.

    Event types:
      {"type": "thinking",    "content": "<model text>"}
      {"type": "tool_call",   "name": "<tool>", "args": {}}
      {"type": "tool_result", "name": "<tool>", "content": "<output>"}
      {"type": "done",        "content": "<final answer>"}
      {"type": "error",       "content": "<message>"}
    """
    try:
        runner = get_runner(model)
    except RuntimeError as exc:
        yield {"type": "error", "content": str(exc)}
        return

    await ensure_session(session_id)

    final_response = ""
    user_message = types.Content(role="user", parts=[types.Part(text=message)])

    try:
        async for event in runner.run_async(
            user_id="web-ui",
            session_id=session_id,
            new_message=user_message,
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
                    args = dict(fc.args) if fc.args else {}
                    logger.info("Tool call: %s args=%s", fc.name, args)
                    yield {"type": "tool_call", "name": fc.name, "args": args}

                elif getattr(part, "function_response", None):
                    fr = part.function_response
                    response_text = str(fr.response) if fr.response is not None else ""
                    logger.info("Tool result: %s", fr.name)
                    yield {"type": "tool_result", "name": fr.name, "content": response_text}

    except Exception as exc:
        logger.warning("stream_agent_chat error: %s", exc)
        yield {"type": "error", "content": str(exc)}
        return

    yield {"type": "done", "content": final_response or "The agent did not return any text."}
