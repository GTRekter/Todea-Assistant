from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from typing import Optional

CLI_TIMEOUT = int(os.getenv("CLI_TIMEOUT", "120"))


def _run(*cmd: str, timeout: int = CLI_TIMEOUT) -> dict:
    """Run a command and return a dict. Failures always have an 'error' key."""
    try:
        result = subprocess.run(list(cmd), capture_output=True, text=True, timeout=timeout)
        output = result.stdout.strip()
        stderr = result.stderr.strip()
        if result.returncode != 0:
            return {"error": f"'{' '.join(cmd)}' exited {result.returncode}", "stderr": stderr, "stdout": output}
        if not output:
            return {"detail": "Command succeeded with no output."}
        try:
            parsed = json.loads(output)
            if isinstance(parsed, (dict, list)):
                return parsed if isinstance(parsed, dict) else {"items": parsed}
        except (json.JSONDecodeError, ValueError):
            pass
        return {"output": output}
    except FileNotFoundError as exc:
        binary = cmd[0] if cmd else "?"
        return {"error": f"'{binary}' not found. Ensure it is installed and on $PATH.", "detail": str(exc)}
    except subprocess.TimeoutExpired:
        return {"error": f"Command timed out after {timeout}s.", "command": " ".join(cmd)}


# ---------------------------------------------------------------------------
# Helm repo
# ---------------------------------------------------------------------------

def helm_repo_add(repo_name: str, repo_url: str) -> str:
    """
    Add a Helm repository and update it.

    repo_name: short alias for the repo (e.g. 'linkerd-buoyant').
    repo_url: URL of the Helm repo (e.g. 'https://helm.buoyant.cloud').
    """
    add = _run("helm", "repo", "add", repo_name, repo_url, "--force-update")
    if "error" in add:
        return json.dumps(add, indent=2)
    update = _run("helm", "repo", "update", repo_name)
    if "error" in update:
        return json.dumps(update, indent=2)
    return json.dumps({"repo_add": add, "repo_update": update}, indent=2)


# ---------------------------------------------------------------------------
# Helm search
# ---------------------------------------------------------------------------

def helm_search(chart: str, minor: str = "") -> str:
    """
    Search all versions of a chart; optionally filter by X.Y minor version.

    chart: chart name to search, e.g. 'myrepo/mychart'.
    minor: optional X.Y version filter (e.g. '2.16').
    """
    result = _run("helm", "search", "repo", chart, "--versions", "--output", "json")
    if "error" in result:
        return json.dumps(result, indent=2)
    versions = result.get("items", [])
    if not versions:
        return json.dumps({"error": "No chart versions found.", "chart": chart}, indent=2)
    if minor:
        def _mm(v: str) -> str:
            m = re.search(r"(\d+\.\d+)", v)
            return m.group(1) if m else ""
        filtered = [v for v in versions if _mm(v.get("version", "")) == minor]
        if not filtered:
            available = sorted({_mm(v.get("version", "")) for v in versions}, reverse=True)
            return json.dumps({"error": f"No versions found for minor '{minor}'.", "available_minors": available}, indent=2)
        return json.dumps({"versions": filtered}, indent=2)
    return json.dumps({"versions": versions}, indent=2)


# ---------------------------------------------------------------------------
# Helm upgrade / install
# ---------------------------------------------------------------------------

def helm_upgrade_install(
    release_name: str,
    chart: str,
    namespace: str = "default",
    version: Optional[str] = None,
    create_namespace: bool = False,
    set_values: Optional[dict[str, str]] = None,
    set_file_values: Optional[dict[str, str]] = None,
) -> str:
    """
    Run 'helm upgrade --install' with optional --set and --set-file flags.

    release_name: Helm release name.
    chart: full chart reference, e.g. 'linkerd-buoyant/linkerd-enterprise-control-plane'.
    namespace: target Kubernetes namespace (default: 'default').
    version: chart version to install (omit for latest).
    create_namespace: pass --create-namespace if True.
    set_values: dict of key=value pairs passed as --set.
    set_file_values: dict of key=<file content> pairs passed as --set-file.
    """
    set_values = set_values or {}
    set_file_values = set_file_values or {}
    cmd = [
        "helm", "upgrade", "--install", release_name, chart,
        "--namespace", namespace,
    ]
    if version:
        cmd += ["--version", version]
    if create_namespace:
        cmd.append("--create-namespace")
    for key, value in set_values.items():
        cmd += ["--set", f"{key}={value}"]

    if set_file_values:
        with tempfile.TemporaryDirectory() as tmpdir:
            for key, content in set_file_values.items():
                safe_name = key.replace(".", "_").replace("/", "_")
                path = os.path.join(tmpdir, safe_name)
                with open(path, "w") as f:
                    f.write(content)
                cmd += ["--set-file", f"{key}={path}"]
            result = _run(*cmd)
    else:
        result = _run(*cmd)

    return json.dumps(result, indent=2)


# ---------------------------------------------------------------------------
# Helm configure (reuse-values)
# ---------------------------------------------------------------------------

def helm_configure(
    release_name: str,
    chart: str,
    namespace: str = "default",
    set_values: Optional[dict[str, str]] = None,
) -> str:
    """
    Override specific key=value pairs in an existing release without touching other values.

    Runs 'helm upgrade --reuse-values --set key=value ...' so all previously
    supplied values (certs, license, etc.) are preserved.

    release_name: name of the existing Helm release.
    chart: full chart reference, e.g. 'linkerd-buoyant/linkerd-enterprise-control-plane'.
    namespace: Kubernetes namespace of the release (default: 'default').
    set_values: dict of key=value pairs to override.
    """
    set_values = set_values or {}
    if not set_values:
        return json.dumps({"error": "set_values must contain at least one key=value pair."}, indent=2)

    list_result = _run(
        "helm", "list",
        "--namespace", namespace,
        "--filter", f"^{release_name}$",
        "--output", "json",
    )
    items = list_result.get("items", []) if isinstance(list_result, dict) else []
    version = ""
    if items:
        m = re.match(r"^.+-(\d+\.\d+\.\d+)$", items[0].get("chart", ""))
        if m:
            version = m.group(1)

    cmd = [
        "helm", "upgrade", release_name, chart,
        "--namespace", namespace,
        "--reuse-values",
    ]
    if version:
        cmd += ["--version", version]
    for key, value in set_values.items():
        cmd += ["--set", f"{key}={value}"]

    return json.dumps(_run(*cmd), indent=2)


# ---------------------------------------------------------------------------
# Helm uninstall
# ---------------------------------------------------------------------------

def helm_uninstall(release_name: str, namespace: str = "default") -> str:
    """
    Uninstall a Helm release.

    release_name: name of the Helm release to remove.
    namespace: Kubernetes namespace of the release (default: 'default').
    """
    return json.dumps(_run("helm", "uninstall", release_name, "--namespace", namespace), indent=2)


# ---------------------------------------------------------------------------
# Helm status / list
# ---------------------------------------------------------------------------

def helm_status(release: str, namespace: str = "default") -> str:
    """
    Get the status of a Helm release.

    release: Helm release name.
    namespace: Kubernetes namespace (default: 'default').
    """
    result = _run("helm", "status", release, "--namespace", namespace, "--output", "json")
    if "error" in result:
        available = _run("helm", "list", "--namespace", namespace, "--output", "json")
        return json.dumps({
            "error": f"Release '{release}' not found in namespace '{namespace}'.",
            "hint": "Use the correct release name from 'available_releases' and retry.",
            "available_releases": available.get("items", available),
        }, indent=2)
    return json.dumps(result, indent=2)


def helm_list(namespace: str = "default") -> str:
    """
    List all Helm releases in a namespace.

    namespace: Kubernetes namespace (default: 'default').
    """
    result = _run("helm", "list", "--namespace", namespace, "--output", "json")
    if "error" in result:
        return json.dumps(result, indent=2)
    return json.dumps({"releases": result.get("items", [])}, indent=2)


# ---------------------------------------------------------------------------
# kubectl
# ---------------------------------------------------------------------------

def kubectl_apply(url: str) -> str:
    """
    Apply a Kubernetes manifest from a URL using 'kubectl apply -f'.

    url: URL of the manifest to apply.
    """
    return json.dumps(_run("kubectl", "apply", "-f", url), indent=2)


def kubectl_pods(namespace: str = "default") -> str:
    """
    List pods in a namespace using 'kubectl get pods -n <namespace> -o wide'.

    namespace: Kubernetes namespace (default: 'default').
    """
    return json.dumps(_run("kubectl", "get", "pods", "-n", namespace, "-o", "wide"), indent=2)
