"""Conversation Hub configuration."""
from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

PORT: int = int(os.getenv("PORT", "3300"))
ALLOW_ORIGINS: list[str] = [o.strip() for o in os.getenv("ALLOW_ORIGINS", "*").split(",") if o.strip()]
