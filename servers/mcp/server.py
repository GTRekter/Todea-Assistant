from __future__ import annotations
import asyncio
import os
from typing import Optional
from fastmcp import FastMCP
from google.adk.runners import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.genai import types
from linkerd_agent.agent import root_agent as linkerd_agent  # type: ignore
from linkerd_agent import tools as linkerd_tools  # type: ignore
from linkerd_agent.tools import BEL_HELM_REPO, BEL_HELM_REPO_URL
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

mcp = FastMCP(MCP_NAME)
AGENT_APP_NAME = os.getenv("MCP_AGENT_APP_NAME", "todea-mcp-agent")
AGENT_USER_ID = os.getenv("MCP_AGENT_USER_ID", "web-ui")
AGENT_SESSION_ID = os.getenv("MCP_AGENT_SESSION_ID", "web-session")

session_service = InMemorySessionService()
runner = Runner(
    app_name=AGENT_APP_NAME,
    agent=linkerd_agent,
    session_service=session_service,
)
agent_lock = asyncio.Lock()

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

async def ensure_agent_session(session_id: str) -> None:
    existing = await session_service.get_session(
        app_name=AGENT_APP_NAME,
        user_id=AGENT_USER_ID,
        session_id=session_id,
    )
    if existing:
        return
    await session_service.create_session(
        app_name=AGENT_APP_NAME,
        user_id=AGENT_USER_ID,
        session_id=session_id,
    )


def content_to_text(content: Optional[types.Content]) -> str:
    if not content:
        return ""
    parts = []
    if content.parts:
        for part in content.parts:
            if getattr(part, "text", None):
                parts.append(part.text)
            elif getattr(part, "function_call", None):
                parts.append(f"[function call] {part.function_call.name}")
            elif getattr(part, "function_response", None):
                parts.append(
                    f"[function response] {part.function_response.name}: "
                    f"{part.function_response.response}"
                )
            elif getattr(part, "code_execution_result", None):
                result = part.code_execution_result
                output = getattr(result, "output", None) or getattr(
                    result, "stdout", None
                )
                if output:
                    parts.append(str(output))
    return "\n".join([p for p in parts if p]) or (getattr(content, "text", "") or "")

async def run_agent_chat(message: str, session_id: str) -> str:
    await ensure_agent_session(session_id)
    final_response = ""
    user_message = types.Content(role="user", parts=[types.Part(text=message)])

    async for event in runner.run_async(
        user_id=AGENT_USER_ID,
        session_id=session_id,
        new_message=user_message,
    ):
        if event.author != AGENT_USER_ID and event.is_final_response():
            final_response = content_to_text(event.content) or final_response

    return final_response or "The agent did not return any text."


@mcp.tool
async def chat(message: str, session_id: Optional[str] = None) -> str:
    """
    Route chat requests through the Gemini agent so it thinks before calling tools.

    The session id is optional; when omitted, a shared in-memory session is used.
    """
    message = message.strip()
    if not message:
        raise ValueError("A message is required.")

    resolved_session = (session_id or AGENT_SESSION_ID).strip() or AGENT_SESSION_ID
    async with agent_lock:
        return await run_agent_chat(message, resolved_session)


# ---------------------------------------------------------------------------
# Linkerd Helm tools
# ---------------------------------------------------------------------------

@mcp.tool
def helm_repo_add(repo_name: str = BEL_HELM_REPO, repo_url: str = BEL_HELM_REPO_URL) -> str:
    """
    Add the Buoyant Enterprise Linkerd Helm repo and refresh the local cache.

    repo_name: local alias for the repo (default: 'linkerd-buoyant').
    repo_url: Helm repo URL (default: https://helm.buoyant.cloud).
    """
    return linkerd_tools.helm_repo_add(repo_name=repo_name, repo_url=repo_url)


@mcp.tool
def install_gateway_api_crds(version: str) -> str:
    """
    Install the Kubernetes Gateway API CRDs required by BEL.

    The manifest is chosen automatically based on major version:
      2.18.x → Gateway API v1.1.1 experimental-install.yaml
      2.19.x+ → Gateway API v1.2.1 standard-install.yaml

    version: the BEL version being installed (e.g. 'enterprise-2.19.4').
    """
    return linkerd_tools.install_gateway_api_crds(version=version)


@mcp.tool
def generate_certificates(
    trust_anchor_cert: str = "ca.crt",
    trust_anchor_key: str = "ca.key",
    issuer_cert: str = "issuer.crt",
    issuer_key: str = "issuer.key",
    trust_anchor_lifetime: str = "87600h",
    issuer_lifetime: str = "8760h",
) -> str:
    """
    Generate a trust anchor and issuer certificate pair for BEL using the step CLI.

    trust_anchor_cert: output path for the trust anchor certificate (default: ca.crt).
    trust_anchor_key: output path for the trust anchor private key (default: ca.key).
    issuer_cert: output path for the issuer certificate (default: issuer.crt).
    issuer_key: output path for the issuer private key (default: issuer.key).
    trust_anchor_lifetime: validity period for the trust anchor (default: 87600h / 10 years).
    issuer_lifetime: validity period for the issuer certificate (default: 8760h / 1 year).
    """
    return linkerd_tools.generate_certificates(
        trust_anchor_cert=trust_anchor_cert,
        trust_anchor_key=trust_anchor_key,
        issuer_cert=issuer_cert,
        issuer_key=issuer_key,
        trust_anchor_lifetime=trust_anchor_lifetime,
        issuer_lifetime=issuer_lifetime,
    )


@mcp.tool
def helm_install_linkerd_crds(version: str, namespace: str = "linkerd") -> str:
    """
    Install the linkerd-enterprise-crds Helm chart.

    version: the BEL Helm chart version (e.g. 'enterprise-2.19.4').
    namespace: target namespace (created if it does not exist).
    """
    return linkerd_tools.helm_install_linkerd_crds(version=version, namespace=namespace)


@mcp.tool
def helm_install_linkerd_control_plane(
    version: str,
    license_key: str,
    ca_cert: str = "ca.crt",
    issuer_cert: str = "issuer.crt",
    issuer_key: str = "issuer.key",
    namespace: str = "linkerd",
) -> str:
    """
    Install the linkerd-enterprise-control-plane Helm chart.

    version: the BEL Helm chart version (e.g. 'enterprise-2.19.4').
    license_key: the Buoyant Enterprise Linkerd license key (BUOYANT_LICENSE).
    ca_cert: path to the trust anchor certificate file (default: ca.crt).
    issuer_cert: path to the issuer certificate file (default: issuer.crt).
    issuer_key: path to the issuer private key file (default: issuer.key).
    namespace: target namespace (default: linkerd).
    """
    return linkerd_tools.helm_install_linkerd_control_plane(
        version=version,
        license_key=license_key,
        ca_cert=ca_cert,
        issuer_cert=issuer_cert,
        issuer_key=issuer_key,
        namespace=namespace,
    )


@mcp.tool
def helm_upgrade_linkerd(
    version: str,
    license_key: str,
    ca_cert: str = "ca.crt",
    issuer_cert: str = "issuer.crt",
    issuer_key: str = "issuer.key",
    namespace: str = "linkerd",
) -> str:
    """
    Upgrade an existing BEL installation to a new version.

    version: the target BEL Helm chart version (e.g. 'enterprise-2.19.4').
    license_key: the Buoyant Enterprise Linkerd license key (BUOYANT_LICENSE).
    ca_cert: path to the trust anchor certificate file (default: ca.crt).
    issuer_cert: path to the issuer certificate file (default: issuer.crt).
    issuer_key: path to the issuer private key file (default: issuer.key).
    namespace: namespace where Linkerd is installed (default: linkerd).
    """
    return linkerd_tools.helm_upgrade_linkerd(
        version=version,
        license_key=license_key,
        ca_cert=ca_cert,
        issuer_cert=issuer_cert,
        issuer_key=issuer_key,
        namespace=namespace,
    )


@mcp.tool
def helm_uninstall_linkerd(namespace: str = "linkerd") -> str:
    """
    Uninstall BEL control-plane and CRDs from the cluster.

    namespace: namespace where Linkerd is installed (default: linkerd).
    """
    return linkerd_tools.helm_uninstall_linkerd(namespace=namespace)


@mcp.tool
def helm_status(
    release: str = "linkerd-enterprise-control-plane",
    namespace: str = "linkerd",
) -> str:
    """
    Show the Helm release status for a BEL release.

    release: the Helm release name (default: 'linkerd-enterprise-control-plane').
    namespace: namespace where the release is installed (default: linkerd).
    """
    return linkerd_tools.helm_status(release=release, namespace=namespace)


@mcp.tool
def linkerd_check(proxy: bool = False) -> str:
    """
    Run 'linkerd check' to verify the BEL installation health.

    proxy: if True, also validate data-plane proxy health (linkerd check --proxy).
    """
    return linkerd_tools.linkerd_check(proxy=proxy)


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host=MCP_HOST, port=MCP_PORT, middleware=middleware)
