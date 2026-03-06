"""
Sub-agent execution — model-agnostic.

When the root agent calls call_<name>_agent(task), these functions run a
nested agentic loop using the sub-agent's own instructions and restricted
tool set, then return the final answer as a plain string.

Works with any provider (Ollama, Azure, Google) because orchestration lives
here, not in a provider-specific SDK.
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Dict, List, Optional

import httpx

from config import MAX_TOOL_ITERATIONS, MCP_SERVER_URL
from mcp_utils import _call_mcp_tool, _list_all_mcp_tools

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Agent config cache  (fetched once from GET /agents on the MCP server)
# ---------------------------------------------------------------------------

_MCP_AGENTS_URL = MCP_SERVER_URL.rstrip("/mcp").rstrip("/") + "/agents"
_config_cache: Dict[str, Any] = {"configs": {}, "ts": 0.0, "last_error": ""}
_CONFIG_TTL = 300.0  # seconds


async def _fetch_agent_configs() -> Dict[str, Any]:
    now = time.time()
    if _config_cache["configs"] and (now - _config_cache["ts"]) < _CONFIG_TTL:
        return _config_cache["configs"]
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(_MCP_AGENTS_URL)
            resp.raise_for_status()
            agents_list = resp.json()
        configs = {a["name"]: a for a in agents_list}
        _config_cache["configs"] = configs
        _config_cache["ts"] = now
        _config_cache["last_error"] = ""
        logger.info("Fetched %d agent configs from %s", len(configs), _MCP_AGENTS_URL)
        return configs
    except Exception as exc:
        _config_cache["last_error"] = f"{type(exc).__name__}: {exc}"
        logger.warning("Could not fetch agent configs from %s: %s", _MCP_AGENTS_URL, exc)
        return _config_cache["configs"]  # return stale cache on failure


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def run_sub_agent(agent_name: str, task: str, provider: str, model: str) -> str:
    """
    Run a sub-agent for the given task.

    Fetches the agent's instructions and allowed tools from the MCP server,
    then runs a non-streaming agentic loop using the same provider/model as
    the root agent.  Returns the final text answer.
    """
    configs = await _fetch_agent_configs()
    config = configs.get(agent_name)
    if not config:
        reason = (
            f" (fetch error: {_config_cache['last_error']})" if _config_cache["last_error"]
            else f" (fetched from {_MCP_AGENTS_URL})"
        )
        return f"Unknown sub-agent '{agent_name}'. Available: {list(configs.keys())}{reason}"

    instructions: str = config["instructions"]
    allowed: set[str] = set(config["tools"])

    all_tools = await _list_all_mcp_tools()
    agent_tools = [t for t in all_tools if t["function"]["name"] in allowed]

    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": instructions},
        {"role": "user", "content": task},
    ]

    return await _run_sub_loop(provider, model, messages, agent_tools)


# ---------------------------------------------------------------------------
# Provider-specific non-streaming loops
# ---------------------------------------------------------------------------

async def _run_sub_loop(
    provider: str,
    model: str,
    messages: List[Dict[str, Any]],
    tools: List[Dict[str, Any]],
) -> str:
    if provider == "ollama":
        return await _ollama_loop(model, messages, tools)
    if provider == "azure":
        return await _azure_loop(model, messages, tools)
    if provider == "google":
        return await _google_loop(model, messages, tools)
    return f"Unknown provider '{provider}'"


async def _execute_tool_calls(
    tool_calls: list,
    messages: List[Dict[str, Any]],
    extract_name,
    extract_args,
    make_tool_msg,
) -> None:
    """Shared tool-call execution helper."""
    for tc in tool_calls:
        name = extract_name(tc)
        args = extract_args(tc)
        if not name:
            continue
        try:
            result = await _call_mcp_tool(name, args or {})
        except Exception as exc:
            result = f"Tool '{name}' error: {exc}"
        messages.append(make_tool_msg(tc, result))


# ---------------------------------------------------------------------------
# Ollama fallback helpers (mirrors providers/ollama.py — kept here to avoid
# circular imports since providers/ollama.py imports run_sub_agent from here)
# ---------------------------------------------------------------------------

def _sub_extract_inline_tool_calls(content: str) -> List[Dict[str, Any]]:
    """Extract tool calls embedded as JSON in the model's text output."""
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


def _sub_resolve_tool_name(name: str, available_tools: List[Dict[str, Any]]) -> Optional[str]:
    known = [t["function"]["name"] for t in available_tools]
    if name in known:
        return name
    matches = [n for n in known if name in n or n in name]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        req_tokens = set(name.split("_"))
        return max(matches, key=lambda n: len(req_tokens & set(n.split("_"))))
    return None


async def _sub_extract_tool_call_via_model(
    content: str,
    tools: List[Dict[str, Any]],
    client: Any,
    model: str,
) -> Optional[Dict[str, Any]]:
    if not tools:
        return None
    known_names = [t["function"]["name"] for t in tools]
    if not any(name in content for name in known_names):
        return None
    tool_specs = json.dumps([
        {"name": t["function"]["name"], "parameters": t["function"]["parameters"]}
        for t in tools
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
            logger.info("Sub-agent extracted tool call via model: name='%s'", name)
            return {"function": {"name": name, "arguments": obj.get("arguments") or {}}}
    except Exception as exc:
        logger.warning("Sub-agent model-based tool extraction failed: %s", exc)
    return None


# --- Ollama ---

async def _ollama_loop(model: str, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]) -> str:
    try:
        from ollama import AsyncClient as OllamaClient
    except ImportError:
        return "Ollama library not installed."

    import os as _os
    ollama_host = _os.getenv("OLLAMA_HOST", "http://localhost:11434")
    client = OllamaClient(host=ollama_host)
    for _ in range(MAX_TOOL_ITERATIONS + 1):
        try:
            result = await client.chat(model=model, messages=messages, tools=tools or None, stream=False)
        except Exception as exc:
            return f"Ollama error: {exc}"

        if isinstance(result, dict):
            msg = result.get("message", {})
            tcs = msg.get("tool_calls") or []
            content = msg.get("content", "")
        else:
            msg = getattr(result, "message", None)
            tcs = getattr(msg, "tool_calls", None) or []
            content = getattr(msg, "content", "") or ""

        messages.append({"role": "assistant", "content": content, "tool_calls": tcs})

        if not tcs:
            # Fallback 1: try to parse JSON tool calls embedded in text
            inline = _sub_extract_inline_tool_calls(content)
            if inline:
                tcs = inline
                messages[-1] = {"role": "assistant", "content": "", "tool_calls": inline}
            else:
                # Fallback 2: ask the model to extract the tool call from its own text
                extracted = await _sub_extract_tool_call_via_model(content, tools, client, model)
                if extracted:
                    resolved = _sub_resolve_tool_name(extracted["function"]["name"], tools)
                    if resolved:
                        extracted["function"]["name"] = resolved
                        tcs = [extracted]
                        messages[-1] = {"role": "assistant", "content": "", "tool_calls": tcs}
            if not tcs:
                return content or "No response from sub-agent."

        for tc in tcs:
            fn = tc.get("function", {}) if isinstance(tc, dict) else getattr(getattr(tc, "function", None), "__dict__", {})
            name = fn.get("name", "") if isinstance(fn, dict) else getattr(tc.function, "name", "")
            args = fn.get("arguments", {}) if isinstance(fn, dict) else getattr(tc.function, "arguments", {})
            if not name:
                continue
            resolved = _sub_resolve_tool_name(name, tools)
            if not resolved:
                messages.append({"role": "tool", "content": f"Unknown tool: '{name}'"})
                continue
            try:
                tool_result = await _call_mcp_tool(resolved, args or {})
            except Exception as exc:
                tool_result = f"Tool '{resolved}' error: {exc}"
            messages.append({"role": "tool", "content": tool_result})

    # synthesis pass
    try:
        final = await client.chat(model=model, messages=messages, tools=None, stream=False)
        return (final.get("message", {}).get("content", "") if isinstance(final, dict)
                else getattr(getattr(final, "message", None), "content", "") or "") or "Sub-agent completed."
    except Exception as exc:
        return f"Ollama synthesis error: {exc}"


# --- Azure ---

async def _azure_loop(model: str, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]) -> str:
    try:
        from openai import AsyncAzureOpenAI
    except ImportError:
        return "openai library not installed."

    import os
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "")
    api_key = os.getenv("AZURE_OPENAI_API_KEY", "")
    api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")
    if not endpoint or not api_key:
        return "Azure OpenAI not configured."

    client = AsyncAzureOpenAI(azure_endpoint=endpoint, api_key=api_key, api_version=api_version)
    for _ in range(MAX_TOOL_ITERATIONS + 1):
        try:
            response = await client.chat.completions.create(
                model=model, messages=messages, tools=tools or None,
                tool_choice="auto" if tools else None,
            )
        except Exception as exc:
            return f"Azure error: {exc}"

        msg = response.choices[0].message
        tcs = msg.tool_calls or []
        content = msg.content or ""

        assistant_dict: Dict[str, Any] = {"role": "assistant", "content": content}
        if tcs:
            assistant_dict["tool_calls"] = [
                {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in tcs
            ]
        messages.append(assistant_dict)

        if not tcs:
            return content or "No response from sub-agent."

        for tc in tcs:
            args = json.loads(tc.function.arguments or "{}")
            try:
                tool_result = await _call_mcp_tool(tc.function.name, args)
            except Exception as exc:
                tool_result = f"Tool '{tc.function.name}' error: {exc}"
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": tool_result})

    try:
        final = await client.chat.completions.create(model=model, messages=messages, tools=None)
        return final.choices[0].message.content or "Sub-agent completed."
    except Exception as exc:
        return f"Azure synthesis error: {exc}"


# --- Google (direct genai, no ADK) ---

async def _google_loop(model: str, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]) -> str:
    try:
        from google import genai
        from google.genai import types as gtypes
    except ImportError:
        return "google-genai library not installed."

    import os
    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GOOGLE_GENAI_API_KEY")
    vertex_project = os.getenv("GOOGLE_VERTEX_PROJECT") or os.getenv("VERTEX_PROJECT")
    vertex_location = os.getenv("GOOGLE_VERTEX_LOCATION") or os.getenv("VERTEX_LOCATION")

    if api_key:
        client = genai.Client(api_key=api_key)
    elif vertex_project and vertex_location:
        client = genai.Client(vertexai=True, project=vertex_project, location=vertex_location)
    else:
        return "Google credentials not configured."

    # Convert OpenAI-style messages to Google genai Content objects
    def _to_contents(msgs):
        contents = []
        for m in msgs:
            role = m["role"]
            if role == "system":
                continue  # handled via system_instruction
            if role in ("user", "tool"):
                contents.append(gtypes.Content(role="user", parts=[gtypes.Part(text=m["content"])]))
            elif role == "assistant":
                contents.append(gtypes.Content(role="model", parts=[gtypes.Part(text=m.get("content") or "")]))
        return contents

    # Extract system instruction
    system_instruction = next((m["content"] for m in messages if m["role"] == "system"), "")

    # Build genai tools
    genai_tools = _build_genai_tools(tools)

    for _ in range(MAX_TOOL_ITERATIONS + 1):
        contents = _to_contents(messages)
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
            return f"Google genai error: {exc}"

        candidate = response.candidates[0] if response.candidates else None
        if not candidate or not candidate.content:
            return "No response from sub-agent."

        parts = candidate.content.parts or []
        text_parts = [p.text for p in parts if getattr(p, "text", None)]
        fn_calls = [p.function_call for p in parts if getattr(p, "function_call", None)]

        text = "\n".join(text_parts)
        messages.append({"role": "assistant", "content": text})

        if not fn_calls:
            return text or "No response from sub-agent."

        for fc in fn_calls:
            args = dict(fc.args) if fc.args else {}
            try:
                tool_result = await _call_mcp_tool(fc.name, args)
            except Exception as exc:
                tool_result = f"Tool '{fc.name}' error: {exc}"
            messages.append({"role": "tool", "content": tool_result})

    return "Sub-agent reached tool iteration limit."


def _build_genai_tools(tools: List[Dict[str, Any]]) -> list:
    """Convert OpenAI-style tool defs to google.genai FunctionDeclaration list."""
    try:
        from google.genai import types as gtypes
    except ImportError:
        return []
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
                        k: gtypes.Schema(type=gtypes.Type.STRING, description=v.get("description", ""))
                        for k, v in params.get("properties", {}).items()
                    },
                    required=params.get("required", []),
                ),
            )
        )
    return [gtypes.Tool(function_declarations=declarations)] if declarations else []
