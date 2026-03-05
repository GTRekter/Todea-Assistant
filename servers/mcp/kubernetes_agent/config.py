"""Kubernetes agent configuration."""
from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

MODEL_NAME: str = os.getenv("AGENT_MODEL", "gemini-2.0-flash")
