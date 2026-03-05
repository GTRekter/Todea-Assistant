from fastapi import APIRouter, Query

from tools import (
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

router = APIRouter(prefix="/kubernetes")


@router.get("/namespaces")
def _get_namespaces():
    return {"result": get_namespaces()}


@router.get("/nodes")
def _get_nodes():
    return {"result": get_nodes()}


@router.get("/pods")
def _get_pods(namespace: str = Query(default="")):
    return {"result": get_pods(namespace=namespace)}


@router.get("/deployments")
def _get_deployments(namespace: str = Query(default="")):
    return {"result": get_deployments(namespace=namespace)}


@router.get("/events")
def _get_events(
    namespace: str = Query(...),
    pod_name: str = Query(default=""),
):
    return {"result": get_events(namespace=namespace, pod_name=pod_name)}


@router.get("/pods/{pod}/containers")
def _get_pod_containers(pod: str, namespace: str = Query(...)):
    return {"result": get_pod_containers(pod=pod, namespace=namespace)}


@router.get("/pods/{pod}/logs")
def _get_pod_logs(
    pod: str,
    namespace: str = Query(...),
    container: str = Query(default=""),
    previous: bool = Query(default=False),
    tail_lines: int = Query(default=100),
):
    return {"result": get_pod_logs(
        pod=pod,
        namespace=namespace,
        container=container,
        previous=previous,
        tail_lines=tail_lines,
    )}


@router.get("/pods/{pod}/describe")
def _describe_pod(pod: str, namespace: str = Query(...)):
    return {"result": describe_pod(pod=pod, namespace=namespace)}


@router.get("/pods/{pod}/diagnose")
def _diagnose_pod_restarts(pod: str, namespace: str = Query(...)):
    return {"result": diagnose_pod_restarts(pod=pod, namespace=namespace)}
