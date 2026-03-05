"""Health check route."""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter

import providers.azure as azure_provider
import providers.google as google_provider
import providers.ollama as ollama_provider
from kubernetes import _refresh_provider_config_from_secret

router = APIRouter()


@router.get("/healthz")
async def health() -> Dict[str, Any]:
    _refresh_provider_config_from_secret()
    return {
        "status": "ok",
        "providers": {
            "google": google_provider.GOOGLE_ENABLED and google_provider._GOOGLE_LIBS,
            "ollama": ollama_provider._OLLAMA_LIBS and ollama_provider.OLLAMA_ENABLED,
            "azure": azure_provider.AZURE_ENABLED and azure_provider._AZURE_LIBS,
        },
    }
