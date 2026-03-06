"""Ollama provider — configuration, model listing, tool extraction, and streaming chat."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from typing import Any, AsyncIterator, Dict, List, Optional

from config import DEFAULT_INSTRUCTION, MAX_TOOL_ITERATIONS
from conv_client import conv_client
from mcp_utils import _call_mcp_tool, _list_mcp_tools
from sub_agent import run_sub_agent

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration globals (may be updated by kubernetes._refresh_provider_config_from_secret)
# ---------------------------------------------------------------------------

OLLAMA_HOST: str = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_ENABLED: bool = "OLLAMA_HOST" in os.environ  # True only if explicitly configured
OLLAMA_MODEL: str = os.getenv("AGENT_MODEL_OLLAMA", os.getenv("OLLAMA_MODEL", "llama3.1:8b"))
MODEL_REFRESH_SECONDS: int = int(os.getenv("MODEL_REFRESH_SECONDS", "60"))

try:
    from ollama import AsyncClient as OllamaClient, ResponseError as OllamaResponseError
    _OLLAMA_LIBS = True
except ImportError:
    _OLLAMA_LIBS = False
    logger.warning("ollama not installed; Ollama provider unavailable.")

# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------

_ollama_lock = asyncio.Lock()
_model_cache: Dict[str, Any] = {"names": [], "ts": 0.0}


async def _list_ollama_models(force: bool = False) -> List[str]:
    if not _OLLAMA_LIBS:
        return []
    now = time.time()
    if not _model_cache["names"] or force or (now - _model_cache["ts"] > MODEL_REFRESH_SECONDS):
        try:
            response = await OllamaClient(host=OLLAMA_HOST).list()
        except Exception as exc:
            logger.warning("Cannot reach Ollama at %s: %s", OLLAMA_HOST, exc)
            return _model_cache["names"]
        if isinstance(response, dict):
            items = response.get("models", [])
            names = [item.get("name") or item.get("model") for item in items if item.get("name") or item.get("model")]
        else:
            names = [getattr(m, "model", None) or getattr(m, "name", None) for m in getattr(response, "models", [])]
            names = [n for n in names if n]
        _model_cache["names"] = names
        _model_cache["ts"] = now
    return _model_cache["names"]


# ---------------------------------------------------------------------------
# Tool extraction helpers
# ---------------------------------------------------------------------------

def _extract_inline_tool_calls(content: str) -> List[Dict[str, Any]]:
    calls: List[Dict[str, Any]] = []
    for m in re.finditer(r"```(?:json)?\s*(\{.*?})\s*```", content, re.DOTALL):
        try:
            obj = json.loads(m.group(1))
            name = obj.get("name") or (obj.get("function") or {}).get("name")
            args = obj.get("parameters") or obj.get("arguments") or (obj.get("function") or {}).get("arguments") or {}
            if name and isinstance(name, str):
                calls.append({"function": {"name": name, "arguments": args}})
        except (json.JSONDecodeError, AttributeError):
            pass
    if calls:
        return calls
    depth, start = 0, -1
    for i, ch in enumerate(content):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    obj = json.loads(content[start: i + 1])
                    name = obj.get("name") or (obj.get("function") or {}).get("name")
                    args = obj.get("parameters") or obj.get("arguments") or (obj.get("function") or {}).get("arguments") or {}
                    if name and isinstance(name, str):
                        calls.append({"function": {"name": name, "arguments": args}})
                except (json.JSONDecodeError, AttributeError):
                    pass
                start = -1
    return calls


def _resolve_tool_name(name: str, available_tools: List[Dict[str, Any]]) -> Optional[str]:
    known = [t["function"]["name"] for t in available_tools]
    if name in known:
        return name
    matches = [n for n in known if name in n or n in name]
    if len(matches) == 1:
        logger.info("Resolved tool '%s' -> '%s'", name, matches[0])
        return matches[0]
    if len(matches) > 1:
        req_tokens = set(name.split("_"))
        best = max(matches, key=lambda n: len(req_tokens & set(n.split("_"))))
        logger.info("Resolved tool '%s' -> '%s' (best of %s)", name, best, matches)
        return best
    logger.warning("Cannot resolve tool name '%s'. Known: %s", name, known)
    return None


def _strip_invalid_args(fn_name: str, fn_args: Dict[str, Any], available_tools: List[Dict[str, Any]]) -> Dict[str, Any]:
    for t in available_tools:
        if t["function"]["name"] == fn_name:
            valid_props = set(t["function"].get("parameters", {}).get("properties", {}).keys())
            if valid_props:
                stripped = {k: v for k, v in fn_args.items() if k in valid_props}
                if len(stripped) != len(fn_args):
                    logger.info("Stripped invalid args for tool '%s': %s", fn_name, set(fn_args) - valid_props)
                return stripped
            break
    return fn_args


async def _extract_tool_call_via_model(
    content: str,
    tools_for_ollama: List[Dict[str, Any]],
    client: Any,
    model: str,
) -> Optional[Dict[str, Any]]:
    if not tools_for_ollama:
        return None
    known_names = [t["function"]["name"] for t in tools_for_ollama]
    if not any(name in content for name in known_names):
        return None
    tool_specs = json.dumps([
        {"name": t["function"]["name"], "parameters": t["function"]["parameters"]}
        for t in tools_for_ollama
    ])
    extraction_messages = [
        {
            "role": "system",
            "content": (
                "You are a JSON extractor. Identify which tool should be called and with what arguments. "
                'Output ONLY a JSON object: {"name": "<tool_name>", "arguments": {<key: value>}}. '
                "No prose, no markdown, just the JSON object."
            ),
        },
        {
            "role": "user",
            "content": f"Assistant message:\n{content}\n\nAvailable tools:\n{tool_specs}\n\nExtract the tool call:",
        },
    ]
    try:
        result = await client.chat(
            model=model,
            messages=extraction_messages,
            format={"type": "object", "properties": {"name": {"type": "string"}, "arguments": {"type": "object"}}, "required": ["name", "arguments"]},
            stream=False,
        )
        raw = (result.get("message", {}).get("content", "") if isinstance(result, dict)
               else getattr(getattr(result, "message", None), "content", "") or "")
        obj = json.loads(raw)
        name = obj.get("name", "")
        if name and isinstance(name, str):
            logger.info("Extracted tool call via model: name='%s'", name)
            return {"function": {"name": name, "arguments": obj.get("arguments") or {}}}
    except Exception as exc:
        logger.warning("Model-based tool extraction failed: %s", exc)
    return None


# ---------------------------------------------------------------------------
# Streaming chat
# ---------------------------------------------------------------------------

async def stream_ollama_chat(message: str, session_id: str, model: str) -> AsyncIterator[Dict[str, Any]]:
    if not _OLLAMA_LIBS:
        yield {"type": "error", "content": "ollama library not installed."}
        return

    history = await conv_client.get_messages(session_id)
    messages: List[Dict[str, Any]] = (
        [{"role": "system", "content": DEFAULT_INSTRUCTION}]
        + [{"role": m["role"], "content": m["content"]} for m in history]
        + [{"role": "user", "content": message}]
    )

    tools_for_ollama = await _list_mcp_tools()
    if tools_for_ollama:
        messages[0]["content"] += "\n\nAvailable tools (use EXACT names): " + ", ".join(
            t["function"]["name"] for t in tools_for_ollama
        )

    client = OllamaClient(host=OLLAMA_HOST)

    for iteration in range(MAX_TOOL_ITERATIONS + 1):
        try:
            result = await client.chat(model=model, messages=messages, tools=tools_for_ollama or None, stream=False)
        except Exception as exc:
            yield {"type": "error", "content": str(exc)}
            return

        if isinstance(result, dict):
            msg_obj = result.get("message", {})
            tool_calls_raw = msg_obj.get("tool_calls") or []
            content = msg_obj.get("content", "")
            assistant_msg: Any = {"role": "assistant", "content": content}
            if tool_calls_raw:
                assistant_msg["tool_calls"] = tool_calls_raw
        else:
            msg_obj = getattr(result, "message", None)
            tool_calls_raw = getattr(msg_obj, "tool_calls", None) or []
            content = getattr(msg_obj, "content", "") or ""
            assistant_msg = msg_obj

        messages.append(assistant_msg)

        if content:
            yield {"type": "thinking", "content": content}

        if not tool_calls_raw:
            if iteration < MAX_TOOL_ITERATIONS:
                inline = _extract_inline_tool_calls(content)
                if inline:
                    tool_calls_raw = inline
                    messages[-1] = {"role": "assistant", "content": "", "tool_calls": inline}
                if not tool_calls_raw:
                    extracted = await _extract_tool_call_via_model(content, tools_for_ollama, client, model)
                    if extracted:
                        resolved = _resolve_tool_name(extracted["function"]["name"], tools_for_ollama)
                        if resolved:
                            extracted["function"]["name"] = resolved
                            tool_calls_raw = [extracted]
                            messages[-1] = {"role": "assistant", "content": "", "tool_calls": tool_calls_raw}
            if not tool_calls_raw:
                yield {"type": "done", "content": content or "The model did not return any text."}
                return

        if iteration == MAX_TOOL_ITERATIONS:
            logger.warning("MAX_TOOL_ITERATIONS reached for session %s.", session_id)
            messages.append({"role": "tool", "content": "Tool iteration limit reached."})
            break

        for tc in tool_calls_raw:
            fn_name = (tc.get("function", {}).get("name", "") if isinstance(tc, dict) else getattr(getattr(tc, "function", None), "name", ""))
            fn_args = (tc.get("function", {}).get("arguments", {}) if isinstance(tc, dict) else getattr(getattr(tc, "function", None), "arguments", {}))
            if not fn_name:
                continue
            resolved = _resolve_tool_name(fn_name, tools_for_ollama)
            if not resolved:
                messages.append({"role": "tool", "content": f"Unknown tool: '{fn_name}'"})
                continue
            fn_args = _strip_invalid_args(resolved, fn_args or {}, tools_for_ollama)
            yield {"type": "tool_call", "name": resolved, "args": fn_args}
            try:
                if resolved.startswith("call_") and resolved.endswith("_agent"):
                    agent_name = resolved[len("call_"):]
                    tool_result = await run_sub_agent(agent_name, fn_args.get("task", ""), "ollama", model)
                else:
                    tool_result = await _call_mcp_tool(resolved, fn_args)
            except Exception as exc:
                tool_result = f"Tool '{resolved}' error: {exc}"
            yield {"type": "tool_result", "name": resolved, "content": tool_result}
            messages.append({"role": "tool", "content": tool_result})

    # Synthesis pass after iteration cap.
    try:
        final = await client.chat(model=model, messages=messages, tools=None, stream=False)
        final_content = (final.get("message", {}).get("content", "") if isinstance(final, dict)
                         else getattr(getattr(final, "message", None), "content", "") or "")
    except Exception as exc:
        yield {"type": "error", "content": str(exc)}
        return
    yield {"type": "done", "content": str(final_content) if final_content else "Agent completed tool execution but produced no summary."}
