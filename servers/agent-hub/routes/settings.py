import json
import logging
import os
import subprocess
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException

from config import KUBE_NAMESPACE, KUBE_SECRET_NAME
from models import ClusterSettingsRequest, ClusterSettingsResponse, SettingsRequest, SettingsResponse

router = APIRouter()
logger = logging.getLogger(__name__)

# Runtime-mutable Kubernetes server URL. Empty string = use default kubeconfig (local cluster).
_kube_server: str = os.getenv("KUBE_SERVER", "")


def _kubectl(*args: str, stdin: Optional[str] = None, timeout: int = 30) -> subprocess.CompletedProcess:
    cmd = ["kubectl"]
    if _kube_server:
        cmd += ["--server", _kube_server]
    cmd += list(args)
    try:
        return subprocess.run(
            cmd,
            input=stdin,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="kubectl not found. Ensure it is installed and on $PATH.")
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail="kubectl command timed out.")


@router.post("/settings", response_model=SettingsResponse)
async def save_settings(request: SettingsRequest) -> SettingsResponse:
    ns_result = _kubectl("get", "namespace", KUBE_NAMESPACE, "--ignore-not-found", "-o", "name")
    if not ns_result.stdout.strip():
        create_result = _kubectl("create", "namespace", KUBE_NAMESPACE)
        if create_result.returncode != 0:
            raise HTTPException(status_code=500, detail=create_result.stderr.strip() or "Failed to create namespace.")
    manifest = json.dumps({
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {"name": KUBE_SECRET_NAME, "namespace": KUBE_NAMESPACE},
        "stringData": {"GOOGLE_API_KEY": request.google_api_key},
    })
    result = _kubectl("apply", "-f", "-", stdin=manifest)
    if result.returncode != 0:
        raise HTTPException(status_code=500, detail=result.stderr.strip() or "kubectl apply failed.")
    return SettingsResponse(status="ok", message=result.stdout.strip())


@router.get("/settings/status")
async def settings_status() -> Dict[str, Any]:
    result = _kubectl(
        "get", "secret", KUBE_SECRET_NAME,
        "-n", KUBE_NAMESPACE,
        "--ignore-not-found", "-o", "name",
    )
    return {"exists": bool(result.stdout.strip())}


@router.get("/settings/cluster", response_model=ClusterSettingsResponse)
async def get_cluster_settings() -> ClusterSettingsResponse:
    return ClusterSettingsResponse(kube_server=_kube_server)


@router.post("/settings/cluster", response_model=ClusterSettingsResponse)
async def save_cluster_settings(request: ClusterSettingsRequest) -> ClusterSettingsResponse:
    global _kube_server
    _kube_server = (request.kube_server or "").strip()
    return ClusterSettingsResponse(kube_server=_kube_server)
