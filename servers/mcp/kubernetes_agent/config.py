"""Kubernetes agent configuration."""
from __future__ import annotations

import os

PORT: int = int(os.getenv("PORT", "3700"))
ALLOW_ORIGINS: list[str] = [o.strip() for o in os.getenv("ALLOW_ORIGINS", "*").split(",") if o.strip()]

from .instructions import kubernetes_agent_instruction  # noqa: E402

AGENT_CONFIG: dict = {
    "name": "kubernetes_agent",
    "instructions": kubernetes_agent_instruction,
    "tools": [
        "get_namespaces",
        "get_nodes",
        "get_pods",
        "get_deployments",
        "get_pod_containers",
        "get_pod_logs",
        "describe_pod",
        "get_events",
        "diagnose_pod_restarts",
    ],
}
