"""Shared configuration — loaded from environment variables."""
from __future__ import annotations

import logging
import os

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# ---------------------------------------------------------------------------
# Shared / infrastructure
# ---------------------------------------------------------------------------

ALLOW_ORIGINS = [o.strip() for o in os.getenv("ALLOW_ORIGINS", "*").split(",") if o.strip()]
MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:3002/mcp")
CONVERSATION_HUB_URL = os.getenv("CONVERSATION_HUB_URL", "http://localhost:3300")
MAX_TOOL_ITERATIONS = int(os.getenv("MAX_TOOL_ITERATIONS", "10"))
TOOL_REFRESH_SECONDS = int(os.getenv("TOOL_REFRESH_SECONDS", "300"))
PORT = int(os.getenv("PORT", "3100"))
KUBE_NAMESPACE = os.getenv("KUBE_NAMESPACE", "todea")
KUBE_SECRET_NAME = os.getenv("KUBE_SECRET_NAME", "todea-api-keys")
_kube_server: str = os.getenv("KUBE_SERVER", "")

DEFAULT_INSTRUCTION = os.getenv(
    "DEFAULT_INSTRUCTION",
    (
        "You are Todea, a Kubernetes and Linkerd platform assistant.\n"
        "You work through five specialist sub-agents. Always delegate — never attempt "
        "low-level operations yourself.\n\n"
        "DELEGATION RULES:\n"
        "- Kubernetes questions (pods, logs, events, restarts, nodes, namespaces)\n"
        "    → call_kubernetes_agent(task='<detailed task>')\n"
        "- Buoyant Enterprise Linkerd (BEL) install, upgrade, configure, check\n"
        "    → call_linkerd_agent(task='<detailed task>')\n"
        "- X.509 certificate generation, inspection, or verification\n"
        "    → call_openssl_agent(task='<detailed task>')\n"
        "- GitHub file reads, directory listings, code search, issues, PRs\n"
        "    → call_github_agent(task='<detailed task>')\n"
        "- Generic Helm chart install/upgrade/uninstall, kubectl apply, pod listing\n"
        "    → call_helm_agent(task='<detailed task>')\n\n"
        "Always pass a detailed 'task' string that includes all context the sub-agent "
        "needs (versions, namespaces, release names, license keys, PEM content, etc.).\n"
        "Think step by step, then delegate. Summarise the sub-agent's result for the user."
    ),
)
