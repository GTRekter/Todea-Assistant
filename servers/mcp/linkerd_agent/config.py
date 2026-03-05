"""Linkerd agent configuration."""
from __future__ import annotations

import os
from typing import Callable, List

from dotenv import load_dotenv

load_dotenv()

MODEL_NAME: str = os.getenv("AGENT_MODEL", "gemini-2.0-flash")
MCP_SERVER_URL: str = os.getenv("MCP_SERVER_URL", "http://localhost:3002")
