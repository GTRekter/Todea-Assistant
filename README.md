# Todea-Assistant

Kubernetes-native AI platform with a React chat UI for installing, managing, and diagnosing a Linkerd service mesh through natural language. Supports Google Gemini, Azure OpenAI, or a fully in-cluster Ollama runtime — all providers get identical hierarchical multi-agent behaviour.

![Screenshot of the Todea-Assistant demo](assets/sample.png)

---

## Architecture

| Service | Path | Port | Role |
|---|---|---|---|
| **Web** | `web/` | 80 | React SPA + Express static server |
| **Agent Hub** | `servers/agent-hub/` | 3100 | Unified LLM gateway — routes to Google, Azure, or Ollama; runs the root dispatcher agent and all sub-agent loops |
| **MCP Server** | `servers/mcp/` | 3002 | FastMCP tool server; exposes all raw tools over MCP and serves `GET /agents` with sub-agent configs |
| **Helm Agent** | `servers/mcp/helm_agent/` | 3400 | HTTP wrapper around `helm` and `kubectl`; called by the MCP server |
| **OpenSSL Agent** | `servers/mcp/openssl_agent/` | 3500 | HTTP wrapper for X.509 certificate generation, inspection, and verification |
| **GitHub Agent** | `servers/mcp/github_agent/` | 3600 | HTTP wrapper around the GitHub REST API |
| **Kubernetes Agent** | `servers/mcp/kubernetes_agent/` | 3700 | HTTP wrapper around `kubectl` |
| **Linkerd Agent** | `servers/mcp/linkerd_agent/` | 3800 | HTTP wrapper around BEL Helm operations and certificate management |
| **Conversation Hub** | `servers/conversation-hub/` | 3300 | Shared conversation + message store for all providers |
| **Training Hub** | `servers/training-hub/` | 3500 | REST + SSE service that manages the ML training pipeline |
| **Ollama Runtime** _(optional)_ | `servers/ollama-runtime/` | 11434 | Custom Ollama image with the model pre-baked |

### Multi-agent hierarchy

The system uses a **model-agnostic hierarchical agent architecture**. Every provider (Google, Azure, Ollama) gets the same behaviour:

```
Root Agent (any provider) — pure dispatcher
  Sees only 5 virtual tools:
    call_kubernetes_agent(task)  — pod/log/event diagnostics
    call_openssl_agent(task)     — cert generate/inspect/verify
    call_github_agent(task)      — repo file/issue/PR lookups
    call_helm_agent(task)        — generic Helm/kubectl operations
    call_linkerd_agent(task)     — BEL install/upgrade/check

Sub-agents (nested loops in agent-hub, any provider):
  kubernetes_agent — 9 kubectl tools
  openssl_agent   — 3 certificate tools
  github_agent    — 5 GitHub API tools
  helm_agent      — 8 generic helm/kubectl tools
  linkerd_agent   — 11 BEL-specific helm/linkerd tools
```

**How it works:**

1. The root agent receives the user's message and decides which specialist to call.
2. `agent-hub` intercepts `call_*_agent` tool calls and runs `run_sub_agent()` in `sub_agent.py`.
3. `sub_agent.py` fetches the sub-agent's instructions and allowed tool list from `GET /agents` on the MCP server, then runs a non-streaming agentic loop with the same provider and model as the root agent.
4. The sub-agent loop calls only the MCP tools it owns; results flow back to the root agent as a plain string.

**Key files:**

| File | Purpose |
|---|---|
| `servers/agent-hub/sub_agent.py` | `run_sub_agent(name, task, provider, model)` — per-provider nested loops |
| `servers/agent-hub/mcp_utils.py` | `_list_mcp_tools()` (root, filtered + virtual) · `_list_all_mcp_tools()` (sub-agents) |
| `servers/agent-hub/config.py` | `DEFAULT_INSTRUCTION` (root dispatcher prompt) |
| `servers/mcp/*/config.py` | Each agent's `AGENT_CONFIG` dict (name, instructions, tool list) |
| `servers/mcp/app.py` | FastMCP ASGI + Starlette `GET /agents` route |
| `servers/mcp/helm_agent/mcp_tools.py` | Generic helm MCP tools (HTTP wrappers, not subprocess) |

### Tool ownership

| Sub-Agent | MCP Tools |
|---|---|
| **kubernetes** | `get_namespaces`, `get_nodes`, `get_pods`, `get_deployments`, `get_pod_containers`, `get_pod_logs`, `describe_pod`, `get_events`, `diagnose_pod_restarts` |
| **openssl** | `generate_certificates`, `inspect_certificate`, `verify_certificate_chain` |
| **github** | `github_get_file`, `github_list_directory`, `github_search_code`, `github_get_issue`, `github_get_pr` |
| **helm** | `helm_generic_repo_add`, `helm_generic_search`, `helm_generic_upgrade_install`, `helm_generic_status`, `helm_generic_list`, `helm_generic_uninstall`, `kubectl_apply`, `kubectl_pods` |
| **linkerd** | `helm_search_bel_versions`, `helm_repo_add`, `install_gateway_api_crds`, `install_linkerd_control_plane`, `helm_install_linkerd_crds`, `helm_install_linkerd_control_plane`, `helm_upgrade_linkerd`, `helm_configure_linkerd`, `helm_uninstall_linkerd`, `helm_status`, `linkerd_check` |

### Service map

```
Browser
  │
  │  HTTP (port 8080 via k3d load balancer)
  ▼
Ingress (Traefik)
  ├── /              → todea-web             :80    React SPA + Express
  ├── /mcp           → todea-mcp             :3002  MCP tool server + /agents
  ├── /chat          → todea-agent-hub       :3100  Unified hub (Google · Azure · Ollama)
  ├── /models        → todea-agent-hub       :3100
  ├── /conversations → todea-agent-hub       :3100
  ├── /settings      → todea-agent-hub       :3100
  └── /healthz       → todea-agent-hub       :3100

Internal only (no dedicated ingress):
  todea-helm-agent        :3400  ← called by todea-mcp for all helm/kubectl operations
  todea-openssl-agent     :3500  ← called by todea-mcp for certificate operations
  todea-github-agent      :3600  ← called by todea-mcp for GitHub API queries
  todea-kubernetes-agent  :3700  ← called by todea-mcp for kubectl diagnostics
  todea-linkerd-agent     :3800  ← called by todea-mcp for BEL Helm operations
  todea-conversation-hub  :3300  ← called by the agent-hub for conversation storage
  todea-training-hub      :3500  ← reached via the web pod's proxy at /training-hub
```

### Call graph

All providers follow the same pattern — the difference is only which LLM API is called.

```
React UI  ──► Agent Hub  ──► LLM API (Google / Azure / Ollama)
                │                │
                │          Root agent sees 5 virtual tools
                │                │
                │          call_*_agent  ──► sub_agent.py (nested loop)
                │                                │
                │                   sub-agent calls MCP tools
                │                                │
                │          ┌─────────────────────┴──────────────────────┐
                │       MCP Server :3002 (raw tools via FastMCP)         │
                │          │                                             │
                │   ┌──────┼──────────────────────────────┐             │
                │  Helm  Kubernetes  OpenSSL  GitHub  Linkerd            │
                │  :3400   :3700     :3500    :3600   :3800              │
                │
                └──► Conversation Hub :3300  (history store)
```

### Coupling table

| Caller | Callee | Fails if callee is down? |
|---|---|---|
| Hub (any provider) | Conversation Hub | yes — chat and conversation list unavailable |
| Hub (any provider) | MCP Server | no — tool calling disabled, plain chat still works |
| Hub (Google path) | Google API | yes — chat unavailable |
| Hub (Azure path) | Azure OpenAI | yes — chat unavailable |
| Hub (Ollama path) | Ollama Runtime | yes — chat unavailable |
| MCP Server | Helm Agent | yes — all Helm/kubectl tools fail |
| MCP Server | OpenSSL Agent | no — cert tools fail, all other tools still work |
| MCP Server | GitHub Agent | no — GitHub tools fail, all other tools still work |
| MCP Server | Kubernetes Agent | no — kubectl diagnostic tools fail, all other tools still work |
| MCP Server | Linkerd Agent | yes — all Linkerd/BEL install tools fail |

---

## Documentation

### Operations

| Guide | Description |
|---|---|
| [Deployment (k3d)](docs/deployment.md) | k3d cluster setup, Helm install (Gemini, Azure & Ollama paths), updating, rebuilding single services |
| [Local Development](docs/local-development.md) | Running each service locally without k3d |
| [Agents & MCP Tools](docs/agents.md) | Multi-agent hierarchy, tool reference, and the Linkerd install sequence |
| [Ollama Reference](docs/ollama.md) | Model management, persistence, live streaming, external Ollama, tool-calling behaviour |

### Azure

| Guide | Description |
|---|---|
| [Infrastructure](docs/azure/infrastructure.md) | Resource group, ACR, AKS cluster, GPU spot node pool, NVIDIA device plugin |
| [Build & Deploy](docs/azure/deploy.md) | Building and pushing images to ACR, creating the namespace and PVC, Helm deploy (Gemini & Ollama paths) |
| [Training Pipeline](docs/azure/training.md) | Running scrape → train → serve via the UI, updating a deployment, continuous training CronJob, useful commands, cost estimate |

### ML & Training

| Guide | Description |
|---|---|
| [Training](docs/training.md) | Training UI, fine-tuning pipeline, and serving a custom Linkerd model |
| [Data Quality](docs/ml/data-quality.md) | Assessment of the current training dataset — sources, statistics, concerns, and recommendations |
| [Continuous Training](docs/ml/continuous-training.md) | Scheduled and event-triggered retraining loop, pipeline architecture, training strategy trade-offs |
| [RAG over Source Code](docs/ml/rag.md) | Why RAG beats training on code, vector store options, chunking strategy, and new MCP tool design |
| [Model Selection & Infrastructure](docs/ml/model-selection.md) | llama3.1:8b vs Qwen2.5-7B-Instruct, AKS vs home GPU, MLOps tool landscape and recommended stack |

---

## License

Refer to the individual directories for licensing terms.
