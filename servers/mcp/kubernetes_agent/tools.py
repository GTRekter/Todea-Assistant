from __future__ import annotations

import json
import subprocess

KUBECTL_TIMEOUT = 30  # seconds


# ---------------------------------------------------------------------------
# Internal helper — same pattern as linkerd_agent
# ---------------------------------------------------------------------------

def _run(*cmd: str, timeout: int = KUBECTL_TIMEOUT) -> str:
    try:
        result = subprocess.run(list(cmd), capture_output=True, text=True, timeout=timeout)
        output = result.stdout.strip()
        stderr = result.stderr.strip()
        if result.returncode != 0:
            return json.dumps({
                "error": f"'{' '.join(cmd)}' exited {result.returncode}",
                "stderr": stderr,
                "stdout": output,
            }, indent=4)
        return output or json.dumps({"detail": "Command succeeded with no output."})
    except FileNotFoundError:
        return json.dumps({
            "error": "kubectl not found. Ensure it is installed and on $PATH.",
        }, indent=4)
    except subprocess.TimeoutExpired:
        return json.dumps({
            "error": f"Command timed out after {timeout}s.",
            "command": " ".join(cmd),
        }, indent=4)


# ---------------------------------------------------------------------------
# Cluster / namespace discovery
# ---------------------------------------------------------------------------

def get_namespaces() -> str:
    """List all namespaces in the cluster."""
    return _run("kubectl", "get", "namespaces")


def get_nodes() -> str:
    """List all nodes with status, roles, and Kubernetes version."""
    return _run("kubectl", "get", "nodes", "-o", "wide")


# ---------------------------------------------------------------------------
# Workload inspection
# ---------------------------------------------------------------------------

def get_pods(namespace: str = "") -> str:
    """
    List pods with status, restart counts, and node assignment.

    namespace: target namespace. Leave empty to list pods across all namespaces.
    """
    cmd = ["kubectl", "get", "pods", "-o", "wide"]
    cmd += ["-n", namespace] if namespace else ["--all-namespaces"]
    return _run(*cmd)


def get_pod_containers(pod: str, namespace: str) -> str:
    """
    List all container names in a pod (init containers excluded).

    Useful to know which container name to pass to get_pod_logs before
    fetching logs for a multi-container pod.

    pod: pod name.
    namespace: namespace the pod is in.
    """
    return _run(
        "kubectl", "get", "pod", pod, "-n", namespace,
        "-o", r"jsonpath={range .spec.containers[*]}{.name}{'\n'}{end}",
    )


def get_deployments(namespace: str = "") -> str:
    """
    List deployments with desired / ready / available replica counts.

    namespace: target namespace. Leave empty to list across all namespaces.
    """
    cmd = ["kubectl", "get", "deployments", "-o", "wide"]
    cmd += ["-n", namespace] if namespace else ["--all-namespaces"]
    return _run(*cmd)


# ---------------------------------------------------------------------------
# Deep diagnostics
# ---------------------------------------------------------------------------

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
    cmd = ["kubectl", "logs", pod, "-n", namespace, f"--tail={tail_lines}"]
    if container:
        cmd += ["-c", container]
    if previous:
        cmd += ["--previous"]
    return _run(*cmd, timeout=60)


def describe_pod(pod: str, namespace: str) -> str:
    """
    Run 'kubectl describe pod' to show full pod spec, conditions, and events.

    Includes the Events section at the bottom which is the primary source for
    diagnosing probe failures, image pull errors, and scheduling issues.

    pod: pod name.
    namespace: namespace the pod is in.
    """
    return _run("kubectl", "describe", "pod", pod, "-n", namespace)


def get_events(namespace: str, pod_name: str = "") -> str:
    """
    List events in a namespace, sorted by timestamp.

    namespace: namespace to query.
    pod_name: optional pod name to filter events to a single pod
              (sets --field-selector=involvedObject.name=<pod_name>).
    """
    cmd = ["kubectl", "get", "events", "-n", namespace, "--sort-by=.lastTimestamp"]
    if pod_name:
        cmd += [f"--field-selector=involvedObject.name={pod_name}"]
    return _run(*cmd)


# ---------------------------------------------------------------------------
# Composite diagnostic
# ---------------------------------------------------------------------------

def diagnose_pod_restarts(pod: str, namespace: str) -> str:
    """
    Composite diagnostic for a crashing or restarting pod.

    Runs in a single call:
      1. Lists containers in the pod
      2. Fetches current and previous logs for each container (last 50 lines)
      3. Fetches pod events filtered to this pod

    Returns a JSON object with keys: pod, namespace, containers, logs, events.
    This avoids many round trips when investigating a CrashLoopBackOff.

    pod: pod name.
    namespace: namespace the pod is in.
    """
    containers_raw = get_pod_containers(pod, namespace)
    containers = [c.strip() for c in containers_raw.splitlines() if c.strip()]

    logs: dict[str, dict] = {}
    for container in containers:
        logs[container] = {
            "current": get_pod_logs(pod, namespace, container=container, tail_lines=50),
            "previous": get_pod_logs(pod, namespace, container=container, previous=True, tail_lines=50),
        }

    return json.dumps({
        "pod": pod,
        "namespace": namespace,
        "containers": containers,
        "logs": logs,
        "events": get_events(namespace, pod_name=pod),
    }, indent=2)
