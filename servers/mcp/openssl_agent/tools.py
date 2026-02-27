"""
OpenSSL certificate agent tools.

Uses the Python `cryptography` library (no external binary required) to:
  - generate_certificates: create a Linkerd-compatible trust anchor + issuer pair
  - inspect_certificate:   parse and display certificate details
  - verify_certificate_chain: verify that a certificate was signed by a given CA
"""
from __future__ import annotations

import datetime
import json

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.x509.oid import NameOID


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_lifetime(lifetime: str) -> datetime.timedelta:
    """Parse a lifetime string into a timedelta.

    Supported suffixes:
      h  — hours   (e.g. '87600h')
      d  — days    (e.g. '3650d')
      y  — years   (e.g. '10y', treated as 365 days each)
    """
    s = lifetime.strip().lower()
    try:
        if s.endswith("h"):
            return datetime.timedelta(hours=int(s[:-1]))
        if s.endswith("d"):
            return datetime.timedelta(days=int(s[:-1]))
        if s.endswith("y"):
            return datetime.timedelta(days=int(s[:-1]) * 365)
    except ValueError:
        pass
    raise ValueError(
        f"Unrecognised lifetime format: '{lifetime}'. "
        "Use e.g. '87600h', '3650d', or '10y'."
    )


def _key_usage_ca() -> x509.KeyUsage:
    return x509.KeyUsage(
        digital_signature=False,
        content_commitment=False,
        key_encipherment=False,
        data_encipherment=False,
        key_agreement=False,
        key_cert_sign=True,
        crl_sign=True,
        encipher_only=False,
        decipher_only=False,
    )


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

def generate_certificates(
    trust_anchor_lifetime: str = "87600h",
    issuer_lifetime: str = "8760h",
) -> str:
    """
    Generate a Linkerd-compatible trust anchor and issuer certificate pair.

    Uses the Python 'cryptography' library — no external binary (step, openssl)
    required. Returns a JSON object with three PEM strings ready to pass
    directly to helm_install_linkerd_control_plane or helm_upgrade_linkerd:

      ca_cert_pem     — trust anchor (self-signed root CA)
      issuer_cert_pem — issuer certificate (intermediate CA, signed by root)
      issuer_key_pem  — issuer private key

    trust_anchor_lifetime: validity period for the trust anchor (default 87600h / 10 years).
    issuer_lifetime: validity period for the issuer cert (default 8760h / 1 year).
    """
    try:
        ta_delta = _parse_lifetime(trust_anchor_lifetime)
        iss_delta = _parse_lifetime(issuer_lifetime)
    except ValueError as exc:
        return json.dumps({"error": str(exc)}, indent=4)

    now = datetime.datetime.now(datetime.timezone.utc)

    # --- Trust anchor (root CA) ---
    ta_key = rsa.generate_private_key(public_exponent=65537, key_size=4096)
    ta_name = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "root.linkerd.cluster.local"),
    ])
    ta_cert = (
        x509.CertificateBuilder()
        .subject_name(ta_name)
        .issuer_name(ta_name)
        .public_key(ta_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + ta_delta)
        .add_extension(x509.BasicConstraints(ca=True, path_length=1), critical=True)
        .add_extension(_key_usage_ca(), critical=True)
        .sign(ta_key, hashes.SHA256())
    )

    # --- Issuer certificate (intermediate CA) ---
    iss_key = rsa.generate_private_key(public_exponent=65537, key_size=4096)
    iss_name = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "identity.linkerd.cluster.local"),
    ])
    iss_cert = (
        x509.CertificateBuilder()
        .subject_name(iss_name)
        .issuer_name(ta_name)
        .public_key(iss_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + iss_delta)
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(_key_usage_ca(), critical=True)
        .sign(ta_key, hashes.SHA256())
    )

    return json.dumps({
        "ca_cert_pem": ta_cert.public_bytes(serialization.Encoding.PEM).decode(),
        "issuer_cert_pem": iss_cert.public_bytes(serialization.Encoding.PEM).decode(),
        "issuer_key_pem": iss_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode(),
    }, indent=4)


def inspect_certificate(pem_content: str) -> str:
    """
    Parse and display details of a PEM-encoded X.509 certificate.

    Returns a JSON object with:
      subject, issuer, serial_number,
      not_before, not_after, days_remaining, is_expired,
      is_ca, path_length, subject_alternative_names, signature_algorithm.

    pem_content: the PEM string of the certificate to inspect.
    """
    try:
        cert = x509.load_pem_x509_certificate(pem_content.strip().encode())
    except Exception as exc:
        return json.dumps({"error": f"Failed to parse certificate: {exc}"}, indent=4)

    now = datetime.datetime.now(datetime.timezone.utc)
    not_after = cert.not_valid_after_utc
    days_remaining = (not_after - now).days

    # BasicConstraints
    try:
        bc = cert.extensions.get_extension_for_class(x509.BasicConstraints)
        is_ca = bc.value.ca
        path_length = bc.value.path_length
    except x509.ExtensionNotFound:
        is_ca = False
        path_length = None

    # Subject Alternative Names
    try:
        san_ext = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        sans: list[str] = (
            san_ext.value.get_values_for_type(x509.DNSName)
            + [str(ip) for ip in san_ext.value.get_values_for_type(x509.IPAddress)]
        )
    except x509.ExtensionNotFound:
        sans = []

    return json.dumps({
        "subject": cert.subject.rfc4514_string(),
        "issuer": cert.issuer.rfc4514_string(),
        "serial_number": str(cert.serial_number),
        "not_before": cert.not_valid_before_utc.isoformat(),
        "not_after": not_after.isoformat(),
        "days_remaining": days_remaining,
        "is_expired": days_remaining < 0,
        "is_ca": is_ca,
        "path_length": path_length,
        "subject_alternative_names": sans,
        "signature_algorithm": cert.signature_algorithm_oid.dotted_string,
    }, indent=4)


def verify_certificate_chain(ca_cert_pem: str, cert_pem: str) -> str:
    """
    Verify that cert_pem was signed by the CA in ca_cert_pem.

    Useful for confirming a Linkerd trust-anchor / issuer pair is valid before
    passing them to helm_install_linkerd_control_plane.

    Returns a JSON object with:
      valid_signature   — True if the signature is cryptographically valid
      error             — error message if validation failed, otherwise null
      issuer_matches_ca — True if cert's Issuer DN matches the CA's Subject DN
      cert_not_expired  — True if the certificate's notAfter is in the future
      ca_not_expired    — True if the CA's notAfter is in the future

    ca_cert_pem: PEM string of the CA (trust anchor) certificate.
    cert_pem: PEM string of the certificate to verify (e.g. issuer cert).
    """
    try:
        ca = x509.load_pem_x509_certificate(ca_cert_pem.strip().encode())
    except Exception as exc:
        return json.dumps({"error": f"Failed to parse CA certificate: {exc}"}, indent=4)

    try:
        cert = x509.load_pem_x509_certificate(cert_pem.strip().encode())
    except Exception as exc:
        return json.dumps({"error": f"Failed to parse certificate: {exc}"}, indent=4)

    valid_signature = False
    error: str | None = None
    try:
        ca.public_key().verify(
            cert.signature,
            cert.tbs_certificate_bytes,
            padding.PKCS1v15(),
            cert.signature_hash_algorithm,
        )
        valid_signature = True
    except Exception as exc:
        error = str(exc)

    now = datetime.datetime.now(datetime.timezone.utc)
    return json.dumps({
        "valid_signature": valid_signature,
        "error": error,
        "issuer_matches_ca": cert.issuer == ca.subject,
        "cert_not_expired": cert.not_valid_after_utc > now,
        "ca_not_expired": ca.not_valid_after_utc > now,
    }, indent=4)
