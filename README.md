# Todea-Assistant

Kubernetes-native AI demo platform with a React chat UI for inspecting a Linkerd service mesh through natural language. Supports Google Gemini (via ADK) or a fully in-cluster Ollama runtime — no cloud API key required for the Ollama path.

![Screenshot of the Todea-Assistant demo](assets/sample.png)

---

## Architecture

Todea-Assistant is composed of the following services:

| Service | Path | Port | Role |
|---|---|---|---|
| **Web** | `web/` | 80 | React SPA + Express static server |
| **Agent Hub** | `servers/agent-hub/` | 3100 | LLM orchestrator (Google Gemini via ADK) + MCP client |
| **MCP Server** | `servers/mcp/` | 3002 | FastMCP tool server with a Linkerd CLI agent |
| **Conversation Hub** | `servers/conversation-hub/` | 3300 | Shared conversation + message store for all providers |
| **Ollama Hub** _(optional)_ | `servers/ollama-hub/` | 3200 | Drop-in chat gateway for Ollama models (no Google key) |
| **Ollama Runtime** _(optional)_ | — | 11434 | In-cluster `ollama/ollama` pod pulled from Docker Hub |

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

Internal only (no ingress):
  todea-conversation-hub  :3300  ← called by agent-hub and ollama-hub
```

### Call graph

**Gemini path** (requires `GOOGLE_API_KEY`):
```
React UI  ──► Agent Hub (Gemini ADK)  ──► MCP Server  ──► linkerd CLI  ──► Kubernetes
                    │
                    └──► Conversation Hub  (store & retrieve conversation history)
```

**Ollama path** (no API key required):
```
React UI  ──► Ollama Hub  ──► Ollama Runtime (in-cluster or external)
                   │
                   └──► Conversation Hub  (store & retrieve conversation history)
```

### Coupling table

| Caller | Callee | Fails if callee is down? |
|---|---|---|
| Agent Hub | MCP Server | yes — chat unavailable |
| Agent Hub | Conversation Hub | yes — chat and conversation list unavailable |
| MCP Server | `linkerd` CLI | yes — all tools fail |
| Ollama Hub | Ollama Runtime | yes — chat unavailable |
| Ollama Hub | Conversation Hub | yes — chat and conversation list unavailable |

---

## Quick start (k3d)

### 1. Create the cluster

```bash
k3d cluster create todea --agents 1 --port "8080:80@loadbalancer"
```

### 2. Choose a path

#### Path A — Google Gemini

Build and import images:

```bash
docker build -t todea-web:local               ./web
docker build -t todea-mcp:local               ./servers/mcp
docker build -t todea-agent-hub:local         ./servers/agent-hub
docker build -t todea-conversation-hub:local  ./servers/conversation-hub

k3d image import --cluster todea \
  todea-web:local \
  todea-mcp:local \
  todea-agent-hub:local \
  todea-conversation-hub:local
```

Deploy:

```bash
helm upgrade --install todea ./helm/todea \
  --namespace todea --create-namespace \
  --set web.image.repository=todea-web              --set web.image.tag=local \
  --set mcp.image.repository=todea-mcp              --set mcp.image.tag=local \
  --set agentHub.image.repository=todea-agent-hub   --set agentHub.image.tag=local \
  --set conversationHub.image.repository=todea-conversation-hub --set conversationHub.image.tag=local \
  --set agentHub.googleApiKey=<YOUR-GOOGLE-API-KEY> \
  --set mcp.googleApiKey=<YOUR-GOOGLE-API-KEY> \
  --set web.ingress.enabled=true \
  --set 'web.ingress.hosts[0].host=localhost' \
  --set 'web.ingress.hosts[0].paths[0].path=/' \
  --set 'web.ingress.hosts[0].paths[0].pathType=Prefix'
```

#### Path B — Ollama (no API key)

Build and import the Ollama Hub and Conversation Hub images. The `ollama/ollama` runtime is pulled directly from Docker Hub by the cluster — no local build needed.

```bash
docker build -t todea-web:local               ./web
docker build -t todea-mcp:local               ./servers/mcp
docker build -t todea-ollama-hub:local        ./servers/ollama-hub
docker build -t todea-conversation-hub:local  ./servers/conversation-hub

k3d image import --cluster todea \
  todea-web:local \
  todea-mcp:local \
  todea-ollama-hub:local \
  todea-conversation-hub:local
```

> **Tip — speed up the first deploy:** By default k3d pulls `ollama/ollama` from Docker Hub at deploy time, which can be slow. Pre-pull it into the cluster's image store first:
> ```bash
> docker pull ollama/ollama:latest
> k3d image import ollama/ollama:latest -c todea
> ```

Deploy:

```bash
helm upgrade --install todea --namespace todea --create-namespace \
  --set web.image.repository=todea-web \
  --set web.image.tag=local \
  --set mcp.image.repository=todea-mcp \
  --set mcp.image.tag=local \
  --set agentHub.enabled=false \
  --set ollamaHub.enabled=true \
  --set ollamaHub.image.repository=todea-ollama-hub \
  --set ollamaHub.image.tag=local \
  --set conversationHub.image.repository=todea-conversation-hub \
  --set conversationHub.image.tag=local \
  --set ollamaRuntime.enabled=true \
  --set ollamaRuntime.model=llama3.1:8b \
  --set ollamaRuntime.persistence.enabled=true \
  --set ollamaRuntime.persistence.size=10Gi \
  --set web.ingress.enabled=true \
  --set 'web.ingress.hosts[0].host=localhost' \
  --set 'web.ingress.hosts[0].paths[0].path=/' \
  --set 'web.ingress.hosts[0].paths[0].pathType=Prefix' \
  ./helm/todea
```

### 3. Open the UI

```bash
open http://localhost:8080
```

Or port-forward if not using an ingress:

```bash
kubectl -n todea port-forward svc/todea-web 8080:80
```

> **Note:** k3d's image store is isolated from the host Docker daemon. Run `k3d image import` every time you rebuild a local image, then restart the affected deployment:
> ```bash
> kubectl rollout restart deployment/<name> -n todea
> ```

---

## Updating an existing deployment

Use `--reuse-values` to carry forward all current settings and only override what you specify:

```bash
# Example: enable in-cluster Ollama on a running deployment
helm upgrade todea ./helm/todea \
  --namespace todea \
  --reuse-values \
  --set ollamaRuntime.enabled=true \
  --set ollamaRuntime.model=llama3.1:8b \
  --set ollamaRuntime.persistence.enabled=true \
  --set ollamaRuntime.persistence.size=10Gi
```

```bash
# Example: switch model
helm upgrade todea ./helm/todea \
  --namespace todea \
  --reuse-values \
  --set ollamaHub.agentModel=mistral \
  --set ollamaRuntime.model=mistral
```

---

## Ollama in Kubernetes — reference

### Model management

The chart pulls `ollamaRuntime.model` automatically on pod startup. To pull additional models or trigger a pull manually:

```bash
kubectl exec -n todea deploy/todea-ollama -- ollama pull mistral
```

### Persistence

Without `ollamaRuntime.persistence.enabled=true` models are stored in an `emptyDir` and re-downloaded on every pod restart. Enable persistence to keep the model cache:

```bash
--set ollamaRuntime.persistence.enabled=true \
--set ollamaRuntime.persistence.size=10Gi
```

k3d uses the `local-path` storage class by default, which works out of the box.

### Pointing at an external Ollama

If you prefer to run Ollama on the host rather than in-cluster, skip `ollamaRuntime` and point the hub at the host:

```bash
--set ollamaRuntime.enabled=false \
--set ollamaHub.ollamaHost=http://host.docker.internal:11434
```

---

## Rebuilding a single service

```bash
docker build -t todea-mcp:local ./servers/mcp
k3d image import todea-mcp:local -c todea
kubectl rollout restart deployment/todea-mcp -n todea
```

---

## Local development (without k3d)

### React front-end (`web/client`)

```bash
cd web/client
yarn install
yarn start        # http://localhost:3000
```

### MCP agent server (`servers/mcp`)

Requires the `linkerd` CLI installed and configured to reach a cluster.

```bash
cd servers/mcp
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 server.py
```

| Variable | Default | Description |
|---|---|---|
| `GOOGLE_API_KEY` | _(required)_ | Google GenAI API key |
| `MCP_PORT` | `3002` | Port to listen on |
| `AGENT_MODEL` | `gemini-2.0-flash` | Gemini model for ADK agents |
| `MCP_ALLOW_ORIGINS` | `http://localhost:3000` | Comma-separated CORS origins |

To exercise the agent interactively:

```bash
adk web   # opens the Google ADK web harness
```

Try: "Is Linkerd healthy?", "Show me traffic stats for all deployments", "Are all connections using mTLS?"

### Conversation Hub (`servers/conversation-hub`)

Start this before running Agent Hub or Ollama Hub locally.

```bash
cd servers/conversation-hub
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --port 3300
```

| Variable | Default | Description |
|---|---|---|
| `ALLOW_ORIGINS` | `*` | Comma-separated CORS origins |
| `PORT` | `3300` | Port to listen on |

### Agent Hub (`servers/agent-hub`)

```bash
cd servers/agent-hub
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in GOOGLE_API_KEY
uvicorn app:app --port 3100
```

| Variable | Default | Description |
|---|---|---|
| `GOOGLE_API_KEY` | _(required)_ | Google GenAI API key |
| `MCP_SERVER_URL` | `http://localhost:3002/mcp` | MCP server endpoint |
| `CONVERSATION_HUB_URL` | `http://localhost:3300` | Conversation Hub endpoint |
| `AGENT_MODEL_GOOGLE` | `gemini-2.0-flash` | Gemini model to use |
| `PORT` | `3100` | Port to listen on |

### Ollama Hub (`servers/ollama-hub`)

Requires an Ollama server with at least one model pulled.

```bash
# Start ollama locally
ollama serve &
ollama pull llama3.1:8b

cd servers/ollama-hub
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # adjust OLLAMA_HOST if needed
uvicorn app:app --port 3200
```

Point the React UI at it: `REACT_APP_AGENT_HUB_URL=http://localhost:3200/chat yarn start`

| Variable | Default | Description |
|---|---|---|
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama server base URL |
| `CONVERSATION_HUB_URL` | `http://localhost:3300` | Conversation Hub endpoint |
| `AGENT_MODEL_OLLAMA` | `llama3.1:8b` | Default model |
| `ALLOW_ORIGINS` | `*` | Comma-separated CORS origins |
| `PORT` | `3200` | Port to listen on |

---

## Concepts

### Linkerd agent

The `linkerd_agent` runs `linkerd` CLI commands as subprocesses to inspect any aspect of a cluster running Linkerd.

| Tool | CLI command | Description |
|---|---|---|
| `linkerd_check` | `linkerd check` | Verify Linkerd control-plane and data-plane health |
| `viz_stat` | `linkerd viz stat` | Aggregate traffic stats (RPS, success rate, latency) |
| `viz_top` | `linkerd viz top` | Point-in-time snapshot of top requests |
| `viz_routes` | `linkerd viz routes` | Per-route traffic metrics (requires a ServiceProfile) |
| `viz_edges` | `linkerd viz edges` | mTLS edge connectivity between services |
| `identity` | `linkerd identity` | TLS certificate identity for a pod's proxy |
| `diagnostics_proxy_metrics` | `linkerd diagnostics proxy-metrics` | Raw Prometheus metrics from a sidecar proxy |

All tools accept an optional `namespace` argument. `viz_stat` and `viz_edges` also accept `all_namespaces=true`.

---

## License

Refer to the individual directories for licensing terms.
