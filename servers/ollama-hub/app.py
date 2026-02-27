import asyncio
import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastmcp import Client as MCPClient
from pydantic import BaseModel, Field
from ollama import AsyncClient, ResponseError
import httpx

load_dotenv()

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Configuration ---------------------------------------------------------------
ALLOW_ORIGINS = [origin.strip() for origin in os.getenv("ALLOW_ORIGINS", "*").split(",") if origin.strip()]
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("AGENT_MODEL_OLLAMA", os.getenv("OLLAMA_MODEL", "llama3.1:8b"))
PORT = int(os.getenv("PORT", "3200"))
MODEL_REFRESH_SECONDS = int(os.getenv("MODEL_REFRESH_SECONDS", "60"))
MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:3002/mcp")
TOOL_REFRESH_SECONDS = int(os.getenv("TOOL_REFRESH_SECONDS", "300"))
MAX_TOOL_ITERATIONS = int(os.getenv("MAX_TOOL_ITERATIONS", "10"))
CONVERSATION_HUB_URL = os.getenv("CONVERSATION_HUB_URL", "http://localhost:3300")
PROVIDER_ID = "ollama"
DEFAULT_INSTRUCTION = os.getenv(
    "DEFAULT_INSTRUCTION",
    (
        "You are the Todea workspace assistant. Think out loud, then answer concisely.\n"
        "You have tools for managing Buoyant Enterprise Linkerd (BEL) on Kubernetes.\n\n"
        "TOOL CALL RULES — follow these exactly:\n"
        "- Status / health check: call 'linkerd_check' or 'helm_status'. No arguments needed for linkerd_check.\n"
        "- Install Linkerd: follow this sequence in order, stop on any error:\n"
        "    1. helm_repo_add                — call with NO arguments (defaults are correct)\n"
        "    2. install_gateway_api_crds     — pass 'version' (e.g. '2.19.4')\n"
        "    3. helm_install_linkerd_crds    — pass 'version'\n"
        "    4. install_linkerd_control_plane — pass 'version' and 'license_key' ONLY\n"
        "    5. linkerd_check                — call with NO arguments to verify\n"
        "NEVER call generate_certificates or helm_install_linkerd_control_plane directly during an install — use install_linkerd_control_plane instead.\n"
        "Before starting an install, ask the user for the BEL version and license key if not provided.\n"
        "- Upgrade Linkerd: call helm_repo_add (no args), then helm_upgrade_linkerd.\n"
        "- Uninstall: call helm_status first to discover release names, then helm_uninstall_linkerd.\n\n"
        "NEVER call helm_*, linkerd_*, install_*, or generate_* tools in a different order than shown above.\n"
        "NEVER use the 'chat' tool.\n"
        "When calling any tool with no required arguments, pass an empty argument list."
    ),
)

app = FastAPI(title="Ollama Hub Service")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOW_ORIGINS or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Models ---------------------------------------------------------------------
class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    model: Optional[str] = None


class ChatResponse(BaseModel):
    content: str
    provider: str
    session_id: str


class ConversationMessage(BaseModel):
    role: str
    content: str
    timestamp: float


class Conversation(BaseModel):
    id: str
    title: str
    model: str
    created_at: float
    updated_at: float
    message_count: int = 0
    messages: List[ConversationMessage] = Field(default_factory=list)


class ConversationSummary(BaseModel):
    id: str
    title: str
    model: str
    created_at: float
    updated_at: float
    message_count: int = 0


class ConversationListResponse(BaseModel):
    conversations: List[ConversationSummary]


class ConversationCreateRequest(BaseModel):
    title: Optional[str] = None
    model: Optional[str] = None


class ConversationUpdateRequest(BaseModel):
    title: str = Field(..., min_length=1)


class SettingsResponse(BaseModel):
    status: str
    message: str


class ClusterSettingsRequest(BaseModel):
    kube_server: str = ""


class ClusterSettingsResponse(BaseModel):
    kube_server: str


# Conversation Hub client ----------------------------------------------------

class ConversationHubClient:
    """Thin async HTTP client for the conversation-hub service."""

    def __init__(self, base_url: str) -> None:
        self._base = base_url.rstrip("/")

    async def ensure(self, conversation_id: str, model: str, title: Optional[str] = None) -> Dict[str, Any]:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._base}/conversations/ensure",
                json={"id": conversation_id, "model": model, "title": title},
            )
            resp.raise_for_status()
            return resp.json()

    async def append_message(self, conversation_id: str, role: str, content: str) -> None:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._base}/conversations/{conversation_id}/messages",
                json={"role": role, "content": content},
            )
            resp.raise_for_status()

    async def get_messages(self, conversation_id: str) -> List[Dict[str, Any]]:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{self._base}/conversations/{conversation_id}/messages")
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            return resp.json()

    async def list(self) -> Dict[str, Any]:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{self._base}/conversations")
            resp.raise_for_status()
            return resp.json()

    async def create(self, title: Optional[str], model: str) -> Dict[str, Any]:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._base}/conversations",
                json={"title": title, "model": model},
            )
            resp.raise_for_status()
            return resp.json()

    async def get(self, conversation_id: str) -> Dict[str, Any]:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{self._base}/conversations/{conversation_id}")
            if resp.status_code == 404:
                raise KeyError(conversation_id)
            resp.raise_for_status()
            return resp.json()

    async def update_title(self, conversation_id: str, title: str) -> Dict[str, Any]:
        async with httpx.AsyncClient() as client:
            resp = await client.patch(
                f"{self._base}/conversations/{conversation_id}",
                json={"title": title},
            )
            if resp.status_code == 404:
                raise KeyError(conversation_id)
            resp.raise_for_status()
            return resp.json()

    async def delete(self, conversation_id: str) -> None:
        async with httpx.AsyncClient() as client:
            resp = await client.delete(f"{self._base}/conversations/{conversation_id}")
            if resp.status_code == 404:
                raise KeyError(conversation_id)
            resp.raise_for_status()


conv_client = ConversationHubClient(CONVERSATION_HUB_URL)

# State ----------------------------------------------------------------------
chat_lock = asyncio.Lock()
_model_cache: Dict[str, Any] = {"names": [], "ts": 0.0}
_tool_cache: Dict[str, Any] = {"tools": [], "ts": 0.0}


# Helpers --------------------------------------------------------------------
async def _list_models(force: bool = False) -> List[str]:
    now = time.time()
    if not _model_cache["names"] or force or (now - _model_cache["ts"] > MODEL_REFRESH_SECONDS):
        try:
            response = await AsyncClient(host=OLLAMA_HOST).list()
        except ResponseError as exc:  # type: ignore
            raise HTTPException(status_code=502, detail=f"Ollama list failed: {exc}") from exc
        except Exception as exc:  # pragma: no cover - defensive
            raise HTTPException(status_code=502, detail=f"Failed to reach Ollama at {OLLAMA_HOST}: {exc}") from exc

        if isinstance(response, dict):
            items = response.get("models", [])
            names = [item.get("name") or item.get("model") for item in items if item.get("name") or item.get("model")]
        else:
            names = [getattr(m, "model", None) or getattr(m, "name", None) for m in getattr(response, "models", [])]
            names = [n for n in names if n]
        if not names:
            raise HTTPException(status_code=400, detail="No models installed on the Ollama host. Use 'ollama pull <model>'.")
        _model_cache["names"] = names
        _model_cache["ts"] = now
    return _model_cache["names"]


# Tools that Ollama should never call directly (they require Gemini or other infrastructure).
_EXCLUDED_TOOLS = {"chat"}


async def _list_mcp_tools(force: bool = False) -> List[Dict[str, Any]]:
    """Fetch the MCP tool list and convert to Ollama format. Cached for TOOL_REFRESH_SECONDS.
    Returns [] if the MCP server is unreachable (graceful degradation)."""
    now = time.time()
    if not _tool_cache["tools"] or force or (now - _tool_cache["ts"] > TOOL_REFRESH_SECONDS):
        try:
            async with MCPClient(MCP_SERVER_URL) as mcp:
                raw_tools = await mcp.list_tools()
            _tool_cache["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description or "",
                        "parameters": t.inputSchema or {"type": "object", "properties": {}},
                    },
                }
                for t in raw_tools
                if t.name not in _EXCLUDED_TOOLS
            ]
            _tool_cache["ts"] = now
            logger.info("Loaded %d MCP tools from %s", len(_tool_cache["tools"]), MCP_SERVER_URL)
        except Exception as exc:
            logger.warning("MCP unreachable; tool calling disabled. Error: %s", exc)
            # Do NOT update ts so the next request retries immediately.
    return _tool_cache["tools"]


async def _call_mcp_tool(tool_name: str, arguments: Dict[str, Any]) -> str:
    """Execute a single MCP tool and return its output as a string."""
    async with MCPClient(MCP_SERVER_URL) as mcp:
        result = await mcp.call_tool(tool_name, arguments)
    if result.content:
        texts = [b.text for b in result.content if hasattr(b, "text") and b.text]
        if texts:
            return "\n".join(texts)
    if result.data is not None:
        return str(result.data)
    return repr(result)


def _extract_inline_tool_calls(content: str) -> List[Dict[str, Any]]:
    """Extract tool calls that a model embedded as JSON text in its content.

    Smaller models often output {"name": "...", "parameters": {...}} as plain text
    instead of using the structured tool_calls field. This parser finds those objects
    and normalises them into the same format as structured tool_calls.
    """
    calls: List[Dict[str, Any]] = []

    # 1. Try JSON inside code blocks first (higher confidence).
    for m in re.finditer(r"```(?:json)?\s*(\{.*?})\s*```", content, re.DOTALL):
        try:
            obj = json.loads(m.group(1))
            name = obj.get("name") or (obj.get("function") or {}).get("name")
            args = (
                obj.get("parameters")
                or obj.get("arguments")
                or (obj.get("function") or {}).get("arguments")
                or {}
            )
            if name and isinstance(name, str):
                calls.append({"function": {"name": name, "arguments": args}})
        except (json.JSONDecodeError, AttributeError):
            pass
    if calls:
        return calls

    # 2. Scan bare text for top-level JSON objects with a "name" key.
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
                    obj = json.loads(content[start : i + 1])
                    name = obj.get("name") or (obj.get("function") or {}).get("name")
                    args = (
                        obj.get("parameters")
                        or obj.get("arguments")
                        or (obj.get("function") or {}).get("arguments")
                        or {}
                    )
                    if name and isinstance(name, str):
                        calls.append({"function": {"name": name, "arguments": args}})
                except (json.JSONDecodeError, AttributeError):
                    pass
                start = -1
    return calls


def _resolve_tool_name(name: str, available_tools: List[Dict[str, Any]]) -> Optional[str]:
    """Resolve a (possibly hallucinated) tool name to a real MCP tool name.

    Tries exact match first, then falls back to substring / token overlap matching.
    Returns None if no reasonable match is found.
    """
    known = [t["function"]["name"] for t in available_tools]
    if name in known:
        return name
    # Substring match: find tools whose name contains the requested name or vice-versa.
    matches = [n for n in known if name in n or n in name]
    if len(matches) == 1:
        logger.info("Resolved tool '%s' -> '%s'", name, matches[0])
        return matches[0]
    if len(matches) > 1:
        # Pick the one with the most token overlap (split on underscore).
        req_tokens = set(name.split("_"))
        best = max(matches, key=lambda n: len(req_tokens & set(n.split("_"))))
        logger.info("Resolved tool '%s' -> '%s' (best of %s)", name, best, matches)
        return best
    logger.warning("Cannot resolve tool name '%s'. Known tools: %s", name, known)
    return None


async def _extract_tool_call_via_model(
    content: str,
    tools_for_ollama: List[Dict[str, Any]],
    client: AsyncClient,
    model: str,
) -> Optional[Dict[str, Any]]:
    """Last-resort extraction: re-ask the model to output its tool call intent as JSON.

    Used when the model mentioned a known tool but formatted the call wrong (e.g. as a
    bash command or prose).  Runs a short focused call with Ollama's constrained JSON
    format mode so the output is guaranteed to be parseable.
    """
    if not tools_for_ollama:
        return None
    known_names = [t["function"]["name"] for t in tools_for_ollama]
    if not any(name in content for name in known_names):
        return None  # No known tool mentioned — nothing to extract.

    tool_specs = json.dumps(
        [
            {"name": t["function"]["name"], "parameters": t["function"]["parameters"]}
            for t in tools_for_ollama
        ]
    )
    extraction_messages = [
        {
            "role": "system",
            "content": (
                "You are a JSON extractor. "
                "Identify which tool should be called and with what arguments. "
                'Output ONLY a JSON object: {"name": "<tool_name>", "arguments": {<key: value>}}. '
                "No prose, no markdown, just the JSON object."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Assistant message:\n{content}\n\n"
                f"Available tools (with parameter schemas):\n{tool_specs}\n\n"
                "Extract the tool call:"
            ),
        },
    ]
    try:
        result = await client.chat(
            model=model,
            messages=extraction_messages,
            format={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "arguments": {"type": "object"},
                },
                "required": ["name", "arguments"],
            },
            stream=False,
        )
        if isinstance(result, dict):
            raw = result.get("message", {}).get("content", "")
        else:
            msg = getattr(result, "message", None)
            raw = getattr(msg, "content", "") if msg else ""
        obj = json.loads(raw)
        name = obj.get("name", "")
        args = obj.get("arguments") or {}
        if name and isinstance(name, str):
            logger.info("Extracted tool call via model: name='%s' args=%s", name, args)
            return {"function": {"name": name, "arguments": args}}
    except Exception as exc:
        logger.warning("Model-based tool extraction failed: %s", exc)
    return None


def _strip_invalid_args(
    fn_name: str,
    fn_args: Dict[str, Any],
    available_tools: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Remove argument keys not in the tool's JSON Schema to prevent Pydantic validation errors.

    When a model passes wrong parameter names (e.g. 'repo-url' instead of 'repo_url'),
    FastMCP raises an 'Unexpected keyword argument' error. Stripping the invalid keys
    lets tools with all-optional parameters succeed with their defaults.
    """
    for t in available_tools:
        if t["function"]["name"] == fn_name:
            valid_props = set(t["function"].get("parameters", {}).get("properties", {}).keys())
            if valid_props:
                stripped = {k: v for k, v in fn_args.items() if k in valid_props}
                if len(stripped) != len(fn_args):
                    logger.info(
                        "Stripped invalid args for tool '%s': %s",
                        fn_name,
                        set(fn_args) - valid_props,
                    )
                return stripped
            break
    return fn_args


async def _history_for_session(session_id: str) -> List[Dict[str, str]]:
    messages = await conv_client.get_messages(session_id)
    return [{"role": m["role"], "content": m["content"]} for m in messages]


async def run_ollama_chat(message: str, session_id: str, model: str) -> str:
    history = await _history_for_session(session_id)
    messages: List[Dict[str, Any]] = (
        [{"role": "system", "content": DEFAULT_INSTRUCTION}]
        + history
        + [{"role": "user", "content": message}]
    )

    tools_for_ollama = await _list_mcp_tools()

    # Include exact tool names in the system message so the model doesn't hallucinate them.
    if tools_for_ollama:
        tool_names_hint = "Available tools (use EXACT names): " + ", ".join(
            t["function"]["name"] for t in tools_for_ollama
        )
        messages[0]["content"] = messages[0]["content"] + "\n\n" + tool_names_hint

    client = AsyncClient(host=OLLAMA_HOST)

    for iteration in range(MAX_TOOL_ITERATIONS + 1):
        try:
            result = await client.chat(
                model=model,
                messages=messages,
                tools=tools_for_ollama or None,
                stream=False,
            )
        except ResponseError as exc:  # type: ignore
            raise HTTPException(status_code=502, detail=f"Ollama chat failed: {exc}") from exc
        except Exception as exc:  # pragma: no cover - defensive
            raise HTTPException(status_code=502, detail=f"Failed to reach Ollama at {OLLAMA_HOST}: {exc}") from exc

        # Normalise: handle both Pydantic object and dict responses.
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

        if not tool_calls_raw:
            if iteration < MAX_TOOL_ITERATIONS:
                # Fallback 1: model embedded the call as inline JSON text.
                inline = _extract_inline_tool_calls(content)
                if inline:
                    logger.info(
                        "Found %d inline tool call(s) in content (model did not use structured API).",
                        len(inline),
                    )
                    tool_calls_raw = inline
                    messages[-1] = {"role": "assistant", "content": "", "tool_calls": inline}

                # Fallback 2: model mentioned a tool name but formatted it wrong
                # (e.g. as a bash command). Re-ask with constrained JSON output.
                if not tool_calls_raw:
                    extracted = await _extract_tool_call_via_model(
                        content, tools_for_ollama, client, model
                    )
                    if extracted:
                        resolved = _resolve_tool_name(
                            extracted["function"]["name"], tools_for_ollama
                        )
                        if resolved:
                            extracted["function"]["name"] = resolved
                            tool_calls_raw = [extracted]
                            messages[-1] = {
                                "role": "assistant",
                                "content": "",
                                "tool_calls": tool_calls_raw,
                            }
            if not tool_calls_raw:
                if not content:
                    raise HTTPException(status_code=500, detail="The Ollama model did not return any text.")
                return str(content)

        if iteration == MAX_TOOL_ITERATIONS:
            logger.warning("MAX_TOOL_ITERATIONS (%d) reached for session %s.", MAX_TOOL_ITERATIONS, session_id)
            messages.append({"role": "tool", "content": "Tool iteration limit reached."})
            break

        for tc in tool_calls_raw:
            if isinstance(tc, dict):
                fn_name = tc.get("function", {}).get("name", "")
                fn_args = tc.get("function", {}).get("arguments", {})
            else:
                fn = getattr(tc, "function", None)
                fn_name = getattr(fn, "name", "") if fn else ""
                fn_args = getattr(fn, "arguments", {}) if fn else {}

            if not fn_name:
                continue

            # Resolve potentially hallucinated name to an actual MCP tool name.
            resolved = _resolve_tool_name(fn_name, tools_for_ollama)
            if not resolved:
                messages.append({"role": "tool", "content": f"Unknown tool: '{fn_name}'"})
                continue
            fn_name = resolved

            fn_args = _strip_invalid_args(fn_name, fn_args or {}, tools_for_ollama)
            logger.info("Calling MCP tool '%s' with args: %s", fn_name, fn_args)
            try:
                tool_result = await _call_mcp_tool(fn_name, fn_args)
            except Exception as exc:
                tool_result = f"Tool '{fn_name}' error: {exc}"
                logger.warning("MCP tool '%s' error: %s", fn_name, exc)

            messages.append({"role": "tool", "content": tool_result})

    # Synthesis pass after hitting the iteration cap.
    try:
        final = await client.chat(model=model, messages=messages, tools=None, stream=False)
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=502, detail=f"Failed to reach Ollama at {OLLAMA_HOST}: {exc}") from exc
    if isinstance(final, dict):
        content = final.get("message", {}).get("content", "")
    else:
        msg = getattr(final, "message", None)
        content = getattr(msg, "content", "") if msg else ""
    return str(content) if content else "Agent completed tool execution but produced no summary."


async def stream_ollama_chat(message: str, session_id: str, model: str):
    """Async generator that yields SSE-style event dicts as the tool-calling loop progresses.

    Event types:
      {"type": "thinking",    "content": "<model text>"}
      {"type": "tool_call",   "name": "<tool>", "args": {}}
      {"type": "tool_result", "name": "<tool>", "content": "<output>"}
      {"type": "done",        "content": "<final answer>"}
      {"type": "error",       "content": "<message>"}
    """
    history = await _history_for_session(session_id)
    messages: List[Dict[str, Any]] = (
        [{"role": "system", "content": DEFAULT_INSTRUCTION}]
        + history
        + [{"role": "user", "content": message}]
    )

    tools_for_ollama = await _list_mcp_tools()
    if tools_for_ollama:
        tool_names_hint = "Available tools (use EXACT names): " + ", ".join(
            t["function"]["name"] for t in tools_for_ollama
        )
        messages[0]["content"] += "\n\n" + tool_names_hint

    client = AsyncClient(host=OLLAMA_HOST)

    for iteration in range(MAX_TOOL_ITERATIONS + 1):
        try:
            result = await client.chat(
                model=model,
                messages=messages,
                tools=tools_for_ollama or None,
                stream=False,
            )
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
                    logger.info("Found %d inline tool call(s)", len(inline))
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
                if not content:
                    yield {"type": "error", "content": "The model did not return any text."}
                    return
                yield {"type": "done", "content": content}
                return

        if iteration == MAX_TOOL_ITERATIONS:
            logger.warning("MAX_TOOL_ITERATIONS (%d) reached for session %s.", MAX_TOOL_ITERATIONS, session_id)
            messages.append({"role": "tool", "content": "Tool iteration limit reached."})
            break

        for tc in tool_calls_raw:
            if isinstance(tc, dict):
                fn_name = tc.get("function", {}).get("name", "")
                fn_args = tc.get("function", {}).get("arguments", {})
            else:
                fn = getattr(tc, "function", None)
                fn_name = getattr(fn, "name", "") if fn else ""
                fn_args = getattr(fn, "arguments", {}) if fn else {}

            if not fn_name:
                continue

            resolved = _resolve_tool_name(fn_name, tools_for_ollama)
            if not resolved:
                messages.append({"role": "tool", "content": f"Unknown tool: '{fn_name}'"})
                continue
            fn_name = resolved

            fn_args = _strip_invalid_args(fn_name, fn_args or {}, tools_for_ollama)
            yield {"type": "tool_call", "name": fn_name, "args": fn_args}

            logger.info("Calling MCP tool '%s' with args: %s", fn_name, fn_args)
            try:
                tool_result = await _call_mcp_tool(fn_name, fn_args)
            except Exception as exc:
                tool_result = f"Tool '{fn_name}' error: {exc}"
                logger.warning("MCP tool '%s' error: %s", fn_name, exc)

            yield {"type": "tool_result", "name": fn_name, "content": tool_result}
            messages.append({"role": "tool", "content": tool_result})

    # Synthesis pass after hitting the iteration cap.
    try:
        final = await client.chat(model=model, messages=messages, tools=None, stream=False)
    except Exception as exc:
        yield {"type": "error", "content": str(exc)}
        return

    if isinstance(final, dict):
        content = final.get("message", {}).get("content", "")
    else:
        msg = getattr(final, "message", None)
        content = getattr(msg, "content", "") if msg else ""

    final_content = str(content) if content else "Agent completed tool execution but produced no summary."
    yield {"type": "done", "content": final_content}


# Routes ---------------------------------------------------------------------
@app.get("/models")
async def list_models() -> Dict[str, Any]:
    names = await _list_models()
    default = OLLAMA_MODEL if OLLAMA_MODEL in names else names[0]
    return {"models": names, "default": default}


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    message = (request.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="A message is required.")

    available_models = await _list_models()
    model = (request.model or OLLAMA_MODEL).strip() or OLLAMA_MODEL
    if available_models and model not in available_models:
        logger.warning("Requested model '%s' not available; falling back to '%s'.", model, OLLAMA_MODEL)
        model = OLLAMA_MODEL
    if available_models and model not in available_models:
        raise HTTPException(status_code=400, detail=f"Default model '{model}' not available. Available: {available_models}")

    session_id = (request.session_id or f"default-{PROVIDER_ID}").strip() or f"default-{PROVIDER_ID}"

    await conv_client.ensure(session_id, model=model)

    async with chat_lock:
        content = await run_ollama_chat(message, session_id, model)

    await conv_client.append_message(session_id, "user", message)
    await conv_client.append_message(session_id, "assistant", content)

    return ChatResponse(content=content, provider=PROVIDER_ID, session_id=session_id)


@app.post("/chat/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    message = (request.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="A message is required.")

    available_models = await _list_models()
    model = (request.model or OLLAMA_MODEL).strip() or OLLAMA_MODEL
    if available_models and model not in available_models:
        logger.warning("Requested model '%s' not available; falling back to '%s'.", model, OLLAMA_MODEL)
        model = OLLAMA_MODEL
    if available_models and model not in available_models:
        raise HTTPException(status_code=400, detail=f"Default model '{model}' not available. Available: {available_models}")

    session_id = (request.session_id or f"default-{PROVIDER_ID}").strip() or f"default-{PROVIDER_ID}"
    await conv_client.ensure(session_id, model=model)

    final_content: Dict[str, str] = {"value": ""}

    async def event_generator():
        async for event in stream_ollama_chat(message, session_id, model):
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


# Conversations --------------------------------------------------------------

def _conversation_not_found(conversation_id: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"Conversation '{conversation_id}' not found.")


@app.get("/conversations", response_model=ConversationListResponse)
async def list_conversations() -> ConversationListResponse:
    data = await conv_client.list()
    return ConversationListResponse(**data)


@app.post("/conversations", response_model=Conversation)
async def create_conversation(request: ConversationCreateRequest) -> Conversation:
    available_models = await _list_models()
    model = (request.model or OLLAMA_MODEL).strip() or OLLAMA_MODEL
    if available_models and model not in available_models:
        raise HTTPException(status_code=400, detail=f"Unknown model '{model}'. Available: {available_models}")

    data = await conv_client.create(request.title, model=model)
    return Conversation(**data)


@app.get("/conversations/{conversation_id}", response_model=Conversation)
async def get_conversation(conversation_id: str) -> Conversation:
    try:
        data = await conv_client.get(conversation_id)
    except KeyError:
        raise _conversation_not_found(conversation_id) from None
    return Conversation(**data)


@app.patch("/conversations/{conversation_id}", response_model=Conversation)
async def update_conversation(conversation_id: str, request: ConversationUpdateRequest) -> Conversation:
    try:
        data = await conv_client.update_title(conversation_id, request.title)
    except KeyError:
        raise _conversation_not_found(conversation_id) from None
    return Conversation(**data)


@app.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str) -> Dict[str, str]:
    try:
        await conv_client.delete(conversation_id)
    except KeyError:
        raise _conversation_not_found(conversation_id)
    return {"status": "deleted", "id": conversation_id}


# Health ---------------------------------------------------------------------
@app.get("/healthz")
async def health() -> Dict[str, Any]:
    try:
        await AsyncClient(host=OLLAMA_HOST).list()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Cannot reach Ollama at {OLLAMA_HOST}: {exc}") from exc
    return {"status": "ok"}


# Settings stubs (keeps the React settings page working) ---------------------
@app.post("/settings", response_model=SettingsResponse)
async def save_settings() -> SettingsResponse:
    return SettingsResponse(status="noop", message="No API key required for Ollama.")


@app.get("/settings/status")
async def settings_status() -> Dict[str, Any]:
    return {"exists": True}


@app.get("/settings/cluster", response_model=ClusterSettingsResponse)
async def get_cluster_settings() -> ClusterSettingsResponse:
    # Cluster settings are not used for the Ollama hub.
    return ClusterSettingsResponse(kube_server="")


@app.post("/settings/cluster", response_model=ClusterSettingsResponse)
async def save_cluster_settings(request: ClusterSettingsRequest = Body(...)) -> ClusterSettingsResponse:
    # Accept and echo the value to satisfy the UI; it is not used by the service.
    return ClusterSettingsResponse(kube_server=(request.kube_server or "").strip())


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=PORT, reload=False)
