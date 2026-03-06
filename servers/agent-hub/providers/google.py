"""Google GenAI provider — direct API, model-agnostic tool calling."""
from __future__ import annotations

import json
import logging
import os
from typing import Any, AsyncIterator, Dict, List, Optional

from config import DEFAULT_INSTRUCTION, MAX_TOOL_ITERATIONS
from conv_client import conv_client
from mcp_utils import _call_mcp_tool, _list_mcp_tools
from sub_agent import run_sub_agent

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
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
GOOGLE_MODEL: str = os.getenv("GOOGLE_MODEL", "gemini-2.0-flash")
GOOGLE_ENABLED: bool = bool(GOOGLE_API_KEY or (GOOGLE_VERTEX_PROJECT and GOOGLE_VERTEX_LOCATION))

try:
    from google import genai
    from google.genai import types as gtypes
    _GOOGLE_LIBS = True
except ImportError:
    _GOOGLE_LIBS = False
    logger.warning("google-genai not installed; Google provider unavailable.")


# ---------------------------------------------------------------------------
# Client factory
# ---------------------------------------------------------------------------

def _google_client() -> Any:
    if not _GOOGLE_LIBS:
        raise RuntimeError("google-genai library not installed.")
    if GOOGLE_API_KEY:
        return genai.Client(api_key=GOOGLE_API_KEY)
    if GOOGLE_VERTEX_PROJECT and GOOGLE_VERTEX_LOCATION:
        return genai.Client(vertexai=True, project=GOOGLE_VERTEX_PROJECT, location=GOOGLE_VERTEX_LOCATION)
    raise RuntimeError(
        "Google credentials missing. Set GOOGLE_API_KEY or GOOGLE_VERTEX_PROJECT/LOCATION."
    )


# ---------------------------------------------------------------------------
# Tool format conversion
# ---------------------------------------------------------------------------

def _to_genai_tools(tools: List[Dict[str, Any]]) -> list:
    """Convert OpenAI-style function tool defs to google.genai FunctionDeclaration list."""
    declarations = []
    for t in tools:
        fn = t.get("function", {})
        params = fn.get("parameters", {})
        declarations.append(
            gtypes.FunctionDeclaration(
                name=fn["name"],
                description=fn.get("description", ""),
                parameters=gtypes.Schema(
                    type=gtypes.Type.OBJECT,
                    properties={
                        k: gtypes.Schema(
                            type=gtypes.Type.STRING,
                            description=v.get("description", ""),
                        )
                        for k, v in params.get("properties", {}).items()
                    },
                    required=params.get("required", []),
                ),
            )
        )
    return [gtypes.Tool(function_declarations=declarations)] if declarations else []


def _messages_to_contents(messages: List[Dict[str, Any]]) -> List[Any]:
    """Convert OpenAI-style message list to google.genai Content objects (skip system)."""
    contents = []
    for m in messages:
        role = m["role"]
        text = m.get("content") or ""
        if role == "system":
            continue
        if role in ("user", "tool"):
            contents.append(gtypes.Content(role="user", parts=[gtypes.Part(text=text)]))
        elif role == "assistant":
            contents.append(gtypes.Content(role="model", parts=[gtypes.Part(text=text)]))
    return contents


# ---------------------------------------------------------------------------
# Streaming chat
# ---------------------------------------------------------------------------

async def stream_google_chat(message: str, session_id: str, model: str) -> AsyncIterator[Dict[str, Any]]:
    if not _GOOGLE_LIBS:
        yield {"type": "error", "content": "google-genai library not installed."}
        return

    try:
        client = _google_client()
    except RuntimeError as exc:
        yield {"type": "error", "content": str(exc)}
        return

    history = await conv_client.get_messages(session_id)
    messages: List[Dict[str, Any]] = (
        [{"role": "system", "content": DEFAULT_INSTRUCTION}]
        + [{"role": m["role"], "content": m["content"]} for m in history]
        + [{"role": "user", "content": message}]
    )

    tools = await _list_mcp_tools()
    genai_tools = _to_genai_tools(tools)
    system_instruction = DEFAULT_INSTRUCTION

    for iteration in range(MAX_TOOL_ITERATIONS + 1):
        contents = _messages_to_contents(messages)
        try:
            response = client.models.generate_content(
                model=model,
                contents=contents,
                config=gtypes.GenerateContentConfig(
                    system_instruction=system_instruction,
                    tools=genai_tools or None,
                ),
            )
        except Exception as exc:
            yield {"type": "error", "content": str(exc)}
            return

        candidate = response.candidates[0] if response.candidates else None
        if not candidate or not candidate.content:
            yield {"type": "done", "content": "No response from the model."}
            return

        parts = candidate.content.parts or []
        text_parts = [p.text for p in parts if getattr(p, "text", None)]
        fn_calls = [p.function_call for p in parts if getattr(p, "function_call", None)]

        content_text = "\n".join(text_parts)
        messages.append({"role": "assistant", "content": content_text})

        if content_text:
            if not fn_calls:
                # No tool calls — this is the final response
                yield {"type": "done", "content": content_text}
                return
            yield {"type": "thinking", "content": content_text}

        if not fn_calls:
            yield {"type": "done", "content": content_text or "No response from the model."}
            return

        if iteration == MAX_TOOL_ITERATIONS:
            logger.warning("MAX_TOOL_ITERATIONS reached for session %s.", session_id)
            break

        for fc in fn_calls:
            fn_name = fc.name
            fn_args = dict(fc.args) if fc.args else {}
            yield {"type": "tool_call", "name": fn_name, "args": fn_args}
            try:
                if fn_name.startswith("call_") and fn_name.endswith("_agent"):
                    agent_name = fn_name[len("call_"):]
                    tool_result = await run_sub_agent(agent_name, fn_args.get("task", ""), "google", model)
                else:
                    tool_result = await _call_mcp_tool(fn_name, fn_args)
            except Exception as exc:
                tool_result = f"Tool '{fn_name}' error: {exc}"
            yield {"type": "tool_result", "name": fn_name, "content": tool_result}
            messages.append({"role": "tool", "content": tool_result})

    # Synthesis pass after iteration cap
    contents = _messages_to_contents(messages)
    try:
        final = client.models.generate_content(
            model=model,
            contents=contents,
            config=gtypes.GenerateContentConfig(system_instruction=system_instruction),
        )
        final_parts = (final.candidates[0].content.parts or []) if final.candidates else []
        final_text = "\n".join(p.text for p in final_parts if getattr(p, "text", None))
    except Exception as exc:
        yield {"type": "error", "content": str(exc)}
        return

    yield {"type": "done", "content": final_text or "Agent completed tool execution but produced no summary."}
