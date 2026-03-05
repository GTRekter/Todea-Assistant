"""Linkerd agent request models."""
from __future__ import annotations

from pydantic import BaseModel


class HelmRepoAddRequest(BaseModel):
    repo_name: str = "linkerd-buoyant"
    repo_url: str = "https://helm.buoyant.cloud"


class InstallGatewayApiCRDsRequest(BaseModel):
    version: str


class InstallControlPlaneRequest(BaseModel):
    version: str
    license_key: str
    namespace: str = "linkerd"


class InstallLinkerdCRDsRequest(BaseModel):
    version: str
    namespace: str = "linkerd"


class HelmInstallControlPlaneRequest(BaseModel):
    version: str
    license_key: str
    ca_cert_pem: str
    issuer_cert_pem: str
    issuer_key_pem: str
    namespace: str = "linkerd"


class UpgradeLinkerdRequest(BaseModel):
    version: str
    license_key: str
    ca_cert_pem: str
    issuer_cert_pem: str
    issuer_key_pem: str
    namespace: str = "linkerd"


class ConfigureLinkerdRequest(BaseModel):
    key: str
    value: str
    release: str = "linkerd-enterprise-control-plane"
    namespace: str = "linkerd"


class UninstallLinkerdRequest(BaseModel):
    namespace: str = "linkerd"
    control_plane_release: str = "linkerd-enterprise-control-plane"
    crds_release: str = "linkerd-enterprise-crds"


class GenerateCertificatesRequest(BaseModel):
    trust_anchor_lifetime: str = "87600h"
    issuer_lifetime: str = "8760h"


class InspectCertificateRequest(BaseModel):
    pem_content: str


class VerifyCertificateChainRequest(BaseModel):
    ca_cert_pem: str
    cert_pem: str
