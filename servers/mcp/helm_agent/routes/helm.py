from fastapi import APIRouter, Query

from tools import (
    helm_repo_add,
    helm_search,
    helm_upgrade_install,
    helm_configure,
    helm_uninstall,
    helm_status,
    helm_list,
)
from schemas import (
    RepoAddRequest,
    UpgradeInstallRequest,
    ConfigureRequest,
    UninstallRequest,
)

router = APIRouter(prefix="/helm")


@router.post("/repo/add")
def _helm_repo_add(req: RepoAddRequest):
    return helm_repo_add(repo_name=req.repo_name, repo_url=req.repo_url)


@router.get("/search")
def _helm_search(
    chart: str = Query(..., description="Chart name to search, e.g. 'myrepo/mychart'"),
    minor: str = Query(default="", description="Optional X.Y version filter"),
):
    return helm_search(chart=chart, minor=minor)


@router.post("/upgrade-install")
def _helm_upgrade_install(req: UpgradeInstallRequest):
    return helm_upgrade_install(
        release_name=req.release_name,
        chart=req.chart,
        namespace=req.namespace,
        version=req.version,
        create_namespace=req.create_namespace,
        set_values=req.set_values,
        set_file_values=req.set_file_values,
    )


@router.post("/configure")
def _helm_configure(req: ConfigureRequest):
    return helm_configure(
        release_name=req.release_name,
        chart=req.chart,
        namespace=req.namespace,
        set_values=req.set_values,
    )


@router.post("/uninstall")
def _helm_uninstall(req: UninstallRequest):
    return helm_uninstall(release_name=req.release_name, namespace=req.namespace)


@router.get("/status")
def _helm_status(
    release: str = Query(...),
    namespace: str = Query(default="default"),
):
    return helm_status(release=release, namespace=namespace)


@router.get("/list")
def _helm_list(namespace: str = Query(default="default")):
    return helm_list(namespace=namespace)
