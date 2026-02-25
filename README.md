# Todea-Assistant

Kubernetes-native AI demo platform with a React chat UI powered by Google Gemini to inspect and analyze a Linkerd service mesh through natural language via MCP agents.

![Screenshot of the Todea-Assistant demo](assets/sample.png)

---

## Architecture

Todea-Assistant is composed of the following services:

| Service | Path | Port | Role |
|---|---|---|---|
| **Web** | `web/` | 80 | React SPA + Express static server |
| **Agent Hub** | `servers/agent-hub/` | 3100 | LLM agent orchestrator (Google Gemini via ADK) |
| **MCP Server** | `servers/mcp/` | 3002 | FastMCP tool server with a Linkerd CLI agent |

### Service map

```
Browser
  │
  │  HTTP (port 8080 via k3d load balancer)
  ▼
Ingress (Traefik)
  ├── /              → todea-web          :80    React SPA + Express
  ├── /mcp           → todea-mcp          :3002  MCP agent server
  └── /chat          → todea-agent-hub    :3100  LLM agent orchestrator
```

### Call graph

```
React UI
  └── POST /chat  ──► Agent Hub (Gemini ADK)
                          │
                          ▼
                      MCP Server
                      └── linkerd_agent  ──► linkerd CLI (subprocess)
                                                  │
                                                  └── Kubernetes cluster (Linkerd)
```

### Coupling table

| Caller | Callee | Fails if callee is down? |
|---|---|---|
| Agent Hub | MCP Server | yes — chat unavailable |
| MCP Server | `linkerd` CLI | yes — all tools fail |
| `linkerd` CLI | Kubernetes cluster | yes — commands return errors |

---

## Quick start (k3d)

### 1. Create the cluster

```bash
k3d cluster create todea --agents 1 --port "8080:80@loadbalancer"
```

### 2. Install Linkerd

```bash
linkerd check --pre
linkerd install --crds | kubectl apply -f -
linkerd install | kubectl apply -f -
linkerd viz install | kubectl apply -f -
linkerd check
```

### 3. Build and import images

```bash
docker build -t todea-web:local           ./web
docker build -t todea-mcp:local           ./servers/mcp
docker build -t todea-agent-hub:local     ./servers/agent-hub
```

Import them into the k3d cluster:

```bash
k3d image import --cluster todea \
  todea-web:local \
  todea-mcp:local \
  todea-agent-hub:local
```

> **Note:** k3d's image store is isolated from the host Docker daemon. Run `k3d image import` every time you rebuild, then restart the affected deployment with `kubectl rollout restart deployment/<name> -n todea`.

### 4. Deploy with Helm

```bash
helm upgrade --install todea ./helm/todea \
  --namespace todea \
  --create-namespace \
  --set web.image.repository=todea-web \
  --set web.image.tag=local \
  --set mcp.image.repository=todea-mcp \
  --set mcp.image.tag=local \
  --set agentHub.image.repository=todea-agent-hub \
  --set agentHub.image.tag=local \
  --set agentHub.googleApiKey=<YOUR-GOOGLE-API-KEY> \
  --set mcp.googleApiKey=<YOUR-GOOGLE-API-KEY> \
  --set web.ingress.enabled=true \
  --set 'web.ingress.hosts[0].host=localhost' \
  --set 'web.ingress.hosts[0].paths[0].path=/' \
  --set 'web.ingress.hosts[0].paths[0].pathType=Prefix'
```

Open **http://localhost:8080** or port-forward directly:

```bash
kubectl -n todea port-forward svc/todea-web 8080:80
```

---

## Rebuilding a single service

```bash
# Example: rebuild the MCP server after a code change
docker build -t todea-mcp:local ./servers/mcp
k3d image import todea-mcp:local -c todea
kubectl rollout restart deployment/todea-mcp -n todea
```

---

## Local development (without k3d)

You need the Agent Hub and MCP server running locally. API URLs are read from environment variables — copy `.env.example` files in each service directory and fill in your keys.

### React front-end (`web/client`)

```bash
cd web/client
yarn install
yarn start
```

Visit http://localhost:3000.

### MCP agent server (`servers/mcp`)

Hosts the FastMCP server and the `linkerd_agent` Google ADK agent. Requires the `linkerd` CLI to be installed and configured to reach a cluster.

```bash
cd servers/mcp
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 server.py
```

Environment variables:

| Variable | Default | Description |
|---|---|---|
| `GOOGLE_API_KEY` | _(required)_ | Google GenAI API key |
| `MCP_PORT` | `3002` | Port to listen on |
| `AGENT_MODEL` | `gemini-2.0-flash` | Gemini model for ADK agents |
| `MCP_ALLOW_ORIGINS` | `http://localhost:3000` | Comma-separated CORS origins |

To exercise the agent with the Google ADK web harness:

```bash
cd servers/mcp
adk web
```

Try queries like:
- "Is Linkerd healthy?"
- "Show me traffic stats for all deployments"
- "What are the top requests hitting the web deployment?"
- "Are all service connections using mTLS?"
- "Show me the certificate identity for pod foo-abc in the default namespace"

### Agent Hub (`servers/agent-hub`)

Translates chat requests from the React UI to Google Gemini and routes tool calls through the MCP server.

```bash
cd servers/agent-hub
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # fill in GOOGLE_API_KEY
uvicorn app:app --port 3100
```

Environment variables:

| Variable | Default | Description |
|---|---|---|
| `GOOGLE_API_KEY` | _(required)_ | Google GenAI API key |
| `MCP_SERVER_URL` | `http://localhost:3002/mcp` | MCP server endpoint |
| `AGENT_MODEL_GOOGLE` | `gemini-2.0-flash` | Gemini model to use |
| `PORT` | `3100` | Port to listen on |

---

## Concepts

### Linkerd agent

The `linkerd_agent` is the root MCP agent. It runs `linkerd` CLI commands as subprocesses to inspect any aspect of a Kubernetes cluster running the Linkerd service mesh.

Available tools:

| Tool | CLI command | Description |
|---|---|---|
| `linkerd_check` | `linkerd check` | Verify Linkerd control-plane and data-plane health |
| `viz_stat` | `linkerd viz stat` | Aggregate traffic stats (RPS, success rate, latency) for a resource |
| `viz_top` | `linkerd viz top` | Point-in-time snapshot of top requests to a resource |
| `viz_routes` | `linkerd viz routes` | Per-route traffic metrics (requires a ServiceProfile) |
| `viz_edges` | `linkerd viz edges` | mTLS edge connectivity between services |
| `identity` | `linkerd identity` | TLS certificate identity for a pod's proxy |
| `diagnostics_proxy_metrics` | `linkerd diagnostics proxy-metrics` | Raw Prometheus metrics from a pod's sidecar proxy |

All tools accept an optional `namespace` argument. `viz_stat` and `viz_edges` also accept `all_namespaces=true` to query the entire cluster.

---

## License

Refer to the individual directories for licensing terms.
