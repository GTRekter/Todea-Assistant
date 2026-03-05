"""Azure OpenAI provider — configuration and streaming chat."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, AsyncIterator, Dict, List

from fastapi import HTTPException

from config import DEFAULT_INSTRUCTION, MAX_TOOL_ITERATIONS
from conv_client import conv_client
from mcp_utils import _call_mcp_tool, _list_mcp_tools

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration globals (may be updated by kubernetes._refresh_provider_config_from_secret)
# ---------------------------------------------------------------------------

AZURE_ENDPOINT: str = os.getenv("AZURE_OPENAI_ENDPOINT", "")
AZURE_API_KEY: str = os.getenv("AZURE_OPENAI_API_KEY", "")
AZURE_DEPLOYMENT: str = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
AZURE_API_VERSION: str = os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")
AZURE_ENABLED: bool = bool(AZURE_ENDPOINT and AZURE_API_KEY)

try:
    from openai import AsyncAzureOpenAI
    _AZURE_LIBS = True
except ImportError:
    _AZURE_LIBS = False
    logger.warning("openai not installed; Azure provider unavailable.")

_azure_lock = asyncio.Lock()


def _azure_client() -> Any:
    if not _AZURE_LIBS:
        raise HTTPException(status_code=503, detail="openai library not installed.")
    if not AZURE_ENDPOINT or not AZURE_API_KEY:
        raise HTTPException(status_code=503, detail="Azure OpenAI not configured. Set AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY.")
    return AsyncAzureOpenAI(azure_endpoint=AZURE_ENDPOINT, api_key=AZURE_API_KEY, api_version=AZURE_API_VERSION)


async def stream_azure_chat(message: str, session_id: str, model: str) -> AsyncIterator[Dict[str, Any]]:
    try:
        client = _azure_client()
    except HTTPException as exc:
        yield {"type": "error", "content": exc.detail}
        return

    history = await conv_client.get_messages(session_id)
    messages: List[Dict[str, Any]] = (
        [{"role": "system", "content": DEFAULT_INSTRUCTION}]
        + [{"role": m["role"], "content": m["content"]} for m in history]
        + [{"role": "user", "content": message}]
    )

    tools = await _list_mcp_tools()

    for iteration in range(MAX_TOOL_ITERATIONS + 1):
        try:
            response = await client.chat.completions.create(
                model=model, messages=messages, tools=tools or None, tool_choice="auto" if tools else None
            )
        except Exception as exc:
            yield {"type": "error", "content": str(exc)}
            return

        msg = response.choices[0].message
        tool_calls = msg.tool_calls or []
        content = msg.content or ""

        assistant_dict: Dict[str, Any] = {"role": "assistant", "content": content}
        if tool_calls:
            assistant_dict["tool_calls"] = [
                {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in tool_calls
            ]
        messages.append(assistant_dict)

        if content:
            yield {"type": "thinking", "content": content}

        if not tool_calls:
            yield {"type": "done", "content": content or "No response from the model."}
            return

        if iteration == MAX_TOOL_ITERATIONS:
            logger.warning("MAX_TOOL_ITERATIONS reached for session %s.", session_id)
            messages.append({"role": "tool", "tool_call_id": tool_calls[0].id, "content": "Tool iteration limit reached."})
            break

        for tc in tool_calls:
            fn_args = json.loads(tc.function.arguments or "{}")
            yield {"type": "tool_call", "name": tc.function.name, "args": fn_args}
            try:
                tool_result = await _call_mcp_tool(tc.function.name, fn_args)
            except Exception as exc:
                tool_result = f"Tool '{tc.function.name}' error: {exc}"
            yield {"type": "tool_result", "name": tc.function.name, "content": tool_result}
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": tool_result})

    try:
        final = await client.chat.completions.create(model=model, messages=messages, tools=None)
        final_content = final.choices[0].message.content or "Agent completed tool execution but produced no summary."
    except Exception as exc:
        yield {"type": "error", "content": str(exc)}
        return
    yield {"type": "done", "content": final_content}
