"""Settings routes — provider credentials and cluster configuration."""
from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException

import config as _cfg
import providers.azure as azure_provider
import providers.google as google_provider
import providers.ollama as ollama_provider
from kubernetes import (
    _SETTINGS_KEY_MAP,
    _kubectl,
    _refresh_provider_config_from_secret,
    _secret_key_present,
)
from schemas import ClusterSettingsRequest, ClusterSettingsResponse, SettingsRequest, SettingsResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/settings")


@router.post("", response_model=SettingsResponse)
async def save_settings(request: SettingsRequest) -> SettingsResponse:
    string_data = {
        env_key: getattr(request, field_name)
        for field_name, env_key in _SETTINGS_KEY_MAP.items()
        if getattr(request, field_name, None)
    }
    if not string_data:
        raise HTTPException(status_code=400, detail="No settings provided.")

    ns_result = _kubectl("get", "namespace", _cfg.KUBE_NAMESPACE, "--ignore-not-found", "-o", "name")
    if not ns_result.stdout.strip():
        create_result = _kubectl("create", "namespace", _cfg.KUBE_NAMESPACE)
        if create_result.returncode != 0:
            raise HTTPException(status_code=500, detail=create_result.stderr.strip() or "Failed to create namespace.")

    import json
    exists_result = _kubectl(
        "get", "secret", _cfg.KUBE_SECRET_NAME, "-n", _cfg.KUBE_NAMESPACE, "--ignore-not-found", "-o", "name"
    )
    if exists_result.stdout.strip():
        patch = json.dumps({"stringData": string_data})
        result = _kubectl(
            "patch", "secret", _cfg.KUBE_SECRET_NAME,
            "-n", _cfg.KUBE_NAMESPACE,
            "--type=merge",
            "-p", patch,
        )
    else:
        manifest = json.dumps({
            "apiVersion": "v1", "kind": "Secret",
            "metadata": {"name": _cfg.KUBE_SECRET_NAME, "namespace": _cfg.KUBE_NAMESPACE},
            "stringData": string_data,
        })
        result = _kubectl("apply", "-f", "-", stdin=manifest)

    if result.returncode != 0:
        raise HTTPException(status_code=500, detail=result.stderr.strip() or "kubectl failed.")
    return SettingsResponse(status="ok", message=result.stdout.strip() or "Settings saved.")


@router.get("/status")
async def settings_status() -> Dict[str, Any]:
    secret_exists, secret_data = _refresh_provider_config_from_secret()

    google_configured = google_provider.GOOGLE_ENABLED or _secret_key_present(secret_data, "GOOGLE_API_KEY")
    azure_configured = azure_provider.AZURE_ENABLED or (
        _secret_key_present(secret_data, "AZURE_OPENAI_API_KEY")
        and _secret_key_present(secret_data, "AZURE_OPENAI_ENDPOINT")
    )
    ollama_configured = ollama_provider._OLLAMA_LIBS and ollama_provider.OLLAMA_ENABLED

    return {
        "exists": secret_exists,
        "providers": {
            "google": google_configured,
            "azure": azure_configured,
            "ollama": ollama_configured,
        },
    }


@router.get("/cluster", response_model=ClusterSettingsResponse)
async def get_cluster_settings() -> ClusterSettingsResponse:
    return ClusterSettingsResponse(kube_server=_cfg._kube_server)


@router.post("/cluster", response_model=ClusterSettingsResponse)
async def save_cluster_settings(request: ClusterSettingsRequest) -> ClusterSettingsResponse:
    _cfg._kube_server = (request.kube_server or "").strip()
    return ClusterSettingsResponse(kube_server=_cfg._kube_server)
