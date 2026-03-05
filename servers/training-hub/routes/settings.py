"""Settings routes — GitHub token management."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from config import (
    AVAILABLE_MODELS,
    DEFAULT_REPOS,
    DEFAULT_WEBSITES,
    GITHUB_SECRET_NAME,
    K8S_AVAILABLE,
    NAMESPACE,
)
from k8s_utils import _core
from schemas import GithubTokenRequest

router = APIRouter(prefix="/settings")


@router.get("")
def get_settings():
    github_token_exists = False
    if K8S_AVAILABLE:
        try:
            _core().read_namespaced_secret(name=GITHUB_SECRET_NAME, namespace=NAMESPACE)
            github_token_exists = True
        except Exception:
            pass
    return {
        "github_token_exists": github_token_exists,
        "models": AVAILABLE_MODELS,
        "repos": DEFAULT_REPOS,
        "websites": DEFAULT_WEBSITES,
    }


@router.post("/github-token", status_code=200)
def save_github_token(body: GithubTokenRequest):
    if not body.token.strip():
        raise HTTPException(status_code=400, detail="Token must not be empty")
    if not K8S_AVAILABLE:
        raise HTTPException(status_code=503, detail="Kubernetes not available")

    from kubernetes import client as k8s_client
    from kubernetes.client.rest import ApiException

    import logging
    logger = logging.getLogger(__name__)

    core = _core()
    secret_body = k8s_client.V1Secret(
        metadata=k8s_client.V1ObjectMeta(name=GITHUB_SECRET_NAME, namespace=NAMESPACE),
        string_data={"token": body.token.strip()},
        type="Opaque",
    )
    try:
        core.read_namespaced_secret(name=GITHUB_SECRET_NAME, namespace=NAMESPACE)
        core.replace_namespaced_secret(
            name=GITHUB_SECRET_NAME, namespace=NAMESPACE, body=secret_body
        )
        logger.info("Updated secret %s", GITHUB_SECRET_NAME)
    except ApiException as exc:
        if exc.status == 404:
            core.create_namespaced_secret(namespace=NAMESPACE, body=secret_body)
            logger.info("Created secret %s", GITHUB_SECRET_NAME)
        else:
            raise HTTPException(status_code=500, detail=str(exc))
    return {"saved": True}
