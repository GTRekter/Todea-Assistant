"""Register all MCP tools and expose the configured FastMCP instance."""
from __future__ import annotations

from typing import Optional

from fastmcp import FastMCP

from agent import agent_lock, run_agent_chat
from config import AGENT_SESSION_ID, MCP_NAME
from kubernetes_agent.tools import (  # type: ignore
    describe_pod,
    diagnose_pod_restarts,
    get_deployments,
    get_events,
    get_namespaces,
    get_nodes,
    get_pod_containers,
    get_pod_logs,
    get_pods,
)
from linkerd_agent.tools import (  # type: ignore
    helm_configure_linkerd,
    helm_install_linkerd_control_plane,
    helm_install_linkerd_crds,
    helm_repo_add as linkerd_helm_repo_add,
    helm_status as linkerd_helm_status,
    helm_uninstall_linkerd,
    helm_upgrade_linkerd,
    install_gateway_api_crds,
    install_linkerd_control_plane,
    linkerd_check,
)
from openssl_agent.tools import (  # type: ignore
    generate_certificates,
    inspect_certificate,
    verify_certificate_chain,
)

mcp = FastMCP(MCP_NAME)


@mcp.tool
async def chat(message: str, session_id: Optional[str] = None) -> str:
    """
    Route chat requests through the Gemini agent so it thinks before calling tools.

    The session id is optional; when omitted, a shared in-memory session is used.
    """
    message = message.strip()
    if not message:
        raise ValueError("A message is required.")

    resolved_session = (session_id or AGENT_SESSION_ID).strip() or AGENT_SESSION_ID
    async with agent_lock:
        return await run_agent_chat(message, resolved_session)


# Linkerd tools
for _fn in (
    linkerd_helm_repo_add, install_gateway_api_crds, install_linkerd_control_plane,
    helm_install_linkerd_crds, helm_install_linkerd_control_plane,
    helm_upgrade_linkerd, helm_configure_linkerd, helm_uninstall_linkerd,
    linkerd_helm_status, linkerd_check,
):
    mcp.tool(_fn)

# OpenSSL tools
for _fn in (generate_certificates, inspect_certificate, verify_certificate_chain):
    mcp.tool(_fn)

# Kubernetes tools
for _fn in (
    get_namespaces, get_nodes, get_pods, get_deployments,
    get_pod_containers, get_pod_logs, describe_pod, get_events,
    diagnose_pod_restarts,
):
    mcp.tool(_fn)
