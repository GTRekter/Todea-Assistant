from fastapi import APIRouter, Query

from tools import (
    helm_search_bel_versions,
    helm_repo_add,
    install_gateway_api_crds,
    install_linkerd_control_plane,
    helm_install_linkerd_crds,
    helm_install_linkerd_control_plane,
    helm_upgrade_linkerd,
    helm_configure_linkerd,
    helm_uninstall_linkerd,
    helm_status,
    linkerd_check,
)
from schemas import (
    HelmRepoAddRequest,
    InstallGatewayApiCRDsRequest,
    InstallControlPlaneRequest,
    InstallLinkerdCRDsRequest,
    HelmInstallControlPlaneRequest,
    UpgradeLinkerdRequest,
    ConfigureLinkerdRequest,
    UninstallLinkerdRequest,
)

router = APIRouter(prefix="/linkerd")


@router.get("/versions")
def _helm_search_bel_versions(minor: str = Query(default="")):
    return {"result": helm_search_bel_versions(minor=minor)}


@router.post("/repo/add")
def _helm_repo_add(req: HelmRepoAddRequest):
    return {"result": helm_repo_add(repo_name=req.repo_name, repo_url=req.repo_url)}


@router.post("/gateway-api/install")
def _install_gateway_api_crds(req: InstallGatewayApiCRDsRequest):
    return {"result": install_gateway_api_crds(version=req.version)}


@router.post("/control-plane/install")
def _install_linkerd_control_plane(req: InstallControlPlaneRequest):
    return {"result": install_linkerd_control_plane(
        version=req.version,
        license_key=req.license_key,
        namespace=req.namespace,
    )}


@router.post("/crds/install")
def _helm_install_linkerd_crds(req: InstallLinkerdCRDsRequest):
    return {"result": helm_install_linkerd_crds(
        version=req.version,
        namespace=req.namespace,
    )}


@router.post("/control-plane/helm-install")
def _helm_install_linkerd_control_plane(req: HelmInstallControlPlaneRequest):
    return {"result": helm_install_linkerd_control_plane(
        version=req.version,
        license_key=req.license_key,
        ca_cert_pem=req.ca_cert_pem,
        issuer_cert_pem=req.issuer_cert_pem,
        issuer_key_pem=req.issuer_key_pem,
        namespace=req.namespace,
    )}


@router.post("/upgrade")
def _helm_upgrade_linkerd(req: UpgradeLinkerdRequest):
    return {"result": helm_upgrade_linkerd(
        version=req.version,
        license_key=req.license_key,
        ca_cert_pem=req.ca_cert_pem,
        issuer_cert_pem=req.issuer_cert_pem,
        issuer_key_pem=req.issuer_key_pem,
        namespace=req.namespace,
    )}


@router.post("/configure")
def _helm_configure_linkerd(req: ConfigureLinkerdRequest):
    return {"result": helm_configure_linkerd(
        key=req.key,
        value=req.value,
        release=req.release,
        namespace=req.namespace,
    )}


@router.post("/uninstall")
def _helm_uninstall_linkerd(req: UninstallLinkerdRequest):
    return {"result": helm_uninstall_linkerd(
        namespace=req.namespace,
        control_plane_release=req.control_plane_release,
        crds_release=req.crds_release,
    )}


@router.get("/status")
def _helm_status(
    release: str = Query(default="linkerd-enterprise-control-plane"),
    namespace: str = Query(default="linkerd"),
):
    return {"result": helm_status(release=release, namespace=namespace)}


@router.get("/check")
def _linkerd_check(
    proxy: bool = Query(default=False),
    namespace: str = Query(default="linkerd"),
    timeout: str = Query(default="30s"),
):
    return {"result": linkerd_check(proxy=proxy, namespace=namespace, timeout=timeout)}
