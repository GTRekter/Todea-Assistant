"""MCP server configuration — loaded from environment variables."""
from __future__ import annotations

import os

from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware

MCP_NAME = "Todea Linkerd Assistant"
MCP_HOST = os.getenv("MCP_HOST", "0.0.0.0")
MCP_PORT = int(os.getenv("MCP_PORT", "3002"))
MCP_ALLOW_ORIGINS = [
    origin.strip()
    for origin in os.getenv("MCP_ALLOW_ORIGINS", "http://localhost:3000").split(",")
    if origin.strip()
]


middleware = [
    Middleware(
        CORSMiddleware,
        allow_origins=MCP_ALLOW_ORIGINS,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=[
            "mcp-protocol-version",
            "mcp-session-id",
            "Authorization",
            "Content-Type",
        ],
        expose_headers=["mcp-session-id"],
    )
]
