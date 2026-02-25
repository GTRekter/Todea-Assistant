import os
from typing import Callable, List

from dotenv import load_dotenv
from google.adk.agents import Agent
from google.adk.tools.mcp_tool import MCPToolset, StreamableHTTPConnectionParams

from .instructions import linkerd_agent_instruction
from .tools import (
    helm_search_bel_versions,
    helm_repo_add,
    install_gateway_api_crds,
    generate_certificates,
    helm_install_linkerd_crds,
    helm_install_linkerd_control_plane,
    helm_upgrade_linkerd,
    helm_uninstall_linkerd,
    helm_status,
    linkerd_check,
)

load_dotenv()
MODEL_NAME = os.getenv("AGENT_MODEL", "gemini-2.0-flash")
MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:3002")

LINKERD_TOOLS: List[Callable] = [
    helm_search_bel_versions,
    helm_repo_add,
    install_gateway_api_crds,
    generate_certificates,
    helm_install_linkerd_crds,
    helm_install_linkerd_control_plane,
    helm_upgrade_linkerd,
    helm_uninstall_linkerd,
    helm_status,
    linkerd_check,
]
LINKERD_TOOL_NAMES = [tool.__name__ for tool in LINKERD_TOOLS]

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
    tools=[tool_set],
)

root_agent = linkerd_agent
