"""GitHub agent configuration."""
from __future__ import annotations

import os

PORT: int = int(os.getenv("PORT", "3600"))
ALLOW_ORIGINS: list[str] = [o.strip() for o in os.getenv("ALLOW_ORIGINS", "*").split(",") if o.strip()]
