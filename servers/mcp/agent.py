"""Google ADK agent session management and chat runner."""
from __future__ import annotations

import asyncio
from typing import Optional

from google.adk.runners import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.genai import types

from config import AGENT_APP_NAME, AGENT_SESSION_ID, AGENT_USER_ID
from linkerd_agent.app import root_agent as linkerd_agent  # type: ignore

session_service = InMemorySessionService()
runner = Runner(
    app_name=AGENT_APP_NAME,
    agent=linkerd_agent,
    session_service=session_service,
)
agent_lock = asyncio.Lock()


async def ensure_agent_session(session_id: str) -> None:
    existing = await session_service.get_session(
        app_name=AGENT_APP_NAME,
        user_id=AGENT_USER_ID,
        session_id=session_id,
    )
    if existing:
        return
    await session_service.create_session(
        app_name=AGENT_APP_NAME,
        user_id=AGENT_USER_ID,
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
                parts.append(
                    f"[function response] {part.function_response.name}: "
                    f"{part.function_response.response}"
                )
            elif getattr(part, "code_execution_result", None):
                result = part.code_execution_result
                output = getattr(result, "output", None) or getattr(result, "stdout", None)
                if output:
                    parts.append(str(output))
    return "\n".join([p for p in parts if p]) or (getattr(content, "text", "") or "")


async def run_agent_chat(message: str, session_id: str) -> str:
    await ensure_agent_session(session_id)
    final_response = ""
    user_message = types.Content(role="user", parts=[types.Part(text=message)])

    async for event in runner.run_async(
        user_id=AGENT_USER_ID,
        session_id=session_id,
        new_message=user_message,
    ):
        if event.author != AGENT_USER_ID and event.is_final_response():
            final_response = content_to_text(event.content) or final_response

    return final_response or "The agent did not return any text."
