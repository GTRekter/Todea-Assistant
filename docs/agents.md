# Agents & MCP Tools

## MCP agent hierarchy

The MCP server hosts a hierarchy of three ADK agents. The `linkerd_agent` is the root and delegates specialised tasks to two sub-agents via `AgentTool`:

```
linkerd_agent  (root — Helm/Linkerd orchestration)
  ├── openssl_agent      (X.509 certificate generation and inspection)
  └── kubernetes_agent   (kubectl-based cluster diagnostics)
```

When deployed in-cluster, the MCP pod runs with a dedicated ServiceAccount bound to a read-only ClusterRole (`todea-mcp-reader`), which grants the `kubernetes_agent` permission to read pods, logs, events, nodes, namespaces, deployments, and services across the cluster without write access.

---

## linkerd_agent

Orchestrates Buoyant Enterprise Linkerd (BEL) installs, upgrades, and health checks. All Helm and kubectl write operations are delegated to the Helm Agent over HTTP — the MCP container itself has no write CLI dependencies for those tasks.

**Helm / Kubernetes tools** (via Helm Agent HTTP):

| Tool | Description |
|---|---|
| `helm_repo_add` | Register the Buoyant Helm repo (`linkerd-buoyant` / `https://helm.buoyant.cloud`) |
| `helm_search_bel_versions` | List available BEL chart versions; filter by X.Y minor |
| `install_gateway_api_crds` | Apply the Gateway API CRD manifest for the target BEL version |
| `helm_install_linkerd_crds` | `helm upgrade --install linkerd-enterprise-crds` |
| `helm_install_linkerd_control_plane` | `helm upgrade --install linkerd-enterprise-control-plane` with cert PEMs |
| `install_linkerd_control_plane` | Composite: generates certs then installs the control plane in one step |
| `helm_upgrade_linkerd` | Upgrade both the CRDs and control-plane charts to a new version |
| `helm_configure_linkerd` | Change a single Helm value with `--reuse-values`; preserves certs and license |
| `helm_uninstall_linkerd` | Uninstall both Linkerd Helm releases |
| `helm_status` | Show the status of a Helm release; lists available releases on miss |
| `linkerd_check` | `linkerd check` — falls back to `kubectl get pods` if the CLI is absent |

---

## openssl_agent

Generates, inspects, and verifies X.509 certificates. Runs entirely in-process using the Python `cryptography` library — no `openssl` or `step` binary required.

| Tool | Description |
|---|---|
| `generate_certificates` | Generate a trust-anchor + issuer cert pair; returns PEM strings ready for Helm |
| `inspect_certificate` | Parse a PEM certificate and return subject, issuer, validity window, days remaining, CA flag, path length, and SANs |
| `verify_certificate_chain` | Verify that an issuer cert was signed by a given CA cert; reports DN match and expiry status |

---

## kubernetes_agent

Diagnoses Kubernetes workload problems by running `kubectl` directly against the cluster. Called by `linkerd_agent` when asked to inspect pods, explain restarts, or investigate CrashLoopBackOff conditions.

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

## Install sequence (fresh install)

The agent follows this exact order — stopping on any error:

```
1. helm_repo_add                    (no args — defaults are always correct)
2. install_gateway_api_crds         (version)
3. generate_certificates            (via openssl_agent — no args)
4. helm_install_linkerd_crds        (version)
5. helm_install_linkerd_control_plane (version, license_key, + 3 PEM strings from step 3)
6. linkerd_check                    (verify — falls back to kubernetes_agent.get_pods if CLI absent)
```

---

## Helm Agent

The Helm Agent (`servers/mcp/helm-agent/`) is a generic, domain-agnostic HTTP service that wraps `helm` and `kubectl` as subprocesses. It has no knowledge of Linkerd or Buoyant — chart names, release names, values, and certificate field names are all supplied by the caller. The `set_file_values` field in `POST /helm/upgrade-install` accepts file content as strings; the agent writes them to a temporary directory, passes `--set-file` flags to helm, and cleans up automatically.
