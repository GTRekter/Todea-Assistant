"""OpenSSL agent configuration."""
from __future__ import annotations

import os

PORT: int = int(os.getenv("PORT", "3500"))
ALLOW_ORIGINS: list[str] = [o.strip() for o in os.getenv("ALLOW_ORIGINS", "*").split(",") if o.strip()]

from .instructions import openssl_agent_instruction  # noqa: E402

AGENT_CONFIG: dict = {
    "name": "openssl_agent",
    "instructions": openssl_agent_instruction,
    "tools": [
        "generate_certificates",
        "inspect_certificate",
        "verify_certificate_chain",
    ],
}
