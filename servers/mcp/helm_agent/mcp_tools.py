"""
Generic Helm and kubectl MCP tools.

These wrap the helm-agent HTTP service for use by the MCP server.
They expose provider-agnostic, general-purpose helm/kubectl operations
(no Linkerd-specific logic) so the helm sub-agent can manage any chart.
"""
from __future__ import annotations

import json
import os
from typing import Optional

import httpx

HELM_AGENT_URL = os.getenv("HELM_AGENT_URL", "http://localhost:3400")
CLI_TIMEOUT = 120


def _helm_get(path: str, params: dict | None = None) -> str:
    try:
        resp = httpx.get(f"{HELM_AGENT_URL}{path}", params=params, timeout=CLI_TIMEOUT)
        data = resp.json()
        if isinstance(data, dict) and "error" in data:
            raise RuntimeError(data["error"] + (f"\nstderr: {data['stderr']}" if data.get("stderr") else ""))
        return json.dumps(data, indent=4)
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Helm agent unreachable: {exc}")


def _helm_post(path: str, payload: dict) -> str:
    try:
        resp = httpx.post(f"{HELM_AGENT_URL}{path}", json=payload, timeout=CLI_TIMEOUT)
        data = resp.json()
        if isinstance(data, dict) and "error" in data:
            raise RuntimeError(data["error"] + (f"\nstderr: {data['stderr']}" if data.get("stderr") else ""))
        return json.dumps(data, indent=4)
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Helm agent unreachable: {exc}")


def helm_generic_repo_add(repo_name: str, repo_url: str) -> str:
    """
    Add a Helm repository and refresh the local cache.

    repo_name: short alias for the repo (e.g. 'bitnami').
    repo_url: URL of the Helm repo (e.g. 'https://charts.bitnami.com/bitnami').
    """
    return _helm_post("/helm/repo/add", {"repo_name": repo_name, "repo_url": repo_url})


def helm_generic_search(repo: str, chart: str) -> str:
    """
    Search for available versions of a chart in a Helm repository.

    repo: repository alias (e.g. 'bitnami').
    chart: chart name to search (e.g. 'prometheus').
    """
    return _helm_get("/helm/search", {"chart": f"{repo}/{chart}"})


def helm_generic_upgrade_install(
    release_name: str,
    chart: str,
    namespace: str = "default",
    version: Optional[str] = None,
    values: Optional[dict] = None,
) -> str:
    """
    Install or upgrade a Helm chart (helm upgrade --install).

    release_name: Helm release name (e.g. 'my-prometheus').
    chart: full chart reference (e.g. 'bitnami/prometheus').
    namespace: target Kubernetes namespace (default: 'default').
    version: chart version to install; omit for latest.
    values: optional dict of --set key=value overrides.
    """
    payload: dict = {
        "release_name": release_name,
        "chart": chart,
        "namespace": namespace,
        "create_namespace": True,
    }
    if version:
        payload["version"] = version
    if values:
        payload["set_values"] = values
    return _helm_post("/helm/upgrade-install", payload)


def helm_generic_status(release: str, namespace: str = "default") -> str:
    """
    Show the status of a Helm release.

    release: Helm release name.
    namespace: Kubernetes namespace (default: 'default').
    """
    return _helm_get("/helm/status", {"release": release, "namespace": namespace})


def helm_generic_list(namespace: str = "default") -> str:
    """
    List all Helm releases in a namespace.

    namespace: Kubernetes namespace (default: 'default').
    """
    return _helm_get("/helm/list", {"namespace": namespace})


def helm_generic_uninstall(release_name: str, namespace: str = "default") -> str:
    """
    Uninstall a Helm release.

    release_name: name of the Helm release to remove.
    namespace: Kubernetes namespace of the release (default: 'default').
    """
    return _helm_post("/helm/uninstall", {"release_name": release_name, "namespace": namespace})


def kubectl_apply(url: str) -> str:
    """
    Apply a Kubernetes manifest from a URL (kubectl apply -f <url>).

    url: URL of the manifest to apply.
    """
    return _helm_post("/kubectl/apply", {"url": url})


def kubectl_pods(namespace: str = "default") -> str:
    """
    List pods in a namespace (kubectl get pods -o wide).

    namespace: Kubernetes namespace (default: 'default').
    """
    return _helm_get("/kubectl/pods", {"namespace": namespace})
