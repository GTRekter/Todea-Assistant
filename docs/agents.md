# Agents & MCP Tools

## Agent structure

The MCP server hosts a hierarchy of ADK agents and HTTP tool services. `linkerd_agent` is the root ADK agent; `kubernetes_agent` is its only ADK sub-agent. The remaining agents (`openssl_agent`, `helm_agent`, `github_agent`) are standalone HTTP services whose tool functions are imported directly into the MCP server and registered as MCP tools.

```
MCP Server (server.py)
  │
  ├── linkerd_agent  (ADK root — Helm/Linkerd orchestration)
  │     └── kubernetes_agent   (ADK sub-agent — kubectl diagnostics)
  │
  └── MCP tools registered directly from:
        ├── linkerd_agent.tools   (Helm + Linkerd + composite install)
        ├── openssl_agent.tools   (X.509 certificate operations)
        └── kubernetes_agent.tools (kubectl inspection)
```

**HTTP services** (called by `linkerd_agent.tools` over HTTP, not registered as MCP tools directly):

```
Helm Agent   :3400  ← linkerd_agent.tools calls this for all helm/kubectl writes
```

**Standalone HTTP service** (independent, not yet wired into the MCP tool registry):

```
OpenSSL Agent  :3500  ← exposes the same certificate tools via REST
GitHub Agent   :3600  ← GitHub REST API wrapper (file, search, issue, PR)
```

Each agent package follows the same file layout:

```
<agent>/
  __init__.py
  tools.py         ← pure functions, no framework dependency
  app.py           ← FastAPI HTTP service (HTTP agents) or ADK Agent (ADK agents)
  instructions.py  ← system prompt string
  requirements.txt
```

When deployed in-cluster, the MCP pod runs with a dedicated ServiceAccount bound to a read-only ClusterRole (`todea-mcp-reader`), granting `kubernetes_agent` permission to read pods, logs, events, nodes, namespaces, deployments, and services without write access.

---

## linkerd_agent

Root ADK agent. Orchestrates BEL installs, upgrades, and health checks. All `helm` and `kubectl` write operations are delegated to the Helm Agent over HTTP — the MCP pod has no helm/kubectl write dependencies itself. Certificate operations are handled in-process via `openssl_agent.tools`.

**Linkerd / Helm tools** (via Helm Agent HTTP at `HELM_AGENT_URL`):

| Tool | Description |
|---|---|
| `helm_repo_add` | Register the Buoyant Helm repo (`linkerd-buoyant` / `https://helm.buoyant.cloud`) |
| `helm_search_bel_versions` | List available BEL chart versions; filter by X.Y minor |
| `install_gateway_api_crds` | Apply the Gateway API CRD manifest for the target BEL version |
| `helm_install_linkerd_crds` | `helm upgrade --install linkerd-enterprise-crds` |
| `helm_install_linkerd_control_plane` | `helm upgrade --install linkerd-enterprise-control-plane` with cert PEMs |
| `install_linkerd_control_plane` | **Composite** — generates certs then installs the control plane in one step |
| `helm_upgrade_linkerd` | Upgrade both CRDs and control-plane charts to a new version |
| `helm_configure_linkerd` | Change a single Helm value with `--reuse-values`; preserves certs and license |
| `helm_uninstall_linkerd` | Uninstall both Linkerd Helm releases |
| `helm_status` | Show Helm release status; lists available releases on name miss |
| `linkerd_check` | `linkerd check` — falls back to `kubectl get pods` if the CLI is absent |

**Certificate tools** (via `openssl_agent.tools`, in-process):

| Tool | Description |
|---|---|
| `generate_certificates` | Generate a trust-anchor + issuer cert pair; returns PEM strings ready for Helm |
| `inspect_certificate` | Parse a PEM certificate and return subject, issuer, validity window, days remaining, CA flag, path length, and SANs |
| `verify_certificate_chain` | Verify that an issuer cert was signed by a given CA; reports DN match and expiry status |

---

## kubernetes_agent

ADK sub-agent of `linkerd_agent`. Diagnoses Kubernetes workload problems by running `kubectl` directly against the cluster.

| Tool | Description |
|---|---|
| `get_namespaces` | List all namespaces in the cluster |
| `get_nodes` | List nodes with status, roles, and Kubernetes version |
| `get_pods` | List pods with status and restart counts; scoped to a namespace or cluster-wide |
| `get_deployments` | List deployments with desired / ready / available replica counts |
| `get_pod_containers` | List container names in a pod — call before `get_pod_logs` when unsure of the container name |
| `get_pod_logs` | Fetch logs from a container; `previous=true` returns the last crash's logs |
| `describe_pod` | Full `kubectl describe pod` output including the Events section |
| `get_events` | List events in a namespace, optionally filtered to a single pod |
| `diagnose_pod_restarts` | **Composite** — runs containers + current/previous logs + events in one call; use this first for any CrashLoopBackOff |

---

## openssl_agent

HTTP service and in-process tool library. Generates, inspects, and verifies X.509 certificates entirely in-process using the Python `cryptography` library — no `openssl` or `step` binary required.

Its tools are registered directly in the MCP server and also exposed via a standalone FastAPI service (`app.py`, port 3500).

| Tool | Description |
|---|---|
| `generate_certificates` | Generate a trust-anchor + issuer cert pair with configurable lifetimes |
| `inspect_certificate` | Parse a PEM certificate and return full metadata |
| `verify_certificate_chain` | Verify that an issuer cert was signed by a given CA cert |

---

## helm_agent

HTTP service (`app.py`, port 3400). Generic, domain-agnostic wrapper around `helm` and `kubectl` subprocesses. Has no knowledge of Linkerd — chart names, release names, values, and cert field names are all supplied by the caller.

The `set_file_values` field in `POST /helm/upgrade-install` accepts file content as strings; the agent writes them to a temporary directory, passes `--set-file` flags to Helm, and cleans up automatically.

| Endpoint | Description |
|---|---|
| `POST /helm/repo/add` | Register a Helm repository |
| `GET  /helm/search?chart=&minor=` | Search chart versions; optional X.Y minor filter |
| `POST /helm/upgrade-install` | `helm upgrade --install` with `set_values` and `set_file_values` |
| `POST /helm/configure` | `helm upgrade --reuse-values --set key=value` |
| `POST /helm/uninstall` | Uninstall a release |
| `GET  /helm/status?release=&namespace=` | Release status; returns available releases on miss |
| `GET  /helm/list?namespace=` | List all releases in a namespace |
| `POST /kubectl/apply` | `kubectl apply -f <url>` |
| `GET  /kubectl/pods?namespace=` | `kubectl get pods -o wide` |

---

## github_agent

Standalone HTTP service (`app.py`, port 3600). Retrieves code, issues, and pull requests from public GitHub repositories. Set `GITHUB_TOKEN` to raise the API rate limit from 60 to 5000 requests/hour.

| Endpoint | Description |
|---|---|
| `GET /github/file?repo=&path=&ref=` | Fetch the raw content of a file |
| `GET /github/directory?repo=&path=&ref=` | List directory contents |
| `GET /github/search?repo=&query=` | Search code within a repository |
| `GET /github/issue?repo=&number=` | Fetch an issue with its comments |
| `GET /github/pr?repo=&number=` | Fetch a pull request with changed files |

---

## Install sequence (fresh install)

The `linkerd_agent` follows this exact order, stopping on any error:

```
1. helm_repo_add                      (no args — defaults are always correct)
2. helm_status                        (check for existing CRDs release)
3. install_gateway_api_crds           (version)
4. helm_install_linkerd_crds          (version)
5. install_linkerd_control_plane      (version, license_key)
     └── internally: generate_certificates → helm_install_linkerd_control_plane
6. linkerd_check                      (verify installation health)
7. helm_status                        (confirm release details)
```

Use `install_linkerd_control_plane` (step 5) for fresh installs — it generates certificates and installs the control plane in one step, avoiding the need to pass large PEM strings between tool calls.
