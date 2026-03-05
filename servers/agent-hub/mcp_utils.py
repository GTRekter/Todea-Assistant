"""MCP tool cache and call helpers — shared by Ollama and Azure providers."""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List

from config import MCP_SERVER_URL, TOOL_REFRESH_SECONDS

logger = logging.getLogger(__name__)

_EXCLUDED_TOOLS = {"chat"}
_tool_cache: Dict[str, Any] = {"tools": [], "ts": 0.0}

try:
    from fastmcp import Client as MCPClient
    _MCP_LIBS = True
except ImportError:
    _MCP_LIBS = False
    logger.warning("fastmcp not installed; MCP tool calling unavailable.")


async def _list_mcp_tools(force: bool = False) -> List[Dict[str, Any]]:
    if not _MCP_LIBS:
        return []
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
    return _tool_cache["tools"]


async def _call_mcp_tool(tool_name: str, arguments: Dict[str, Any]) -> str:
    async with MCPClient(MCP_SERVER_URL) as mcp:
        result = await mcp.call_tool(tool_name, arguments)
    if result.content:
        texts = [b.text for b in result.content if hasattr(b, "text") and b.text]
        if texts:
            return "\n".join(texts)
    if result.data is not None:
        return str(result.data)
    return repr(result)
