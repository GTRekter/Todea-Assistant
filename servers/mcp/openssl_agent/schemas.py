"""OpenSSL agent request models."""
from __future__ import annotations

from pydantic import BaseModel


class GenerateCertificatesRequest(BaseModel):
    trust_anchor_lifetime: str = "87600h"
    issuer_lifetime: str = "8760h"


class InspectCertificateRequest(BaseModel):
    pem_content: str


class VerifyCertificateChainRequest(BaseModel):
    ca_cert_pem: str
    cert_pem: str
