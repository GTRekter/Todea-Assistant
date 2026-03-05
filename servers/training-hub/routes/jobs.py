"""Job routes — scrape, train, list, logs, cancel."""
from __future__ import annotations

import asyncio
import json
import logging
import threading
from typing import AsyncIterator, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from config import (
    GITHUB_SECRET_NAME,
    GPU_NODE_SELECTOR_KEY,
    GPU_NODE_SELECTOR_VALUE,
    K8S_AVAILABLE,
    NAMESPACE,
    SCRAPER_IMAGE,
    TRAINER_IMAGE,
    TRAINING_PVC_NAME,
)
from k8s_utils import _batch, _core, _find_pod_for_job, _job_phase, _running_job_of_type, _timestamp
from schemas import ScrapeRequest, TrainRequest

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/scrape", status_code=201)
def start_scrape(body: ScrapeRequest):
    if not K8S_AVAILABLE:
        raise HTTPException(status_code=503, detail="Kubernetes not available")

    running = _running_job_of_type("scraper")
    if running:
        raise HTTPException(status_code=409, detail=f"Scraper already running: {running}")

    from kubernetes import client as k8s_client

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
                                k8s_client.V1EnvVar(name="PYTHONUNBUFFERED", value="1"),
                                k8s_client.V1EnvVar(
                                    name="GITHUB_TOKEN",
                                    value_from=k8s_client.V1EnvVarSource(
                                        secret_key_ref=k8s_client.V1SecretKeySelector(
                                            name=GITHUB_SECRET_NAME, key="token", optional=True,
                                        )
                                    ),
                                ),
                            ],
                            volume_mounts=[
                                k8s_client.V1VolumeMount(name="training-data", mount_path="/data")
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


@router.post("/train", status_code=201)
def start_training(body: TrainRequest):
    if not K8S_AVAILABLE:
        raise HTTPException(status_code=503, detail="Kubernetes not available")

    running = _running_job_of_type("trainer")
    if running:
        raise HTTPException(status_code=409, detail=f"Training already running: {running}")

    from kubernetes import client as k8s_client

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
                                k8s_client.V1VolumeMount(name="training-data", mount_path="/data")
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


@router.get("/jobs")
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


@router.get("/logs/{job_name}")
async def stream_logs(job_name: str):
    """SSE stream of pod logs for a Job."""

    async def generate() -> AsyncIterator[str]:
        if not K8S_AVAILABLE:
            yield f"data: {json.dumps({'line': 'Kubernetes not available'})}\n\n"
            return

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

        for _ in range(60):
            pod = await asyncio.to_thread(
                lambda: _core().read_namespaced_pod(name=pod_name, namespace=NAMESPACE)
            )
            phase = pod.status.phase
            if phase in ("Running", "Succeeded", "Failed"):
                break
            await asyncio.sleep(2)
            yield f"data: {json.dumps({'line': f'Pod {pod_name}: {phase}…'})}\n\n"

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


@router.delete("/jobs/{job_name}", status_code=200)
def cancel_job(job_name: str):
    if not K8S_AVAILABLE:
        raise HTTPException(status_code=503, detail="Kubernetes not available")

    from kubernetes import client as k8s_client
    from kubernetes.client.rest import ApiException

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
