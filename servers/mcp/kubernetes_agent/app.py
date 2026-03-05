from google.adk.agents import Agent

from .config import MODEL_NAME
from .instructions import kubernetes_agent_instruction
from .tools import (
    get_namespaces,
    get_nodes,
    get_pods,
    get_deployments,
    get_pod_containers,
    get_pod_logs,
    describe_pod,
    get_events,
    diagnose_pod_restarts,
)

kubernetes_agent = Agent(
    name="kubernetes_agent",
    model=MODEL_NAME,
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
