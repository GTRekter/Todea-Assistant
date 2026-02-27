import os
from typing import Callable, List

from dotenv import load_dotenv
from google.adk.agents import Agent
from google.adk.tools.agent_tool import AgentTool
from google.adk.tools.mcp_tool import MCPToolset, StreamableHTTPConnectionParams

from .instructions import linkerd_agent_instruction
from .tools import (
    helm_search_bel_versions,
    helm_repo_add,
    install_gateway_api_crds,
    helm_configure_linkerd,
    helm_install_linkerd_crds,
    helm_install_linkerd_control_plane,
    helm_upgrade_linkerd,
    helm_uninstall_linkerd,
    helm_status,
    linkerd_check,
)
from openssl_agent.agent import openssl_agent  # type: ignore
from kubernetes_agent.agent import kubernetes_agent  # type: ignore

load_dotenv()
MODEL_NAME = os.getenv("AGENT_MODEL", "gemini-2.0-flash")
MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:3002")

# MCP tools exposed directly by server.py (Helm / Linkerd operations).
# Certificate generation is intentionally excluded here — use the openssl_agent
# sub-agent for standalone cert work, or install_linkerd_control_plane for a
# combined cert-generation + Helm-install step that avoids passing large PEM
# strings between tool calls.
LINKERD_TOOLS: List[Callable] = [
    helm_search_bel_versions,
    helm_repo_add,
    install_gateway_api_crds,
    helm_configure_linkerd,
    helm_install_linkerd_crds,
    helm_install_linkerd_control_plane,
    helm_upgrade_linkerd,
    helm_uninstall_linkerd,
    helm_status,
    linkerd_check,
]
# install_linkerd_control_plane is a composite MCP tool defined in server.py
# (not in linkerd_tools), so it is added by name.
LINKERD_TOOL_NAMES = [tool.__name__ for tool in LINKERD_TOOLS] + [
    "install_linkerd_control_plane",
]

tool_set = MCPToolset(
    connection_params=StreamableHTTPConnectionParams(
        url=f"{MCP_SERVER_URL.rstrip('/')}/mcp"
    ),
    tool_filter=LINKERD_TOOL_NAMES,
)

linkerd_agent = Agent(
    name="linkerd_agent",
    model=MODEL_NAME,
    description="Install and manage Buoyant Enterprise Linkerd (BEL) on a Kubernetes cluster using Helm.",
    instruction=linkerd_agent_instruction,
    tools=[tool_set, AgentTool(agent=openssl_agent), AgentTool(agent=kubernetes_agent)],
)

root_agent = linkerd_agent
