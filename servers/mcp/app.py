"""MCP server entry point."""
from __future__ import annotations

from config import MCP_HOST, MCP_PORT, middleware
from tools import mcp

if __name__ == "__main__":
    mcp.run(transport="streamable-http", host=MCP_HOST, port=MCP_PORT, middleware=middleware)
