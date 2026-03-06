"""Linkerd agent configuration."""
from __future__ import annotations

import os

PORT: int = int(os.getenv("PORT", "3800"))
ALLOW_ORIGINS: list[str] = [o.strip() for o in os.getenv("ALLOW_ORIGINS", "*").split(",") if o.strip()]

from .instructions import linkerd_agent_instruction  # noqa: E402

AGENT_CONFIG: dict = {
    "name": "linkerd_agent",
    "instructions": linkerd_agent_instruction,
    "tools": [
        "helm_search_bel_versions",
        "helm_repo_add",
        "install_gateway_api_crds",
        "install_linkerd_control_plane",
        "helm_install_linkerd_crds",
        "helm_install_linkerd_control_plane",
        "helm_upgrade_linkerd",
        "helm_configure_linkerd",
        "helm_uninstall_linkerd",
        "helm_status",
        "linkerd_check",
    ],
}
