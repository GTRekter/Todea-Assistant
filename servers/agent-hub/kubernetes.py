"""Kubernetes secret management and provider config refresh."""
from __future__ import annotations

import base64
import json
import logging
import os
import subprocess
from typing import Any, Dict, Optional, Tuple

from fastapi import HTTPException

import config as _cfg
import providers.google as google_provider
import providers.ollama as ollama_provider
import providers.azure as azure_provider

logger = logging.getLogger(__name__)

# Maps SettingsRequest field names to Kubernetes secret / env var keys.
_SETTINGS_KEY_MAP = {
    "google_api_key":    "GOOGLE_API_KEY",
    "azure_api_key":     "AZURE_OPENAI_API_KEY",
    "azure_endpoint":    "AZURE_OPENAI_ENDPOINT",
    "azure_deployment":  "AZURE_OPENAI_DEPLOYMENT",
    "azure_api_version": "AZURE_OPENAI_API_VERSION",
    "ollama_host":       "OLLAMA_HOST",
}


def _secret_key_present(secret_data: Dict[str, Any], key: str) -> bool:
    """Return True if the K8s Secret contains a non-empty value for key."""
    encoded = secret_data.get(key)
    if not encoded:
        return False
    try:
        decoded = base64.b64decode(encoded).decode().strip()
    except Exception:
        return True  # If decoding fails, assume the key exists to avoid false negatives.
    return bool(decoded)


def _decode_secret_value(secret_data: Dict[str, Any], key: str) -> str:
    encoded = secret_data.get(key)
    if not encoded:
        return ""
    try:
        return base64.b64decode(encoded).decode().strip()
    except Exception:
        return ""


def _load_secret_data() -> Tuple[bool, Dict[str, Any]]:
    result = _kubectl(
        "get", "secret", _cfg.KUBE_SECRET_NAME,
        "-n", _cfg.KUBE_NAMESPACE,
        "--ignore-not-found",
        "-o", "json",
    )
    if not result.stdout.strip():
        return False, {}
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return False, {}
    return True, payload.get("data", {}) or {}


def _refresh_provider_config_from_secret() -> Tuple[bool, Dict[str, Any]]:
    """Sync provider credentials from the K8s secret into process memory/env."""
    exists, secret_data = _load_secret_data()
    if not secret_data:
        return exists, secret_data

    # Google
    secret_google_key = _decode_secret_value(secret_data, "GOOGLE_API_KEY")
    if secret_google_key:
        if secret_google_key != google_provider.GOOGLE_API_KEY:
            google_provider._google_session_service = None
            google_provider._google_runners = {}
        google_provider.GOOGLE_API_KEY = secret_google_key
        os.environ["GOOGLE_API_KEY"] = secret_google_key
    google_provider.GOOGLE_ENABLED = bool(
        google_provider.GOOGLE_API_KEY
        or (google_provider.GOOGLE_VERTEX_PROJECT and google_provider.GOOGLE_VERTEX_LOCATION)
    )

    # Azure
    secret_azure_key = _decode_secret_value(secret_data, "AZURE_OPENAI_API_KEY")
    secret_azure_endpoint = _decode_secret_value(secret_data, "AZURE_OPENAI_ENDPOINT")
    secret_azure_deployment = _decode_secret_value(secret_data, "AZURE_OPENAI_DEPLOYMENT")
    secret_azure_api_version = _decode_secret_value(secret_data, "AZURE_OPENAI_API_VERSION")

    if secret_azure_key:
        azure_provider.AZURE_API_KEY = secret_azure_key
        os.environ["AZURE_OPENAI_API_KEY"] = secret_azure_key
    if secret_azure_endpoint:
        azure_provider.AZURE_ENDPOINT = secret_azure_endpoint
        os.environ["AZURE_OPENAI_ENDPOINT"] = secret_azure_endpoint
    if secret_azure_deployment:
        azure_provider.AZURE_DEPLOYMENT = secret_azure_deployment
    if secret_azure_api_version:
        azure_provider.AZURE_API_VERSION = secret_azure_api_version
    azure_provider.AZURE_ENABLED = bool(azure_provider.AZURE_ENDPOINT and azure_provider.AZURE_API_KEY)

    # Ollama
    secret_ollama_host = _decode_secret_value(secret_data, "OLLAMA_HOST")
    if secret_ollama_host:
        ollama_provider.OLLAMA_HOST = secret_ollama_host
        os.environ["OLLAMA_HOST"] = secret_ollama_host
        ollama_provider.OLLAMA_ENABLED = True

    return exists, secret_data


def _kubectl(*args: str, stdin: Optional[str] = None, timeout: int = 30) -> subprocess.CompletedProcess:
    cmd = ["kubectl"]
    if _cfg._kube_server:
        cmd += ["--server", _cfg._kube_server]
    cmd += list(args)
    try:
        return subprocess.run(cmd, input=stdin, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="kubectl not found.")
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail="kubectl command timed out.")
