"""
Helm Agent — generic HTTP wrapper around the helm and kubectl CLIs.

All domain-specific knowledge (chart names, release names, values) lives in
the callers. This service is purely a subprocess bridge.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import tempfile
from typing import Optional

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

_LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, _LOG_LEVEL, logging.INFO))
logger = logging.getLogger(__name__)

PORT = int(os.getenv("PORT", "3400"))
CLI_TIMEOUT = int(os.getenv("CLI_TIMEOUT", "120"))
ALLOW_ORIGINS = [o.strip() for o in os.getenv("ALLOW_ORIGINS", "*").split(",") if o.strip()]

app = FastAPI(title="Helm Agent")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOW_ORIGINS or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Subprocess helpers
# ---------------------------------------------------------------------------

def _run(*cmd: str, timeout: int = CLI_TIMEOUT) -> dict:
    """Run a command and return a dict. Failures always have an 'error' key."""
    logger.debug("exec: %s", " ".join(cmd))
    try:
        result = subprocess.run(list(cmd), capture_output=True, text=True, timeout=timeout)
        output = result.stdout.strip()
        stderr = result.stderr.strip()
        if result.returncode != 0:
            return {"error": f"'{' '.join(cmd)}' exited {result.returncode}", "stderr": stderr, "stdout": output}
        if not output:
            return {"detail": "Command succeeded with no output."}
        # Try to parse helm JSON output (e.g. helm status --output json)
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
# Request models
# ---------------------------------------------------------------------------

class RepoAddRequest(BaseModel):
    repo_name: str
    repo_url: str


class UpgradeInstallRequest(BaseModel):
    release_name: str
    chart: str
    version: Optional[str] = None
    namespace: str = "default"
    create_namespace: bool = False
    # Passed as --set key=value
    set_values: dict[str, str] = {}
    # Passed as --set-file key=<tmp_file>; values are file contents (e.g. PEM strings)
    set_file_values: dict[str, str] = {}


class ConfigureRequest(BaseModel):
    """Override specific key=value pairs in an existing release without touching certs."""
    release_name: str
    # Full chart reference, e.g. "linkerd-buoyant/linkerd-enterprise-control-plane".
    # Required so helm upgrade knows which chart (and repo) to use.
    chart: str
    namespace: str = "default"
    set_values: dict[str, str] = {}


class UninstallRequest(BaseModel):
    release_name: str
    namespace: str = "default"


class KubectlApplyRequest(BaseModel):
    url: str


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/healthz")
def healthz():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Helm endpoints
# ---------------------------------------------------------------------------

@app.post("/helm/repo/add")
def helm_repo_add(req: RepoAddRequest):
    add = _run("helm", "repo", "add", req.repo_name, req.repo_url, "--force-update")
    if "error" in add:
        return add
    update = _run("helm", "repo", "update", req.repo_name)
    if "error" in update:
        return update
    return {"repo_add": add, "repo_update": update}


@app.get("/helm/search")
def helm_search(
    chart: str = Query(..., description="Chart name to search, e.g. 'myrepo/mychart'"),
    minor: str = Query(default="", description="Optional X.Y version filter"),
):
    """Search all versions of a chart; optionally filter by X.Y minor."""
    import re
    result = _run("helm", "search", "repo", chart, "--versions", "--output", "json")
    if "error" in result:
        return result
    versions = result.get("items", [])
    if not versions:
        return {"error": "No chart versions found.", "chart": chart}
    if minor:
        def _mm(v: str) -> str:
            m = re.search(r"(\d+\.\d+)", v)
            return m.group(1) if m else ""
        filtered = [v for v in versions if _mm(v.get("version", "")) == minor]
        if not filtered:
            available = sorted({_mm(v.get("version", "")) for v in versions}, reverse=True)
            return {"error": f"No versions found for minor '{minor}'.", "available_minors": available}
        return {"versions": filtered}
    return {"versions": versions}


@app.post("/helm/upgrade-install")
def helm_upgrade_install(req: UpgradeInstallRequest):
    """Run 'helm upgrade --install' with optional --set and --set-file flags."""
    logger.debug(
        "upgrade-install request: release=%s chart=%s version=%s namespace=%s "
        "set_values=%s set_file_keys=%s",
        req.release_name, req.chart, req.version, req.namespace,
        req.set_values, list(req.set_file_values.keys()),
    )
    cmd = [
        "helm", "upgrade", "--install", req.release_name, req.chart,
        "--namespace", req.namespace,
    ]
    if req.version:
        cmd += ["--version", req.version]
    if req.create_namespace:
        cmd.append("--create-namespace")
    for key, value in req.set_values.items():
        cmd += ["--set", f"{key}={value}"]

    if req.set_file_values:
        with tempfile.TemporaryDirectory() as tmpdir:
            for key, content in req.set_file_values.items():
                safe_name = key.replace(".", "_").replace("/", "_")
                path = os.path.join(tmpdir, safe_name)
                with open(path, "w") as f:
                    f.write(content)
                cmd += ["--set-file", f"{key}={path}"]
            result = _run(*cmd)
    else:
        result = _run(*cmd)

    return result


@app.post("/helm/configure")
def helm_configure(req: ConfigureRequest):
    """
    Override specific key=value pairs in an existing release without touching certs.

    Runs 'helm upgrade --reuse-values --set key=value ...' so all previously
    supplied values (certs, license, etc.) are preserved, and only the keys in
    set_values are changed.  If a key was already set to a different value,
    the new value takes precedence (--set overrides --reuse-values for the
    same key).
    """
    logger.debug(
        "configure request: release=%s chart=%s namespace=%s set_values=%s",
        req.release_name, req.chart, req.namespace, req.set_values,
    )
    if not req.set_values:
        return {"error": "set_values must contain at least one key=value pair."}

    # Look up the currently installed chart version so we upgrade in-place.
    list_result = _run(
        "helm", "list",
        "--namespace", req.namespace,
        "--filter", f"^{req.release_name}$",
        "--output", "json",
    )
    items = list_result.get("items", []) if isinstance(list_result, dict) else []
    version = ""
    if items:
        m = re.match(r"^.+-(\d+\.\d+\.\d+)$", items[0].get("chart", ""))
        if m:
            version = m.group(1)

    cmd = [
        "helm", "upgrade", req.release_name, req.chart,
        "--namespace", req.namespace,
        "--reuse-values",
    ]
    if version:
        cmd += ["--version", version]
    for key, value in req.set_values.items():
        cmd += ["--set", f"{key}={value}"]

    return _run(*cmd)


@app.post("/helm/uninstall")
def helm_uninstall(req: UninstallRequest):
    return _run("helm", "uninstall", req.release_name, "--namespace", req.namespace)


@app.get("/helm/status")
def helm_status(
    release: str = Query(...),
    namespace: str = Query(default="default"),
):
    result = _run("helm", "status", release, "--namespace", namespace, "--output", "json")
    if "error" in result:
        available = _run("helm", "list", "--namespace", namespace, "--output", "json")
        return {
            "error": f"Release '{release}' not found in namespace '{namespace}'.",
            "hint": "Use the correct release name from 'available_releases' and retry.",
            "available_releases": available.get("items", available),
        }
    return result


@app.get("/helm/list")
def helm_list(namespace: str = Query(default="default")):
    result = _run("helm", "list", "--namespace", namespace, "--output", "json")
    if "error" in result:
        return result
    return {"releases": result.get("items", [])}


# ---------------------------------------------------------------------------
# kubectl endpoints
# ---------------------------------------------------------------------------

@app.post("/kubectl/apply")
def kubectl_apply(req: KubectlApplyRequest):
    return _run("kubectl", "apply", "-f", req.url)


@app.get("/kubectl/pods")
def kubectl_pods(namespace: str = Query(default="default")):
    return _run("kubectl", "get", "pods", "-n", namespace, "-o", "wide")


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
