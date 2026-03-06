"""GitHub agent configuration."""
from __future__ import annotations

import os

PORT: int = int(os.getenv("PORT", "3600"))
ALLOW_ORIGINS: list[str] = [o.strip() for o in os.getenv("ALLOW_ORIGINS", "*").split(",") if o.strip()]

from .instructions import github_agent_instruction  # noqa: E402

AGENT_CONFIG: dict = {
    "name": "github_agent",
    "instructions": github_agent_instruction,
    "tools": [
        "github_get_file",
        "github_list_directory",
        "github_search_code",
        "github_get_issue",
        "github_get_pr",
    ],
}
