"""MCP tool cache and call helpers — shared by all providers."""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List

from config import MCP_SERVER_URL, TOOL_REFRESH_SECONDS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tools that belong exclusively to sub-agents — hidden from the root agent
# ---------------------------------------------------------------------------

_SUB_AGENT_TOOL_NAMES: frozenset = frozenset({
    # kubernetes_agent
    "get_namespaces", "get_nodes", "get_pods", "get_deployments",
    "get_pod_containers", "get_pod_logs", "describe_pod", "get_events",
    "diagnose_pod_restarts",
    # openssl_agent
    "generate_certificates", "inspect_certificate", "verify_certificate_chain",
    # github_agent
    "github_get_file", "github_list_directory", "github_search_code",
    "github_get_issue", "github_get_pr",
    # helm_agent (generic)
    "helm_generic_repo_add", "helm_generic_search", "helm_generic_upgrade_install",
    "helm_generic_status", "helm_generic_list", "helm_generic_uninstall",
    "kubectl_apply", "kubectl_pods",
    # linkerd_agent
    "helm_search_bel_versions", "helm_repo_add", "install_gateway_api_crds",
    "install_linkerd_control_plane", "helm_install_linkerd_crds",
    "helm_install_linkerd_control_plane", "helm_upgrade_linkerd",
    "helm_configure_linkerd", "helm_uninstall_linkerd", "helm_status", "linkerd_check",
})

# ---------------------------------------------------------------------------
# Virtual tools injected into the root agent's tool list
# ---------------------------------------------------------------------------

VIRTUAL_AGENT_TOOLS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "call_kubernetes_agent",
            "description": (
                "Delegate a Kubernetes diagnostic task to the Kubernetes agent. "
                "Use for pod inspection, log analysis, event queries, restart diagnosis, "
                "node/namespace/deployment status."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "Describe the Kubernetes task or question in detail."},
                },
                "required": ["task"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "call_openssl_agent",
            "description": (
                "Delegate certificate operations to the OpenSSL agent. "
                "Use for generating, inspecting, or verifying X.509 certificates."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "Describe the certificate task in detail."},
                },
                "required": ["task"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "call_github_agent",
            "description": (
                "Delegate GitHub repository lookups to the GitHub agent. "
                "Use for reading files, listing directories, searching code, "
                "fetching issues or pull requests from public repositories."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "Describe the GitHub task in detail."},
                },
                "required": ["task"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "call_helm_agent",
            "description": (
                "Delegate generic Helm or kubectl operations to the Helm agent. "
                "Use for installing, upgrading, or removing non-Linkerd charts, "
                "and for running kubectl apply or listing pods."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "Describe the Helm/kubectl task in detail."},
                },
                "required": ["task"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "call_linkerd_agent",
            "description": (
                "Delegate Buoyant Enterprise Linkerd (BEL) installation, upgrade, "
                "configuration, or health-check tasks to the Linkerd agent."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "Describe the Linkerd task in detail."},
                },
                "required": ["task"],
            },
        },
    },
]

# ---------------------------------------------------------------------------
# MCP client bootstrap
# ---------------------------------------------------------------------------

try:
    from fastmcp import Client as MCPClient
    _MCP_LIBS = True
except ImportError:
    _MCP_LIBS = False
    logger.warning("fastmcp not installed; MCP tool calling unavailable.")

_tool_cache: Dict[str, Any] = {"tools": [], "ts": 0.0}
_all_tool_cache: Dict[str, Any] = {"tools": [], "ts": 0.0}


async def _fetch_raw_tools() -> List[Dict[str, Any]]:
    """Fetch all tools from MCP — no caching, no filtering."""
    async with MCPClient(MCP_SERVER_URL) as mcp:
        raw_tools = await mcp.list_tools()
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description or "",
                "parameters": t.inputSchema or {"type": "object", "properties": {}},
            },
        }
        for t in raw_tools
    ]


async def _list_mcp_tools(force: bool = False) -> List[Dict[str, Any]]:
    """
    Root agent tool list:
      - sub-agent-owned tools filtered out
      - virtual call_*_agent tools appended
    """
    if not _MCP_LIBS:
        return list(VIRTUAL_AGENT_TOOLS)
    now = time.time()
    if not _tool_cache["tools"] or force or (now - _tool_cache["ts"] > TOOL_REFRESH_SECONDS):
        try:
            raw = await _fetch_raw_tools()
            root_tools = [t for t in raw if t["function"]["name"] not in _SUB_AGENT_TOOL_NAMES]
            _tool_cache["tools"] = root_tools + VIRTUAL_AGENT_TOOLS
            _tool_cache["ts"] = now
            logger.info(
                "Root agent: %d MCP tools + %d virtual = %d total",
                len(root_tools), len(VIRTUAL_AGENT_TOOLS), len(_tool_cache["tools"]),
            )
        except Exception as exc:
            logger.warning("MCP unreachable; using virtual tools only. Error: %s", exc)
            if not _tool_cache["tools"]:
                _tool_cache["tools"] = list(VIRTUAL_AGENT_TOOLS)
    return _tool_cache["tools"]


async def _list_all_mcp_tools(force: bool = False) -> List[Dict[str, Any]]:
    """All MCP tools without filtering — used by sub-agents."""
    if not _MCP_LIBS:
        return []
    now = time.time()
    if not _all_tool_cache["tools"] or force or (now - _all_tool_cache["ts"] > TOOL_REFRESH_SECONDS):
        try:
            _all_tool_cache["tools"] = await _fetch_raw_tools()
            _all_tool_cache["ts"] = now
            logger.info("Loaded %d total MCP tools", len(_all_tool_cache["tools"]))
        except Exception as exc:
            logger.warning("MCP unreachable for full tool list. Error: %s", exc)
    return _all_tool_cache["tools"]


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
