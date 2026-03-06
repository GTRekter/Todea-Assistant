"""MCP server entry point."""
from __future__ import annotations

import uvicorn
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from config import MCP_ALLOW_ORIGINS, MCP_HOST, MCP_PORT
from tools import mcp

from github_agent.config import AGENT_CONFIG as _github_cfg  # type: ignore
from helm_agent.config import AGENT_CONFIG as _helm_cfg  # type: ignore
from kubernetes_agent.config import AGENT_CONFIG as _k8s_cfg  # type: ignore
from linkerd_agent.config import AGENT_CONFIG as _linkerd_cfg  # type: ignore
from openssl_agent.config import AGENT_CONFIG as _openssl_cfg  # type: ignore

_AGENTS = [_k8s_cfg, _openssl_cfg, _github_cfg, _helm_cfg, _linkerd_cfg]


async def _agents_endpoint(request):
    """Return all sub-agent configurations (name, instructions, tools list)."""
    return JSONResponse(_AGENTS)


if __name__ == "__main__":
    if hasattr(mcp, "streamable_http_app"):
        mcp_asgi = mcp.streamable_http_app()
    else:
        mcp_asgi = mcp.http_app()

    app = Starlette(
        routes=[
            Route("/agents", _agents_endpoint, methods=["GET"]),
            Mount("/", app=mcp_asgi),
        ],
        middleware=[
            Middleware(
                CORSMiddleware,
                allow_origins=MCP_ALLOW_ORIGINS or ["*"],
                allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
                allow_headers=["mcp-protocol-version", "mcp-session-id", "Authorization", "Content-Type"],
                expose_headers=["mcp-session-id"],
            )
        ],
    )

    uvicorn.run(app, host=MCP_HOST, port=MCP_PORT)
