"""Kubernetes helper functions shared across routes."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from config import K8S_AVAILABLE, NAMESPACE


def _batch():
    if not K8S_AVAILABLE:
        raise RuntimeError("Kubernetes not available")
    from kubernetes import client as k8s_client
    return k8s_client.BatchV1Api()


def _core():
    if not K8S_AVAILABLE:
        raise RuntimeError("Kubernetes not available")
    from kubernetes import client as k8s_client
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
