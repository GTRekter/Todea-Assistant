# Agents & MCP Tools

## Multi-agent architecture

The system uses a **model-agnostic hierarchical agent architecture**. All providers (Google, Azure, Ollama) share the same orchestration logic — only the LLM API call differs.

```
Root Agent (any provider) — pure dispatcher
  │
  │  Sees only 5 virtual tools (call_*_agent)
  │
  ├── call_kubernetes_agent(task)
  ├── call_openssl_agent(task)
  ├── call_github_agent(task)
  ├── call_helm_agent(task)
  └── call_linkerd_agent(task)
        │
        ▼
  Sub-agents run inside agent-hub/sub_agent.py as nested agentic loops.
  Each sub-agent has its own instructions and a restricted set of MCP tools.

MCP Server (servers/mcp/) — pure tool server
  ├── GET /mcp    — FastMCP endpoint (all raw tools)
  └── GET /agents — JSON list of agent configs (name, instructions, tool list)
```

### How a request flows

1. The root agent receives the user message and decides which specialist to call.
2. `agent-hub` detects a `call_*_agent` tool call and routes it to `run_sub_agent()` in `sub_agent.py`.
3. `sub_agent.py` calls `GET /agents` on the MCP server to fetch the sub-agent's instructions and allowed tool names, then calls `_list_all_mcp_tools()` to get the full MCP tool schemas.
4. It runs a non-streaming provider-specific loop (Ollama / Azure / Google), calling only the tools owned by the sub-agent.
5. The loop returns a plain string; the root agent receives it as a tool result and summarises for the user.

### Key files

| File | Purpose |
|---|---|
| `servers/agent-hub/sub_agent.py` | `run_sub_agent(name, task, provider, model)` + per-provider loops |
| `servers/agent-hub/mcp_utils.py` | `_list_mcp_tools()` (root — filtered + 5 virtuals) · `_list_all_mcp_tools()` (sub-agents — unfiltered) |
| `servers/agent-hub/config.py` | `DEFAULT_INSTRUCTION` (root dispatcher system prompt) |
| `servers/agent-hub/providers/*.py` | Provider-specific streaming loops; intercept `call_*_agent` → `run_sub_agent()` |
| `servers/mcp/*/config.py` | Each agent's `AGENT_CONFIG` dict (name, instructions, tool list) |
| `servers/mcp/app.py` | FastMCP ASGI app wrapped in Starlette; adds `GET /agents` route |
| `servers/mcp/helm_agent/mcp_tools.py` | Generic helm MCP tools (HTTP wrappers around the Helm Agent service) |

### Agent package layout

Each HTTP service follows the same layout:

```
<agent>/
  __init__.py
  config.py        ← env vars + AGENT_CONFIG dict (name, instructions, tools list)
  schemas.py       ← Pydantic request models (where needed)
  tools.py         ← pure functions, no framework dependency
  app.py           ← slim FastAPI app
  instructions.py  ← system prompt string
  requirements.txt
  routes/
    __init__.py
    health.py      ← GET /healthz
    <domain>.py    ← domain endpoints
  Dockerfile
```

The MCP server imports `AGENT_CONFIG` from each sub-package and serves all configs at `GET /agents`.

---

## kubernetes_agent

FastAPI HTTP service (port 3700). Diagnoses Kubernetes workload problems by running `kubectl` directly against the cluster. Granted read-only cluster access via the `todea-mcp-reader` ClusterRole.

**MCP tools** (owned exclusively by this sub-agent):

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

**HTTP endpoints:**

| Endpoint | Description |
|---|---|
| `GET /kubernetes/namespaces` | List all namespaces |
| `GET /kubernetes/nodes` | List nodes with status and version |
| `GET /kubernetes/pods?namespace=` | List pods; cluster-wide when namespace is omitted |
| `GET /kubernetes/deployments?namespace=` | List deployments with replica counts |
| `GET /kubernetes/events?namespace=&pod_name=` | List events, optionally filtered to one pod |
| `GET /kubernetes/pods/{pod}/containers?namespace=` | List container names in a pod |
| `GET /kubernetes/pods/{pod}/logs?namespace=&container=&previous=&tail_lines=` | Fetch container logs |
| `GET /kubernetes/pods/{pod}/describe?namespace=` | Full `kubectl describe pod` output |
| `GET /kubernetes/pods/{pod}/diagnose?namespace=` | Composite: containers + current/previous logs + events |

---

## openssl_agent

FastAPI HTTP service (port 3500). Generates, inspects, and verifies X.509 certificates entirely in-process using the Python `cryptography` library — no `openssl` binary required.

**MCP tools** (owned exclusively by this sub-agent):

| Tool | Description |
|---|---|
| `generate_certificates` | Generate a trust-anchor + issuer cert pair with configurable lifetimes; returns PEM strings ready for Helm |
| `inspect_certificate` | Parse a PEM certificate and return subject, issuer, validity window, days remaining, CA flag, path length, and SANs |
| `verify_certificate_chain` | Verify that an issuer cert was signed by a given CA; reports DN match and expiry status |

**HTTP endpoints:**

| Endpoint | Description |
|---|---|
| `POST /certificates/generate` | Generate a trust anchor + issuer cert pair |
| `POST /certificates/inspect` | Parse and display a PEM certificate |
| `POST /certificates/verify` | Verify an issuer cert was signed by a given CA |

---

## github_agent

Standalone HTTP service (port 3600). Retrieves code, issues, and pull requests from public GitHub repositories. Set `GITHUB_TOKEN` to raise the API rate limit from 60 to 5,000 requests/hour.

**MCP tools** (owned exclusively by this sub-agent):

| Tool | Description |
|---|---|
| `github_get_file` | Fetch the raw content of a file from a repository |
| `github_list_directory` | List directory contents at a path |
| `github_search_code` | Search code within a repository |
| `github_get_issue` | Fetch an issue with its comments |
| `github_get_pr` | Fetch a pull request with changed files |

**HTTP endpoints:**

| Endpoint | Description |
|---|---|
| `GET /github/file?repo=&path=&ref=` | Fetch the raw content of a file |
| `GET /github/directory?repo=&path=&ref=` | List directory contents |
| `GET /github/search?repo=&query=` | Search code within a repository |
| `GET /github/issue?repo=&number=` | Fetch an issue with its comments |
| `GET /github/pr?repo=&number=` | Fetch a pull request with changed files |

---

## helm_agent

HTTP service (port 3400). Generic, domain-agnostic wrapper around `helm` and `kubectl` subprocesses. Has no knowledge of Linkerd — chart names, release names, values, and cert field names are all supplied by the caller.

The `set_file_values` field in `POST /helm/upgrade-install` accepts file content as strings; the service writes them to a temporary directory, passes `--set-file` flags to Helm, and cleans up automatically.

**MCP tools** (owned exclusively by this sub-agent, defined in `helm_agent/mcp_tools.py`):

| Tool | Description |
|---|---|
| `helm_generic_repo_add` | Register a Helm repository |
| `helm_generic_search` | Search chart versions; optional X.Y minor filter |
| `helm_generic_upgrade_install` | `helm upgrade --install` with values and file-values support |
| `helm_generic_status` | Show Helm release status; lists available releases on name miss |
| `helm_generic_list` | List all releases in a namespace |
| `helm_generic_uninstall` | Uninstall a release |
| `kubectl_apply` | `kubectl apply -f <url>` |
| `kubectl_pods` | `kubectl get pods -o wide` scoped to a namespace |

**HTTP endpoints:**

| Endpoint | Description |
|---|---|
| `POST /helm/repo/add` | Register a Helm repository |
| `GET  /helm/search?chart=&minor=` | Search chart versions; optional X.Y filter |
| `POST /helm/upgrade-install` | `helm upgrade --install` with `set_values` and `set_file_values` |
| `POST /helm/configure` | `helm upgrade --reuse-values --set key=value` |
| `POST /helm/uninstall` | Uninstall a release |
| `GET  /helm/status?release=&namespace=` | Release status; returns available releases on miss |
| `GET  /helm/list?namespace=` | List all releases in a namespace |
| `POST /kubectl/apply` | `kubectl apply -f <url>` |
| `GET  /kubectl/pods?namespace=` | `kubectl get pods -o wide` |

---

## linkerd_agent

FastAPI HTTP service (port 3800). Orchestrates BEL installs, upgrades, and health checks. All `helm` and `kubectl` write operations are delegated to the Helm Agent over HTTP.

**MCP tools** (owned exclusively by this sub-agent):

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

**HTTP endpoints:**

| Endpoint | Description |
|---|---|
| `GET  /linkerd/versions?minor=` | List available BEL chart versions |
| `POST /linkerd/repo/add` | Register the Buoyant Helm repository |
| `POST /linkerd/control-plane/install` | Generate certs + install control plane (composite) |
| `POST /linkerd/upgrade` | Upgrade CRDs and control plane |
| `GET  /linkerd/status?release=&namespace=` | Helm release status |
| `GET  /linkerd/check?proxy=&namespace=` | Run `linkerd check` |

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
