# Todea-Assistant

Kubernetes-native AI demo platform with a React chat UI for installing, managing, and diagnosing a Linkerd service mesh through natural language. Supports Google Gemini (via ADK) or a fully in-cluster Ollama runtime — no cloud API key required for the Ollama path.

![Screenshot of the Todea-Assistant demo](assets/sample.png)

---

## Architecture

| Service | Path | Port | Role |
|---|---|---|---|
| **Web** | `web/` | 80 | React SPA + Express static server |
| **Agent Hub** | `servers/agent-hub/` | 3100 | LLM orchestrator (Google Gemini via ADK) + MCP client |
| **MCP Server** | `servers/mcp/` | 3002 | FastMCP tool server; hosts the `linkerd_agent` with `openssl_agent` and `kubernetes_agent` sub-agents |
| **Helm Agent** | `servers/mcp/helm-agent/` | 3400 | Generic HTTP wrapper around `helm` and `kubectl`; called by the MCP server |
| **Conversation Hub** | `servers/conversation-hub/` | 3300 | Shared conversation + message store for all providers |
| **Training Hub** | `servers/training-hub/` | 3500 | REST + SSE service that manages the ML training pipeline |
| **Ollama Hub** _(optional)_ | `servers/ollama-hub/` | 3200 | Drop-in chat gateway for Ollama models; streams live tool-call steps via SSE |
| **Ollama Runtime** _(optional)_ | `servers/ollama-runtime/` | 11434 | Custom Ollama image with the model pre-baked |

### Service map

```
Browser
  │
  │  HTTP (port 8080 via k3d load balancer)
  ▼
Ingress (Traefik)
  ├── /              → todea-web              :80    React SPA + Express
  ├── /mcp           → todea-mcp              :3002  MCP agent server
  └── /chat          → todea-agent-hub        :3100  Gemini path (default)
                       todea-ollama-hub       :3200  Ollama path (ollamaHub.enabled=true)

Internal only (no dedicated ingress):
  todea-helm-agent        :3400  ← called by todea-mcp for all helm/kubectl operations
  todea-conversation-hub  :3300  ← called by agent-hub and ollama-hub
  todea-training-hub      :3500  ← reached via the web pod's proxy at `/training-hub`
```

### Call graph

**Gemini path** (requires `GOOGLE_API_KEY`):
```
React UI  ──► Agent Hub (Gemini ADK)  ──► MCP Server
                    │                         │
                    │                    linkerd_agent (Gemini)
                    │                         ├── MCPToolset ──► Helm Agent ──► helm/kubectl ──► Kubernetes
                    │                         ├── openssl_agent  (cert generation + inspection)
                    │                         └── kubernetes_agent ──► kubectl ──► Kubernetes
                    │
                    └──► Conversation Hub  (store & retrieve conversation history)
```

**Ollama path** (no API key required):
```
React UI  ──► Ollama Hub (/chat/stream SSE)  ──► Ollama Runtime (in-cluster or external)
                   │          │                         │
                   │          └── streams: thinking ·   │ tool_call · tool_result · done
                   │                                    │
                   │◄── tool results ───────── MCP Server (Linkerd + OpenSSL + Kubernetes tools)
                   │                                    │
                   │                           Helm Agent (helm/kubectl)
                   │
                   └──► Conversation Hub  (store & retrieve conversation history)
```

### Coupling table

| Caller | Callee | Fails if callee is down? |
|---|---|---|
| Agent Hub | MCP Server | yes — chat unavailable |
| Agent Hub | Conversation Hub | yes — chat and conversation list unavailable |
| MCP Server | Helm Agent | yes — all Helm/kubectl tools fail |
| Ollama Hub | Ollama Runtime | yes — chat unavailable |
| Ollama Hub | MCP Server | no — tool calling disabled, plain chat still works |
| Ollama Hub | Conversation Hub | yes — chat and conversation list unavailable |

---

## Documentation

### Operations

| Guide | Description |
|---|---|
| [Deployment (k3d)](docs/deployment.md) | k3d cluster setup, Helm install (Gemini & Ollama paths), updating, rebuilding single services |
| [Local Development](docs/local-development.md) | Running each service locally without k3d |
| [Agents & MCP Tools](docs/agents.md) | MCP agent hierarchy, tool reference, and the Linkerd install sequence |
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
