"""Register all MCP tools and expose the configured FastMCP instance."""
from __future__ import annotations

from fastmcp import FastMCP

from config import MCP_NAME
from github_agent.tools import (  # type: ignore
    github_get_file,
    github_get_issue,
    github_get_pr,
    github_list_directory,
    github_search_code,
)
from helm_agent.mcp_tools import (  # type: ignore
    helm_generic_list,
    helm_generic_repo_add,
    helm_generic_search,
    helm_generic_status,
    helm_generic_uninstall,
    helm_generic_upgrade_install,
    kubectl_apply,
    kubectl_pods,
)
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
    helm_search_bel_versions,
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

# Linkerd / BEL tools
for _fn in (
    linkerd_helm_repo_add, helm_search_bel_versions, install_gateway_api_crds,
    install_linkerd_control_plane, helm_install_linkerd_crds,
    helm_install_linkerd_control_plane, helm_upgrade_linkerd, helm_configure_linkerd,
    helm_uninstall_linkerd, linkerd_helm_status, linkerd_check,
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

# GitHub tools
for _fn in (
    github_get_file, github_list_directory, github_search_code,
    github_get_issue, github_get_pr,
):
    mcp.tool(_fn)

# Generic Helm / kubectl tools
for _fn in (
    helm_generic_repo_add, helm_generic_search, helm_generic_upgrade_install,
    helm_generic_status, helm_generic_list, helm_generic_uninstall,
    kubectl_apply, kubectl_pods,
):
    mcp.tool(_fn)
