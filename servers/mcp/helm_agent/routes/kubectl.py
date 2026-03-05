from fastapi import APIRouter, Query

from tools import kubectl_apply, kubectl_pods
from schemas import KubectlApplyRequest

router = APIRouter(prefix="/kubectl")


@router.post("/apply")
def _kubectl_apply(req: KubectlApplyRequest):
    return kubectl_apply(url=req.url)


@router.get("/pods")
def _kubectl_pods(namespace: str = Query(default="default")):
    return kubectl_pods(namespace=namespace)
