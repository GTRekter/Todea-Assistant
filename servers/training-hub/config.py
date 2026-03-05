"""Training Hub configuration — loaded from environment variables."""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

ALLOW_ORIGINS = [o.strip() for o in os.getenv("ALLOW_ORIGINS", "*").split(",") if o.strip()]
PORT = int(os.getenv("PORT", "3500"))
NAMESPACE = os.getenv("NAMESPACE", "todea")
GITHUB_SECRET_NAME = os.getenv("GITHUB_SECRET_NAME", "todea-github-token")
TRAINING_PVC_NAME = os.getenv("TRAINING_PVC_NAME", "todea-training-data")
SCRAPER_IMAGE = os.getenv("SCRAPER_IMAGE", "todea-scraper:local")
TRAINER_IMAGE = os.getenv("TRAINER_IMAGE", "todea-trainer:local")
GPU_NODE_SELECTOR_KEY = os.getenv("GPU_NODE_SELECTOR_KEY", "agentpool")
GPU_NODE_SELECTOR_VALUE = os.getenv("GPU_NODE_SELECTOR_VALUE", "gpupool")

# ── Kubernetes client (graceful fallback when running outside a cluster) ────────
try:
    from kubernetes import client as k8s_client, config as k8s_config
    from kubernetes.client.rest import ApiException

    try:
        k8s_config.load_incluster_config()
        logger.info("Loaded in-cluster Kubernetes config")
    except k8s_config.ConfigException:
        k8s_config.load_kube_config()
        logger.info("Loaded local kubeconfig")

    K8S_AVAILABLE = True
except Exception as exc:
    logger.warning("Kubernetes client not available: %s", exc)
    K8S_AVAILABLE = False

# ── Static catalogue ────────────────────────────────────────────────────────────
AVAILABLE_MODELS = [
    "qwen2.5:7b-instruct",
    "llama3.1:8b",
    "llama3.2:3b",
    "mistral:7b",
]

DEFAULT_REPOS = [
    {"id": "linkerd/linkerd2", "label": "linkerd/linkerd2", "default": True},
    {"id": "linkerd/linkerd2-proxy", "label": "linkerd/linkerd2-proxy", "default": True},
    {"id": "linkerd/website", "label": "linkerd/website (docs source)", "default": True},
    {"id": "linkerd/linkerd-viz", "label": "linkerd/linkerd-viz", "default": False},
    {"id": "linkerd/multicluster-controller", "label": "linkerd/multicluster-controller", "default": False},
]

DEFAULT_WEBSITES = [
    {"id": "linkerd.io", "label": "linkerd.io/docs", "default": True},
    {"id": "docs.buoyant.io", "label": "docs.buoyant.io", "default": True},
    {"id": "deepwiki", "label": "deepwiki.com/linkerd", "default": False},
]
