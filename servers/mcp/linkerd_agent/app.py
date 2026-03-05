from typing import Callable, List

from google.adk.agents import Agent
from google.adk.tools.agent_tool import AgentTool
from google.adk.tools.mcp_tool import MCPToolset, StreamableHTTPConnectionParams

from .config import MODEL_NAME, MCP_SERVER_URL
from .instructions import linkerd_agent_instruction
from .tools import (
    helm_search_bel_versions,
    helm_repo_add,
    install_gateway_api_crds,
    install_linkerd_control_plane,
    helm_configure_linkerd,
    helm_install_linkerd_crds,
    helm_install_linkerd_control_plane,
    helm_upgrade_linkerd,
    helm_uninstall_linkerd,
    helm_status,
    linkerd_check,
)
from openssl_agent.tools import (  # type: ignore
    generate_certificates,
    inspect_certificate,
    verify_certificate_chain,
)
from kubernetes_agent.app import kubernetes_agent  # type: ignore

LINKERD_TOOLS: List[Callable] = [
    helm_search_bel_versions,
    helm_repo_add,
    install_gateway_api_crds,
    install_linkerd_control_plane,
    helm_configure_linkerd,
    helm_install_linkerd_crds,
    helm_install_linkerd_control_plane,
    helm_upgrade_linkerd,
    helm_uninstall_linkerd,
    helm_status,
    linkerd_check,
    generate_certificates,
    inspect_certificate,
    verify_certificate_chain,
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
    tools=[tool_set, AgentTool(agent=kubernetes_agent)],
)

root_agent = linkerd_agent
