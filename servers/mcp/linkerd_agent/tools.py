import json
import os
import re
import subprocess

import httpx

CLI_TIMEOUT = 120  # seconds — for step/linkerd CLIs only

BEL_HELM_REPO = "linkerd-buoyant"
BEL_HELM_REPO_URL = "https://helm.buoyant.cloud"

HELM_AGENT_URL = os.getenv("HELM_AGENT_URL", "http://localhost:3400")

# Gateway API CRD manifests differ between BEL major versions:
#   2.18 → experimental-install.yaml (v1.1.1) — transition release
#   2.19+ → standard-install.yaml   (v1.2.1) — Linkerd no longer owns Gateway API CRDs
_GATEWAY_API_MANIFESTS = {
    "2.18": "https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.1.1/experimental-install.yaml",
    "2.19": "https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.2.1/standard-install.yaml",
}
_GATEWAY_API_DEFAULT = _GATEWAY_API_MANIFESTS["2.19"]

BEL_RELEASE_NOTES_URL = "https://docs.buoyant.io/buoyant-enterprise-linkerd/{minor}/release-notes/"


# ---------------------------------------------------------------------------
# Local subprocess helper — only used for step and linkerd CLIs
# ---------------------------------------------------------------------------

def _run(*cmd: str, timeout: int = CLI_TIMEOUT) -> str:
    """Execute a shell command and return the output as a string."""
    try:
        result = subprocess.run(list(cmd), capture_output=True, text=True, timeout=timeout)
        output = result.stdout.strip()
        stderr = result.stderr.strip()
        if result.returncode != 0:
            return json.dumps({
                "error": f"'{' '.join(cmd)}' exited {result.returncode}",
                "stderr": stderr,
                "stdout": output,
            }, indent=4)
        return output or json.dumps({"detail": "Command succeeded with no output."})
    except FileNotFoundError as exc:
        binary = cmd[0] if cmd else "?"
        return json.dumps({
            "error": f"'{binary}' not found. Ensure it is installed and on $PATH.",
            "detail": str(exc),
        }, indent=4)
    except subprocess.TimeoutExpired:
        return json.dumps({
            "error": f"Command timed out after {timeout}s.",
            "command": " ".join(cmd),
        }, indent=4)


# ---------------------------------------------------------------------------
# Helm agent HTTP helpers
# ---------------------------------------------------------------------------

def _check_error(data: dict) -> None:
    """Raise RuntimeError if the helm-agent response contains an error."""
    if isinstance(data, dict) and "error" in data:
        msg = data["error"]
        stderr = data.get("stderr", "")
        raise RuntimeError(f"{msg}" + (f"\nstderr: {stderr}" if stderr else ""))


def _helm_get(path: str, params: dict | None = None) -> str:
    try:
        resp = httpx.get(f"{HELM_AGENT_URL}{path}", params=params, timeout=CLI_TIMEOUT)
        data = resp.json()
        _check_error(data)
        return json.dumps(data, indent=4)
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Helm agent unreachable: {exc}")


def _helm_post(path: str, payload: dict) -> str:
    try:
        resp = httpx.post(f"{HELM_AGENT_URL}{path}", json=payload, timeout=CLI_TIMEOUT)
        data = resp.json()
        _check_error(data)
        return json.dumps(data, indent=4)
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Helm agent unreachable: {exc}")


# ---------------------------------------------------------------------------
# Version helpers
# ---------------------------------------------------------------------------

def _major_minor(version: str) -> str:
    """Extract 'X.Y' from strings like 'enterprise-2.19.4' or '2.19.4'."""
    m = re.search(r"(\d+\.\d+)", version)
    return m.group(1) if m else ""


def _chart_version(version: str) -> str:
    """
    Normalize a BEL version string to the Helm chart version.

    Accepts either:
      - chart version: '2.19.4'
      - app version:   'enterprise-2.19.4'

    Returns the numeric chart version ('2.19.4') for use with '--version'.
    """
    match = re.search(r"(\d+\.\d+\.\d+)", version)
    return match.group(1) if match else version


def _gateway_api_manifest_url(version: str) -> str:
    mm = _major_minor(version)
    return _GATEWAY_API_MANIFESTS.get(mm, _GATEWAY_API_DEFAULT)


# ---------------------------------------------------------------------------
# Tools — BEL-specific logic lives here; helm agent receives generic params
# ---------------------------------------------------------------------------

def helm_search_bel_versions(minor: str = "") -> str:
    """
    List available BEL chart versions from the Helm repo.
    Call helm_repo_add first to ensure the repo is up to date.

    minor: optional 'X.Y' filter (e.g. '2.19') to return only that minor's
           releases sorted newest-first. Leave empty to return all versions.

    Each entry contains:
      'version'     — the Helm chart version to pass to helm install/upgrade --version
      'app_version' — the BEL version string (e.g. 'enterprise-2.19.4')
      'release_notes_url' — docs link for that minor

    The first entry when filtered by minor is the latest available patch.
    """
    raw = _helm_get(
        "/helm/search",
        {"chart": f"{BEL_HELM_REPO}/linkerd-enterprise-control-plane", "minor": minor},
    )
    try:
        data = json.loads(raw)
        versions = data.get("versions", [])
        for entry in versions:
            mm = _major_minor(entry.get("version", ""))
            entry["release_notes_url"] = BEL_RELEASE_NOTES_URL.format(minor=mm) if mm else ""
        return json.dumps(data, indent=4)
    except (json.JSONDecodeError, ValueError):
        return raw


def helm_repo_add(repo_name: str = BEL_HELM_REPO, repo_url: str = BEL_HELM_REPO_URL) -> str:
    """
    Add the Buoyant Enterprise Linkerd Helm repo and refresh the local cache.

    repo_name: local alias for the repo (default: 'linkerd-buoyant').
    repo_url: Helm repo URL (default: https://helm.buoyant.cloud).
    """
    return _helm_post("/helm/repo/add", {"repo_name": repo_name, "repo_url": repo_url})


def install_gateway_api_crds(version: str) -> str:
    """
    Install the Kubernetes Gateway API CRDs required by BEL.

    The manifest URL is chosen automatically based on the BEL major version:
      - 2.18.x → Gateway API v1.1.1 experimental-install.yaml
      - 2.19.x+ → Gateway API v1.2.1 standard-install.yaml

    version: the BEL version being installed (e.g. 'enterprise-2.19.4' or '2.18.7').
    """
    url = _gateway_api_manifest_url(version)
    result = _helm_post("/kubectl/apply", {"url": url})
    return f"Gateway API CRDs ({url}):\n{result}"


def generate_certificates(
    trust_anchor_lifetime: str = "87600h",
    issuer_lifetime: str = "8760h",
) -> str:
    """
    Generate a trust anchor and issuer certificate pair for BEL using the step CLI.
    Returns the PEM content of the generated certificates so they can be passed
    directly to helm_install_linkerd_control_plane or helm_upgrade_linkerd.

    trust_anchor_lifetime: validity period for the trust anchor (default: 87600h / 10 years).
    issuer_lifetime: validity period for the issuer certificate (default: 8760h / 1 year).
    """
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        ca_crt = os.path.join(tmpdir, "ca.crt")
        ca_key = os.path.join(tmpdir, "ca.key")
        iss_crt = os.path.join(tmpdir, "issuer.crt")
        iss_key = os.path.join(tmpdir, "issuer.key")

        anchor_result = _run(
            "step", "certificate", "create",
            "root.linkerd.cluster.local", ca_crt, ca_key,
            "--profile", "root-ca",
            "--no-password", "--insecure",
            "--not-after", trust_anchor_lifetime,
        )
        try:
            if "error" in json.loads(anchor_result):
                return json.dumps({"error": "Trust anchor generation failed.", "detail": anchor_result}, indent=4)
        except json.JSONDecodeError:
            pass

        issuer_result = _run(
            "step", "certificate", "create",
            "identity.linkerd.cluster.local", iss_crt, iss_key,
            "--profile", "intermediate-ca",
            "--not-after", issuer_lifetime,
            "--no-password", "--insecure",
            "--ca", ca_crt, "--ca-key", ca_key,
        )
        try:
            if "error" in json.loads(issuer_result):
                return json.dumps({"error": "Issuer cert generation failed.", "detail": issuer_result}, indent=4)
        except json.JSONDecodeError:
            pass

        return json.dumps({
            "ca_cert_pem": open(ca_crt).read(),
            "issuer_cert_pem": open(iss_crt).read(),
            "issuer_key_pem": open(iss_key).read(),
        }, indent=4)


def helm_install_linkerd_crds(version: str, namespace: str = "linkerd") -> str:
    """
    Install the linkerd-enterprise-crds Helm chart.

    version: the BEL Helm chart version (e.g. '2.19.4' or 'enterprise-2.19.4').
    namespace: target namespace (created if it does not exist).
    """
    return _helm_post("/helm/upgrade-install", {
        "release_name": "linkerd-enterprise-crds",
        "chart": f"{BEL_HELM_REPO}/linkerd-enterprise-crds",
        "version": _chart_version(version),
        "namespace": namespace,
        "create_namespace": True,
    })


def helm_install_linkerd_control_plane(
    version: str,
    license_key: str,
    ca_cert_pem: str,
    issuer_cert_pem: str,
    issuer_key_pem: str,
    namespace: str = "linkerd",
) -> str:
    """
    Install the linkerd-enterprise-control-plane Helm chart.

    version: the BEL Helm chart version (e.g. '2.19.4' or 'enterprise-2.19.4').
    license_key: the Buoyant Enterprise Linkerd license key (BUOYANT_LICENSE).
    ca_cert_pem: PEM content of the trust anchor certificate.
    issuer_cert_pem: PEM content of the issuer certificate.
    issuer_key_pem: PEM content of the issuer private key.
    namespace: target namespace (default: linkerd).
    """
    return _helm_post("/helm/upgrade-install", {
        "release_name": "linkerd-enterprise-control-plane",
        "chart": f"{BEL_HELM_REPO}/linkerd-enterprise-control-plane",
        "version": _chart_version(version),
        "namespace": namespace,
        "set_values": {"license": license_key},
        "set_file_values": {
            "identityTrustAnchorsPEM": ca_cert_pem,
            "identity.issuer.tls.crtPEM": issuer_cert_pem,
            "identity.issuer.tls.keyPEM": issuer_key_pem,
        },
    })


def helm_upgrade_linkerd(
    version: str,
    license_key: str,
    ca_cert_pem: str,
    issuer_cert_pem: str,
    issuer_key_pem: str,
    namespace: str = "linkerd",
) -> str:
    """
    Upgrade an existing BEL installation to a new version.

    version: the target BEL Helm chart version (e.g. '2.19.4' or 'enterprise-2.19.4').
    license_key: the Buoyant Enterprise Linkerd license key (BUOYANT_LICENSE).
    ca_cert_pem: PEM content of the trust anchor certificate.
    issuer_cert_pem: PEM content of the issuer certificate.
    issuer_key_pem: PEM content of the issuer private key.
    namespace: namespace where Linkerd is installed (default: linkerd).
    """
    crds = _helm_post("/helm/upgrade-install", {
        "release_name": "linkerd-enterprise-crds",
        "chart": f"{BEL_HELM_REPO}/linkerd-enterprise-crds",
        "version": _chart_version(version),
        "namespace": namespace,
    })
    cp = _helm_post("/helm/upgrade-install", {
        "release_name": "linkerd-enterprise-control-plane",
        "chart": f"{BEL_HELM_REPO}/linkerd-enterprise-control-plane",
        "version": _chart_version(version),
        "namespace": namespace,
        "set_values": {"license": license_key},
        "set_file_values": {
            "identityTrustAnchorsPEM": ca_cert_pem,
            "identity.issuer.tls.crtPEM": issuer_cert_pem,
            "identity.issuer.tls.keyPEM": issuer_key_pem,
        },
    })
    return f"CRDs upgrade:\n{crds}\n\nControl-plane upgrade:\n{cp}"


def helm_configure_linkerd(
    key: str,
    value: str,
    release: str = "linkerd-enterprise-control-plane",
    namespace: str = "linkerd",
) -> str:
    """
    Change a single Helm value on an existing BEL release without regenerating
    certificates or re-supplying any other previously set value.

    Uses 'helm upgrade --reuse-values --set key=value' so certs, license, and
    all other existing values are preserved.  If the key was already set to a
    different value it is correctly overridden.

    Common use-cases:
      key="controllerLogLevel", value="debug"        → enable debug logging
      key="controllerLogLevel", value="info"         → revert to info
      key="proxy.logLevel",     value="warn,linkerd=info"

    key: Helm value key in dot-notation (e.g. 'controllerLogLevel').
    value: the new value to set (e.g. 'debug').
    release: Helm release name (default: 'linkerd-enterprise-control-plane').
    namespace: namespace of the release (default: linkerd).
    """
    chart = f"{BEL_HELM_REPO}/{release}"
    return _helm_post("/helm/configure", {
        "release_name": release,
        "chart": chart,
        "namespace": namespace,
        "set_values": {key: value},
    })


def helm_uninstall_linkerd(
    namespace: str = "linkerd",
    control_plane_release: str = "linkerd-enterprise-control-plane",
    crds_release: str = "linkerd-enterprise-crds",
) -> str:
    """
    Uninstall BEL control-plane and CRDs from the cluster.

    namespace: namespace where Linkerd is installed (default: linkerd).
    control_plane_release: Helm release name for the control plane
        (default: 'linkerd-enterprise-control-plane').
    crds_release: Helm release name for the CRDs chart
        (default: 'linkerd-enterprise-crds').

    If you are unsure of the release names, call helm_status first — it will
    list all available releases in the namespace when the default is not found.
    """
    cp = _helm_post("/helm/uninstall", {
        "release_name": control_plane_release,
        "namespace": namespace,
    })
    crds = _helm_post("/helm/uninstall", {
        "release_name": crds_release,
        "namespace": namespace,
    })
    return f"control-plane ({control_plane_release}):\n{cp}\n\nCRDs ({crds_release}):\n{crds}"


def helm_status(
    release: str = "linkerd-enterprise-control-plane",
    namespace: str = "linkerd",
) -> str:
    """
    Show the Helm release status for a BEL release.

    release: the Helm release name (default: 'linkerd-enterprise-control-plane').
    namespace: namespace where the release is installed (default: linkerd).
    """
    return _helm_get("/helm/status", {"release": release, "namespace": namespace})


def linkerd_check(proxy: bool = False, namespace: str = "linkerd") -> str:
    """
    Run 'linkerd check' to verify the BEL installation health.
    Falls back to kubectl get pods (via helm agent) when the linkerd CLI is not installed.

    proxy: if True, also validate data-plane proxy health (linkerd check --proxy).
    namespace: namespace to inspect when falling back to kubectl (default: linkerd).
    """
    args = ["linkerd", "check"]
    if proxy:
        args.append("--proxy")
    result = _run(*args)
    try:
        parsed = json.loads(result)
        if "error" in parsed and "not found" in parsed.get("error", ""):
            pods = _helm_get("/kubectl/pods", {"namespace": namespace})
            return json.dumps({
                "warning": "'linkerd' CLI not found; showing kubectl pod status as a fallback.",
                "namespace": namespace,
                "pods": pods,
            }, indent=4)
    except (json.JSONDecodeError, ValueError):
        pass
    return result
