"""
training-hub — FastAPI service that manages the training pipeline on Kubernetes.

Endpoints:
  GET  /healthz                   — health check
  GET  /settings                  — models, repos, websites, github token status
  POST /settings/github-token     — save GitHub token as K8s Secret
  POST /scrape                    — create a scraper Job
  POST /train                     — create a trainer Job
  GET  /jobs                      — list active/recent training Jobs
  GET  /logs/{job_name}           — SSE stream of pod logs
  DELETE /jobs/{job_name}         — cancel a running Job
"""

import asyncio
import json
import logging
import os
import threading
from datetime import datetime, timezone
from typing import AsyncIterator, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

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

# ── Kubernetes client (graceful fallback when running outside a cluster) ───────
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

# ── FastAPI app ────────────────────────────────────────────────────────────────
app = FastAPI(title="Training Hub")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOW_ORIGINS or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Static catalogue ───────────────────────────────────────────────────────────
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

# ── Request / response models ──────────────────────────────────────────────────
class GithubTokenRequest(BaseModel):
    token: str

class ScrapeRequest(BaseModel):
    repos: list[str] = []
    websites: list[str] = []

class TrainRequest(BaseModel):
    model: str = "qwen2.5:7b-instruct"
    adapter_name: str = ""
    gpu_node_pool: str = ""

# ── Kubernetes helpers ─────────────────────────────────────────────────────────
def _batch() -> "k8s_client.BatchV1Api":
    return k8s_client.BatchV1Api()

def _core() -> "k8s_client.CoreV1Api":
    return k8s_client.CoreV1Api()

def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

def _job_phase(job) -> str:
    if job.status.succeeded:
        return "Succeeded"
    if job.status.failed:
        return "Failed"
    if job.status.active:
        return "Running"
    for cond in (job.status.conditions or []):
        if cond.type == "Failed" and cond.status == "True":
            return "Failed"
    return "Pending"

def _find_pod_for_job(job_name: str) -> Optional[str]:
    pods = _core().list_namespaced_pod(
        namespace=NAMESPACE,
        label_selector=f"job-name={job_name}",
    )
    if pods.items:
        return pods.items[0].metadata.name
    return None

def _running_job_of_type(job_type: str) -> Optional[str]:
    jobs = _batch().list_namespaced_job(
        namespace=NAMESPACE,
        label_selector=f"todea-job-type={job_type}",
    )
    for job in jobs.items:
        if _job_phase(job) == "Running":
            return job.metadata.name
    return None

# ── Routes ─────────────────────────────────────────────────────────────────────

@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/settings")
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


@app.post("/settings/github-token", status_code=200)
def save_github_token(body: GithubTokenRequest):
    if not body.token.strip():
        raise HTTPException(status_code=400, detail="Token must not be empty")
    if not K8S_AVAILABLE:
        raise HTTPException(status_code=503, detail="Kubernetes not available")

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


@app.post("/scrape", status_code=201)
def start_scrape(body: ScrapeRequest):
    if not K8S_AVAILABLE:
        raise HTTPException(status_code=503, detail="Kubernetes not available")

    running = _running_job_of_type("scraper")
    if running:
        raise HTTPException(status_code=409, detail=f"Scraper already running: {running}")

    job_name = f"todea-scraper-{_timestamp()}"
    repos_arg = ",".join(body.repos) if body.repos else ""
    websites_arg = ",".join(body.websites) if body.websites else ""

    job = k8s_client.V1Job(
        metadata=k8s_client.V1ObjectMeta(
            name=job_name,
            namespace=NAMESPACE,
            labels={"todea-job-type": "scraper"},
        ),
        spec=k8s_client.V1JobSpec(
            ttl_seconds_after_finished=3600,
            backoff_limit=1,
            template=k8s_client.V1PodTemplateSpec(
                metadata=k8s_client.V1ObjectMeta(labels={"todea-job-type": "scraper"}),
                spec=k8s_client.V1PodSpec(
                    restart_policy="Never",
                    containers=[
                        k8s_client.V1Container(
                            name="scraper",
                            image=SCRAPER_IMAGE,
                            image_pull_policy="IfNotPresent",
                            command=["python", "scrapers/runner.py"],
                            args=[
                                f"--repos={repos_arg}",
                                f"--websites={websites_arg}",
                            ],
                            env=[
                                k8s_client.V1EnvVar(
                                    name="PYTHONUNBUFFERED",
                                    value="1",
                                ),
                                k8s_client.V1EnvVar(
                                    name="GITHUB_TOKEN",
                                    value_from=k8s_client.V1EnvVarSource(
                                        secret_key_ref=k8s_client.V1SecretKeySelector(
                                            name=GITHUB_SECRET_NAME,
                                            key="token",
                                            optional=True,
                                        )
                                    ),
                                ),
                            ],
                            volume_mounts=[
                                k8s_client.V1VolumeMount(
                                    name="training-data", mount_path="/data"
                                )
                            ],
                        )
                    ],
                    volumes=[
                        k8s_client.V1Volume(
                            name="training-data",
                            persistent_volume_claim=k8s_client.V1PersistentVolumeClaimVolumeSource(
                                claim_name=TRAINING_PVC_NAME
                            ),
                        )
                    ],
                ),
            ),
        ),
    )
    _batch().create_namespaced_job(namespace=NAMESPACE, body=job)
    logger.info("Created scraper job: %s", job_name)
    return {"job_name": job_name}


@app.post("/train", status_code=201)
def start_training(body: TrainRequest):
    if not K8S_AVAILABLE:
        raise HTTPException(status_code=503, detail="Kubernetes not available")

    running = _running_job_of_type("trainer")
    if running:
        raise HTTPException(status_code=409, detail=f"Training already running: {running}")

    job_name = f"todea-trainer-{_timestamp()}"
    adapter_name = body.adapter_name.strip() or f"adapter-{_timestamp()}"
    node_pool = body.gpu_node_pool.strip() or GPU_NODE_SELECTOR_VALUE

    job = k8s_client.V1Job(
        metadata=k8s_client.V1ObjectMeta(
            name=job_name,
            namespace=NAMESPACE,
            labels={"todea-job-type": "trainer"},
        ),
        spec=k8s_client.V1JobSpec(
            ttl_seconds_after_finished=86400,
            backoff_limit=0,
            template=k8s_client.V1PodTemplateSpec(
                metadata=k8s_client.V1ObjectMeta(labels={"todea-job-type": "trainer"}),
                spec=k8s_client.V1PodSpec(
                    restart_policy="Never",
                    node_selector={GPU_NODE_SELECTOR_KEY: node_pool},
                    tolerations=[
                        k8s_client.V1Toleration(
                            key="sku", operator="Equal", value="gpu", effect="NoSchedule"
                        ),
                        k8s_client.V1Toleration(
                            key="kubernetes.azure.com/scalesetpriority",
                            operator="Equal",
                            value="spot",
                            effect="NoSchedule",
                        ),
                    ],
                    containers=[
                        k8s_client.V1Container(
                            name="trainer",
                            image=TRAINER_IMAGE,
                            image_pull_policy="IfNotPresent",
                            command=["python", "training/train.py"],
                            args=[
                                f"--model={body.model}",
                                f"--adapter-name={adapter_name}",
                            ],
                            resources=k8s_client.V1ResourceRequirements(
                                limits={"nvidia.com/gpu": "1"},
                                requests={"nvidia.com/gpu": "1"},
                            ),
                            volume_mounts=[
                                k8s_client.V1VolumeMount(
                                    name="training-data", mount_path="/data"
                                )
                            ],
                        )
                    ],
                    volumes=[
                        k8s_client.V1Volume(
                            name="training-data",
                            persistent_volume_claim=k8s_client.V1PersistentVolumeClaimVolumeSource(
                                claim_name=TRAINING_PVC_NAME
                            ),
                        )
                    ],
                ),
            ),
        ),
    )
    _batch().create_namespaced_job(namespace=NAMESPACE, body=job)
    logger.info("Created trainer job: %s", job_name)
    return {"job_name": job_name}


@app.get("/jobs")
def list_jobs():
    if not K8S_AVAILABLE:
        return {"jobs": []}

    results = []
    for job_type in ("scraper", "trainer"):
        jobs = _batch().list_namespaced_job(
            namespace=NAMESPACE,
            label_selector=f"todea-job-type={job_type}",
        )
        for job in sorted(
            jobs.items,
            key=lambda j: j.metadata.creation_timestamp or "",
            reverse=True,
        ):
            results.append({
                "name": job.metadata.name,
                "type": job_type,
                "phase": _job_phase(job),
                "created_at": (
                    job.metadata.creation_timestamp.isoformat()
                    if job.metadata.creation_timestamp else None
                ),
                "start_time": (
                    job.status.start_time.isoformat()
                    if job.status.start_time else None
                ),
                "completion_time": (
                    job.status.completion_time.isoformat()
                    if job.status.completion_time else None
                ),
            })
    return {"jobs": results}


@app.get("/logs/{job_name}")
async def stream_logs(job_name: str):
    """SSE stream of pod logs for a Job."""

    async def generate() -> AsyncIterator[str]:
        if not K8S_AVAILABLE:
            yield f"data: {json.dumps({'line': 'Kubernetes not available'})}\n\n"
            return

        # Wait up to 60 s for the pod to appear
        pod_name: Optional[str] = None
        for _ in range(30):
            pod_name = await asyncio.to_thread(_find_pod_for_job, job_name)
            if pod_name:
                break
            await asyncio.sleep(2)
            yield f"data: {json.dumps({'line': 'Waiting for pod to start…'})}\n\n"

        if not pod_name:
            yield f"data: {json.dumps({'line': f'No pod found for job {job_name}'})}\n\n"
            return

        # Wait for pod to reach a loggable phase
        for _ in range(60):
            pod = await asyncio.to_thread(
                lambda: _core().read_namespaced_pod(name=pod_name, namespace=NAMESPACE)
            )
            phase = pod.status.phase
            if phase in ("Running", "Succeeded", "Failed"):
                break
            await asyncio.sleep(2)
            yield f"data: {json.dumps({'line': f'Pod {pod_name}: {phase}…'})}\n\n"

        # Stream logs via a background thread + queue to avoid blocking the event loop
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def _read_logs() -> None:
            try:
                log_stream = _core().read_namespaced_pod_log(
                    name=pod_name,
                    namespace=NAMESPACE,
                    follow=True,
                    _preload_content=False,
                )
                for chunk in log_stream.stream(amt=4096):
                    if chunk:
                        text = chunk.decode("utf-8", errors="replace")
                        for line in text.splitlines():
                            if line.strip():
                                asyncio.run_coroutine_threadsafe(queue.put(line), loop)
            except Exception as exc:
                asyncio.run_coroutine_threadsafe(
                    queue.put(f"Log stream ended: {exc}"), loop
                )
            finally:
                asyncio.run_coroutine_threadsafe(queue.put(None), loop)

        threading.Thread(target=_read_logs, daemon=True).start()

        while True:
            line = await queue.get()
            if line is None:
                break
            yield f"data: {json.dumps({'line': line})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.delete("/jobs/{job_name}", status_code=200)
def cancel_job(job_name: str):
    if not K8S_AVAILABLE:
        raise HTTPException(status_code=503, detail="Kubernetes not available")
    try:
        _batch().delete_namespaced_job(
            name=job_name,
            namespace=NAMESPACE,
            body=k8s_client.V1DeleteOptions(propagation_policy="Foreground"),
        )
        return {"cancelled": True}
    except ApiException as exc:
        if exc.status == 404:
            raise HTTPException(status_code=404, detail="Job not found")
        raise HTTPException(status_code=500, detail=str(exc))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
