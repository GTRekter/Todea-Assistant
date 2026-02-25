import json
import re
import subprocess

CLI_TIMEOUT = 120  # seconds — Helm installs can take time

BEL_HELM_REPO = "linkerd-buoyant"
BEL_HELM_REPO_URL = "https://helm.buoyant.cloud"

# Gateway API CRD manifests differ between BEL major versions:
#   2.18 → experimental-install.yaml (v1.1.1) — transition release
#   2.19+ → standard-install.yaml   (v1.2.1) — Linkerd no longer owns Gateway API CRDs
_GATEWAY_API_MANIFESTS = {
    "2.18": "https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.1.1/experimental-install.yaml",
    "2.19": "https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.2.1/standard-install.yaml",
}
_GATEWAY_API_DEFAULT = _GATEWAY_API_MANIFESTS["2.19"]

BEL_RELEASE_NOTES_URL = "https://docs.buoyant.io/buoyant-enterprise-linkerd/{minor}/release-notes/"


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
    result = _run(
        "helm", "search", "repo",
        f"{BEL_HELM_REPO}/linkerd-enterprise-control-plane",
        "--versions", "--output", "json",
    )
    try:
        versions = json.loads(result)
        if not isinstance(versions, list):
            return result
        for entry in versions:
            mm = _major_minor(entry.get("version", ""))
            entry["release_notes_url"] = BEL_RELEASE_NOTES_URL.format(minor=mm) if mm else ""
        if minor:
            filtered = [v for v in versions if _major_minor(v.get("version", "")) == minor]
            if not filtered:
                return json.dumps({
                    "error": f"No BEL versions found for minor '{minor}'.",
                    "available_minors": sorted({_major_minor(v.get("version", "")) for v in versions}, reverse=True),
                }, indent=4)
            return json.dumps(filtered, indent=4)
        return json.dumps(versions, indent=4)
    except (json.JSONDecodeError, ValueError):
        return result


def helm_repo_add(repo_name: str = BEL_HELM_REPO, repo_url: str = BEL_HELM_REPO_URL) -> str:
    """
    Add the Buoyant Enterprise Linkerd Helm repo and refresh the local cache.

    repo_name: local alias for the repo (default: 'linkerd-buoyant').
    repo_url: Helm repo URL (default: https://helm.buoyant.cloud).
    """
    add = _run("helm", "repo", "add", repo_name, repo_url, "--force-update")
    update = _run("helm", "repo", "update", repo_name)
    return f"repo add:\n{add}\n\nrepo update:\n{update}"


def install_gateway_api_crds(version: str) -> str:
    """
    Install the Kubernetes Gateway API CRDs required by BEL.

    The manifest URL is chosen automatically based on the BEL major version:
      - 2.18.x → Gateway API v1.1.1 experimental-install.yaml
      - 2.19.x+ → Gateway API v1.2.1 standard-install.yaml

    version: the BEL version being installed (e.g. 'enterprise-2.19.4' or '2.18.7').
    """
    url = _gateway_api_manifest_url(version)
    result = _run("kubectl", "apply", "-f", url)
    return f"Gateway API CRDs ({url}):\n{result}"


def generate_certificates(
    trust_anchor_cert: str = "ca.crt",
    trust_anchor_key: str = "ca.key",
    issuer_cert: str = "issuer.crt",
    issuer_key: str = "issuer.key",
    trust_anchor_lifetime: str = "87600h",
    issuer_lifetime: str = "8760h",
) -> str:
    """
    Generate a trust anchor and issuer certificate pair for BEL using the step CLI.

    trust_anchor_cert: output path for the trust anchor certificate (default: ca.crt).
    trust_anchor_key: output path for the trust anchor private key (default: ca.key).
    issuer_cert: output path for the issuer certificate (default: issuer.crt).
    issuer_key: output path for the issuer private key (default: issuer.key).
    trust_anchor_lifetime: validity period for the trust anchor (default: 87600h / 10 years).
    issuer_lifetime: validity period for the issuer certificate (default: 8760h / 1 year).
    """
    anchor_result = _run(
        "step", "certificate", "create",
        "root.linkerd.cluster.local", trust_anchor_cert, trust_anchor_key,
        "--profile", "root-ca",
        "--no-password", "--insecure",
        "--not-after", trust_anchor_lifetime,
    )
    try:
        parsed = json.loads(anchor_result)
        if "error" in parsed:
            return f"Trust anchor generation failed:\n{anchor_result}"
    except json.JSONDecodeError:
        pass  # plain text success output

    issuer_result = _run(
        "step", "certificate", "create",
        "identity.linkerd.cluster.local", issuer_cert, issuer_key,
        "--profile", "intermediate-ca",
        "--not-after", issuer_lifetime,
        "--no-password", "--insecure",
        "--ca", trust_anchor_cert, "--ca-key", trust_anchor_key,
    )
    return f"Trust anchor:\n{anchor_result}\n\nIssuer certificate:\n{issuer_result}"


def helm_install_linkerd_crds(version: str, namespace: str = "linkerd") -> str:
    """
    Install the linkerd-enterprise-crds Helm chart.

    version: the BEL Helm chart version (e.g. '2.19.4' or 'enterprise-2.19.4').
    namespace: target namespace (created if it does not exist).
    """
    cv = _chart_version(version)
    return _run(
        "helm", "upgrade", "--install", "linkerd-enterprise-crds",
        f"{BEL_HELM_REPO}/linkerd-enterprise-crds",
        "--version", cv,
        "--namespace", namespace,
        "--create-namespace",
    )


def helm_install_linkerd_control_plane(
    version: str,
    license_key: str,
    ca_cert: str = "ca.crt",
    issuer_cert: str = "issuer.crt",
    issuer_key: str = "issuer.key",
    namespace: str = "linkerd",
) -> str:
    """
    Install the linkerd-enterprise-control-plane Helm chart.

    version: the BEL Helm chart version (e.g. '2.19.4' or 'enterprise-2.19.4').
    license_key: the Buoyant Enterprise Linkerd license key (BUOYANT_LICENSE).
    ca_cert: path to the trust anchor certificate file (default: ca.crt).
    issuer_cert: path to the issuer certificate file (default: issuer.crt).
    issuer_key: path to the issuer private key file (default: issuer.key).
    namespace: target namespace (default: linkerd).
    """
    cv = _chart_version(version)
    return _run(
        "helm", "upgrade", "--install", "linkerd-enterprise-control-plane",
        f"{BEL_HELM_REPO}/linkerd-enterprise-control-plane",
        "--version", cv,
        "--namespace", namespace,
        "--set", f"license={license_key}",
        "--set-file", f"identityTrustAnchorsPEM={ca_cert}",
        "--set-file", f"identity.issuer.tls.crtPEM={issuer_cert}",
        "--set-file", f"identity.issuer.tls.keyPEM={issuer_key}",
    )


def helm_upgrade_linkerd(
    version: str,
    license_key: str,
    ca_cert: str = "ca.crt",
    issuer_cert: str = "issuer.crt",
    issuer_key: str = "issuer.key",
    namespace: str = "linkerd",
) -> str:
    """
    Upgrade an existing BEL installation to a new version.

    version: the target BEL Helm chart version (e.g. '2.19.4' or 'enterprise-2.19.4').
    license_key: the Buoyant Enterprise Linkerd license key (BUOYANT_LICENSE).
    ca_cert: path to the trust anchor certificate file (default: ca.crt).
    issuer_cert: path to the issuer certificate file (default: issuer.crt).
    issuer_key: path to the issuer private key file (default: issuer.key).
    namespace: namespace where Linkerd is installed (default: linkerd).
    """
    cv = _chart_version(version)
    crds = _run(
        "helm", "upgrade", "linkerd-enterprise-crds",
        f"{BEL_HELM_REPO}/linkerd-enterprise-crds",
        "--version", cv,
        "--namespace", namespace,
    )
    cp = _run(
        "helm", "upgrade", "linkerd-enterprise-control-plane",
        f"{BEL_HELM_REPO}/linkerd-enterprise-control-plane",
        "--version", cv,
        "--namespace", namespace,
        "--set", f"license={license_key}",
        "--set-file", f"identityTrustAnchorsPEM={ca_cert}",
        "--set-file", f"identity.issuer.tls.crtPEM={issuer_cert}",
        "--set-file", f"identity.issuer.tls.keyPEM={issuer_key}",
    )
    return f"CRDs upgrade:\n{crds}\n\nControl-plane upgrade:\n{cp}"


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
    cp = _run("helm", "uninstall", control_plane_release, "--namespace", namespace)
    crds = _run("helm", "uninstall", crds_release, "--namespace", namespace)
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
    result = _run("helm", "status", release, "--namespace", namespace, "--output", "json")
    try:
        parsed = json.loads(result)
        if "error" in parsed:
            available = _run("helm", "list", "--namespace", namespace, "--output", "json")
            return json.dumps({
                "error": f"Release '{release}' not found in namespace '{namespace}'.",
                "hint": "Use the correct release name from 'available_releases' and retry.",
                "available_releases": json.loads(available) if available else [],
            }, indent=4)
    except (json.JSONDecodeError, ValueError):
        pass
    return result


def linkerd_check(proxy: bool = False, namespace: str = "linkerd") -> str:
    """
    Run 'linkerd check' to verify the BEL installation health.
    Falls back to 'kubectl get pods' when the linkerd CLI is not installed.

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
            pods = _run("kubectl", "get", "pods", "-n", namespace, "-o", "wide")
            return json.dumps({
                "warning": "'linkerd' CLI not found; showing kubectl pod status as a fallback.",
                "namespace": namespace,
                "pods": pods,
            }, indent=4)
    except (json.JSONDecodeError, ValueError):
        pass
    return result
