from fastapi import APIRouter

from tools import (
    generate_certificates,
    inspect_certificate,
    verify_certificate_chain,
)
from schemas import (
    GenerateCertificatesRequest,
    InspectCertificateRequest,
    VerifyCertificateChainRequest,
)

router = APIRouter(prefix="/certificates")


@router.post("/generate")
def _generate_certificates(req: GenerateCertificatesRequest):
    return generate_certificates(
        trust_anchor_lifetime=req.trust_anchor_lifetime,
        issuer_lifetime=req.issuer_lifetime,
    )


@router.post("/inspect")
def _inspect_certificate(req: InspectCertificateRequest):
    return inspect_certificate(pem_content=req.pem_content)


@router.post("/verify")
def _verify_certificate_chain(req: VerifyCertificateChainRequest):
    return verify_certificate_chain(
        ca_cert_pem=req.ca_cert_pem,
        cert_pem=req.cert_pem,
    )
