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
from openssl_agent import tools as openssl_tools  # type: ignore
from kubernetes_agent import tools as k8s_tools  # type: ignore
from linkerd_agent.tools import BEL_HELM_REPO, BEL_HELM_REPO_URL, helm_configure_linkerd as _helm_configure_linkerd
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
    trust_anchor_lifetime: str = "87600h",
    issuer_lifetime: str = "8760h",
) -> str:
    """
    Generate a Linkerd-compatible trust anchor and issuer certificate pair.

    Uses the Python 'cryptography' library — no external binary required.
    Returns JSON with 'ca_cert_pem', 'issuer_cert_pem', and 'issuer_key_pem' fields
    containing the PEM content ready to pass to helm_install_linkerd_control_plane
    or helm_upgrade_linkerd.

    trust_anchor_lifetime: validity period for the trust anchor (default: 87600h / 10 years).
    issuer_lifetime: validity period for the issuer certificate (default: 8760h / 1 year).
    """
    return openssl_tools.generate_certificates(
        trust_anchor_lifetime=trust_anchor_lifetime,
        issuer_lifetime=issuer_lifetime,
    )


@mcp.tool
def inspect_certificate(pem_content: str) -> str:
    """
    Parse and display details of a PEM-encoded X.509 certificate.

    Returns JSON with: subject, issuer, serial_number, not_before, not_after,
    days_remaining, is_expired, is_ca, path_length, subject_alternative_names,
    and signature_algorithm.

    pem_content: the PEM string of the certificate to inspect.
    """
    return openssl_tools.inspect_certificate(pem_content=pem_content)


@mcp.tool
def verify_certificate_chain(ca_cert_pem: str, cert_pem: str) -> str:
    """
    Verify that cert_pem was signed by the CA in ca_cert_pem.

    Returns JSON with: valid_signature, error, issuer_matches_ca,
    cert_not_expired, ca_not_expired.

    Useful for confirming a Linkerd trust-anchor / issuer pair is valid before
    passing them to helm_install_linkerd_control_plane.

    ca_cert_pem: PEM string of the CA (trust anchor) certificate.
    cert_pem: PEM string of the certificate to verify (e.g. issuer cert).
    """
    return openssl_tools.verify_certificate_chain(
        ca_cert_pem=ca_cert_pem,
        cert_pem=cert_pem,
    )


@mcp.tool
def install_linkerd_control_plane(
    version: str,
    license_key: str,
    namespace: str = "linkerd",
) -> str:
    """
    Generate certificates and install the Linkerd Enterprise control plane in one step.

    This composite tool runs generate_certificates followed by
    helm_install_linkerd_control_plane internally so the model never has to
    copy large PEM strings between tool calls.

    Call this INSTEAD of calling generate_certificates and
    helm_install_linkerd_control_plane separately.

    version: the BEL Helm chart version (e.g. '2.19.4').
    license_key: the Buoyant Enterprise Linkerd license key (BUOYANT_LICENSE).
    namespace: target namespace (default: linkerd).
    """
    import json as _json

    certs_raw = openssl_tools.generate_certificates()
    try:
        certs = _json.loads(certs_raw)
    except Exception as exc:
        return _json.dumps({"error": f"Certificate generation failed: {exc}"}, indent=4)
    if "error" in certs:
        return certs_raw

    install_result = linkerd_tools.helm_install_linkerd_control_plane(
        version=version,
        license_key=license_key,
        ca_cert_pem=certs["ca_cert_pem"],
        issuer_cert_pem=certs["issuer_cert_pem"],
        issuer_key_pem=certs["issuer_key_pem"],
        namespace=namespace,
    )

    try:
        install_data = _json.loads(install_result)
    except Exception:
        install_data = install_result

    return _json.dumps({
        "certificates": {
            "ca_cert_pem": certs["ca_cert_pem"],
            "issuer_cert_pem": certs["issuer_cert_pem"],
            "issuer_key_pem": certs["issuer_key_pem"],
        },
        "install": install_data,
    }, indent=4)


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
    ca_cert_pem: str,
    issuer_cert_pem: str,
    issuer_key_pem: str,
    namespace: str = "linkerd",
) -> str:
    """
    Install the linkerd-enterprise-control-plane Helm chart.

    version: the BEL Helm chart version (e.g. 'enterprise-2.19.4').
    license_key: the Buoyant Enterprise Linkerd license key (BUOYANT_LICENSE).
    ca_cert_pem: PEM content of the trust anchor certificate.
    issuer_cert_pem: PEM content of the issuer certificate.
    issuer_key_pem: PEM content of the issuer private key.
    namespace: target namespace (default: linkerd).
    """
    return linkerd_tools.helm_install_linkerd_control_plane(
        version=version,
        license_key=license_key,
        ca_cert_pem=ca_cert_pem,
        issuer_cert_pem=issuer_cert_pem,
        issuer_key_pem=issuer_key_pem,
        namespace=namespace,
    )


@mcp.tool
def helm_upgrade_linkerd(
    version: str,
    license_key: str,
    ca_cert_pem: str,
    issuer_cert_pem: str,
    issuer_key_pem: str,
    namespace: str = "linkerd",
) -> str:
    """
    Upgrade an existing BEL installation to a new version.

    version: the target BEL Helm chart version (e.g. 'enterprise-2.19.4').
    license_key: the Buoyant Enterprise Linkerd license key (BUOYANT_LICENSE).
    ca_cert_pem: PEM content of the trust anchor certificate.
    issuer_cert_pem: PEM content of the issuer certificate.
    issuer_key_pem: PEM content of the issuer private key.
    namespace: namespace where Linkerd is installed (default: linkerd).
    """
    return linkerd_tools.helm_upgrade_linkerd(
        version=version,
        license_key=license_key,
        ca_cert_pem=ca_cert_pem,
        issuer_cert_pem=issuer_cert_pem,
        issuer_key_pem=issuer_key_pem,
        namespace=namespace,
    )


@mcp.tool
def helm_configure_linkerd(
    key: str,
    value: str,
    release: str = "linkerd-enterprise-control-plane",
    namespace: str = "linkerd",
) -> str:
    """
    Change a single Helm value on an existing BEL release without regenerating
    certificates or re-supplying any other previously set value.

    Uses 'helm upgrade --reuse-values --set key=value' so certs, license, and
    all other existing values are preserved.  If the key was already set it is
    correctly overridden by the new value.

    Common keys:
      controllerLogLevel  — control-plane log verbosity (e.g. 'debug', 'info', 'warn')
      proxy.logLevel      — data-plane proxy verbosity (e.g. 'warn,linkerd=info')

    key: Helm value key in dot-notation (e.g. 'controllerLogLevel').
    value: the new value to set (e.g. 'debug').
    release: Helm release name (default: 'linkerd-enterprise-control-plane').
    namespace: namespace of the release (default: linkerd).
    """
    return _helm_configure_linkerd(key=key, value=value, release=release, namespace=namespace)


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


# ---------------------------------------------------------------------------
# Kubernetes diagnostic tools
# ---------------------------------------------------------------------------

@mcp.tool
def get_namespaces() -> str:
    """List all namespaces in the cluster."""
    return k8s_tools.get_namespaces()


@mcp.tool
def get_nodes() -> str:
    """List all nodes with status, roles, and Kubernetes version."""
    return k8s_tools.get_nodes()


@mcp.tool
def get_pods(namespace: str = "") -> str:
    """
    List pods with status, restart counts, and node assignment.

    namespace: target namespace. Leave empty to list pods across all namespaces.
    """
    return k8s_tools.get_pods(namespace=namespace)


@mcp.tool
def get_deployments(namespace: str = "") -> str:
    """
    List deployments with desired / ready / available replica counts.

    namespace: target namespace. Leave empty to list across all namespaces.
    """
    return k8s_tools.get_deployments(namespace=namespace)


@mcp.tool
def get_pod_containers(pod: str, namespace: str) -> str:
    """
    List all container names in a pod (init containers excluded).

    Useful to know which container name to pass to get_pod_logs before
    fetching logs for a multi-container pod.

    pod: pod name.
    namespace: namespace the pod is in.
    """
    return k8s_tools.get_pod_containers(pod=pod, namespace=namespace)


@mcp.tool
def get_pod_logs(
    pod: str,
    namespace: str,
    container: str = "",
    previous: bool = False,
    tail_lines: int = 100,
) -> str:
    """
    Fetch logs from a container in a pod.

    pod: pod name.
    namespace: namespace the pod is in.
    container: container name. Required when the pod has more than one container;
               call get_pod_containers first if unsure.
    previous: if True, fetch logs from the previous (crashed) container instance.
    tail_lines: number of log lines to return from the end (default: 100).
    """
    return k8s_tools.get_pod_logs(
        pod=pod,
        namespace=namespace,
        container=container,
        previous=previous,
        tail_lines=tail_lines,
    )


@mcp.tool
def describe_pod(pod: str, namespace: str) -> str:
    """
    Run 'kubectl describe pod' to show full pod spec, conditions, and events.

    Includes the Events section which is the primary source for diagnosing
    probe failures, image pull errors, and scheduling issues.

    pod: pod name.
    namespace: namespace the pod is in.
    """
    return k8s_tools.describe_pod(pod=pod, namespace=namespace)


@mcp.tool
def get_events(namespace: str, pod_name: str = "") -> str:
    """
    List events in a namespace, sorted by timestamp.

    namespace: namespace to query.
    pod_name: optional pod name to filter events to a single pod.
    """
    return k8s_tools.get_events(namespace=namespace, pod_name=pod_name)


@mcp.tool
def diagnose_pod_restarts(pod: str, namespace: str) -> str:
    """
    Composite diagnostic for a crashing or restarting pod.

    Runs in a single call:
      1. Lists containers in the pod
      2. Fetches current and previous logs for each container (last 50 lines)
      3. Fetches pod events filtered to this pod

    Returns a JSON object with keys: pod, namespace, containers, logs, events.
    Use this as the first tool when investigating a CrashLoopBackOff or
    unexpected restart — it avoids multiple round trips.

    pod: pod name.
    namespace: namespace the pod is in.
    """
    return k8s_tools.diagnose_pod_restarts(pod=pod, namespace=namespace)


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host=MCP_HOST, port=MCP_PORT, middleware=middleware)
