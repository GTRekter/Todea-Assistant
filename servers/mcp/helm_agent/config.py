"""Helm agent configuration."""
from __future__ import annotations

import os

PORT: int = int(os.getenv("PORT", "3400"))
ALLOW_ORIGINS: list[str] = [o.strip() for o in os.getenv("ALLOW_ORIGINS", "*").split(",") if o.strip()]

try:
    from .instructions import helm_agent_instruction  # noqa: E402
except ImportError:
    from instructions import helm_agent_instruction  # noqa: E402

AGENT_CONFIG: dict = {
    "name": "helm_agent",
    "instructions": helm_agent_instruction,
    "tools": [
        "helm_generic_repo_add",
        "helm_generic_search",
        "helm_generic_upgrade_install",
        "helm_generic_status",
        "helm_generic_list",
        "helm_generic_uninstall",
        "kubectl_apply",
        "kubectl_pods",
    ],
}
