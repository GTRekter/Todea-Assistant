"""Google ADK agent session management and chat runner."""
from __future__ import annotations

import asyncio
import os
from typing import Optional

from dotenv import load_dotenv
from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.adk.tools.agent_tool import AgentTool
from google.genai import types

from config import AGENT_APP_NAME, AGENT_SESSION_ID, AGENT_USER_ID
from kubernetes_agent.instructions import kubernetes_agent_instruction  # type: ignore
from kubernetes_agent.tools import (  # type: ignore
    describe_pod,
    diagnose_pod_restarts,
    get_deployments,
    get_events,
    get_namespaces,
    get_nodes,
    get_pod_containers,
    get_pod_logs,
    get_pods,
)
from linkerd_agent.instructions import linkerd_agent_instruction  # type: ignore
from linkerd_agent.tools import (  # type: ignore
    helm_configure_linkerd,
    helm_install_linkerd_control_plane,
    helm_install_linkerd_crds,
    helm_repo_add,
    helm_search_bel_versions,
    helm_status,
    helm_uninstall_linkerd,
    helm_upgrade_linkerd,
    install_gateway_api_crds,
    install_linkerd_control_plane,
    linkerd_check,
)
from openssl_agent.tools import (  # type: ignore
    generate_certificates,
    inspect_certificate,
    verify_certificate_chain,
)

load_dotenv()
_MODEL_NAME = os.getenv("AGENT_MODEL", "gemini-2.0-flash")

_kubernetes_agent = Agent(
    name="kubernetes_agent",
    model=_MODEL_NAME,
    description=(
        "Diagnose Kubernetes workload issues: pod crashes, CrashLoopBackOff, "
        "restart storms, liveness/readiness probe failures, OOMKills, and log analysis. "
        "Call this agent when you need to inspect pods, deployments, events, or logs."
    ),
    instruction=kubernetes_agent_instruction,
    tools=[
        get_namespaces,
        get_nodes,
        get_pods,
        get_deployments,
        get_pod_containers,
        get_pod_logs,
        describe_pod,
        get_events,
        diagnose_pod_restarts,
    ],
)

root_agent = Agent(
    name="linkerd_agent",
    model=_MODEL_NAME,
    description="Install and manage Buoyant Enterprise Linkerd (BEL) on a Kubernetes cluster using Helm.",
    instruction=linkerd_agent_instruction,
    tools=[
        helm_repo_add,
        helm_search_bel_versions,
        install_gateway_api_crds,
        install_linkerd_control_plane,
        helm_install_linkerd_crds,
        helm_install_linkerd_control_plane,
        helm_upgrade_linkerd,
        helm_configure_linkerd,
        helm_uninstall_linkerd,
        helm_status,
        linkerd_check,
        generate_certificates,
        inspect_certificate,
        verify_certificate_chain,
        AgentTool(agent=_kubernetes_agent),
    ],
)

session_service = InMemorySessionService()
runner = Runner(
    app_name=AGENT_APP_NAME,
    agent=root_agent,
    session_service=session_service,
)
agent_lock = asyncio.Lock()


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
                output = getattr(result, "output", None) or getattr(result, "stdout", None)
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
