# Local Development

Instructions for running each service locally without k3d.

---

## React front-end (`web/client`)

```bash
cd web/client
yarn install
yarn start        # http://localhost:3000
```

---

## Helm Agent (`servers/mcp/helm-agent`)

Requires `helm` and `kubectl` installed and configured to reach a cluster.

```bash
cd servers/mcp/helm-agent
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 app.py
```

| Variable | Default | Description |
|---|---|---|
| `PORT` | `3400` | Port to listen on |
| `CLI_TIMEOUT` | `120` | Subprocess timeout in seconds |
| `ALLOW_ORIGINS` | `*` | Comma-separated CORS origins |

Key endpoints:

| Endpoint | Description |
|---|---|
| `POST /helm/repo/add` | Register a Helm repository |
| `GET  /helm/search?chart=&minor=` | Search chart versions; optional X.Y filter |
| `POST /helm/upgrade-install` | `helm upgrade --install` with `set_values` and `set_file_values` support |
| `POST /helm/uninstall` | Uninstall a release |
| `GET  /helm/status?release=&namespace=` | Release status; returns available releases on miss |
| `GET  /helm/list?namespace=` | List all releases in a namespace |
| `POST /kubectl/apply` | `kubectl apply -f <url>` |
| `GET  /kubectl/pods?namespace=` | `kubectl get pods -o wide` |
| `GET  /healthz` | Health check |

---

## MCP agent server (`servers/mcp`)

Requires the Helm Agent running (see above) and `kubectl` on `$PATH` configured to reach a cluster (for the `kubernetes_agent` diagnostic tools). The `linkerd` CLI is optional — `linkerd_check` falls back to `kubectl get pods` when it is absent. No other external binaries are required: certificate generation uses the Python `cryptography` library.

```bash
cd servers/mcp
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 server.py
```

| Variable | Default | Description |
|---|---|---|
| `GOOGLE_API_KEY` | _(optional)_ | Google GenAI API key — only required for the `chat` tool (Gemini routing); all other tools work without it |
| `MCP_PORT` | `3002` | Port to listen on |
| `AGENT_MODEL` | `gemini-2.0-flash` | Gemini model for ADK agents |
| `MCP_ALLOW_ORIGINS` | `http://localhost:3000` | Comma-separated CORS origins |
| `HELM_AGENT_URL` | `http://localhost:3400` | Helm Agent base URL |

To exercise the agent interactively:

```bash
adk web   # opens the Google ADK web harness
```

Try: "Install Linkerd 2.19", "What version of Linkerd is running?", "Why are the identity pods restarting?"

---

## Conversation Hub (`servers/conversation-hub`)

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

---

## Agent Hub (`servers/agent-hub`)

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

---

## Training Hub (`servers/training-hub`)

Requires `kubectl` configured to reach a cluster (in-cluster config is loaded automatically when running inside a pod).

```bash
cd servers/training-hub
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 app.py   # http://localhost:3500
```

Point the React UI at it:

- In-cluster / Helm: no extra config — the web pod proxies `/training-hub/*` to the training hub service (same-origin, no CORS needed).
- Local dev: `REACT_APP_TRAINING_HUB_URL=http://localhost:3500 yarn start`

| Variable | Default | Description |
|---|---|---|
| `PORT` | `3500` | Port to listen on |
| `ALLOW_ORIGINS` | `*` | Comma-separated CORS origins |
| `NAMESPACE` | `todea` | Kubernetes namespace for Jobs and Secrets |
| `GITHUB_SECRET_NAME` | `todea-github-token` | Name of the K8s Secret that stores the GitHub token |
| `TRAINING_PVC_NAME` | `todea-training-data` | PVC shared between the scraper and trainer Jobs |
| `SCRAPER_IMAGE` | `todea-scraper:local` | Container image for the scraper Job |
| `TRAINER_IMAGE` | `todea-trainer:local` | Container image for the trainer Job |
| `GPU_NODE_SELECTOR_KEY` | `agentpool` | Node label key used to target the GPU node pool |
| `GPU_NODE_SELECTOR_VALUE` | `gpupool` | Node label value for the GPU node pool |

Key endpoints:

| Endpoint | Description |
|---|---|
| `GET  /settings` | Returns models catalogue, repo/website list, and GitHub token status |
| `POST /settings/github-token` | Saves the GitHub token as K8s Secret `todea-github-token` |
| `POST /scrape` | Creates a scraper Kubernetes Job; returns `{ job_name }` |
| `POST /train` | Creates a trainer Kubernetes Job on the GPU node pool; returns `{ job_name }` |
| `GET  /jobs` | Lists all scraper and trainer Jobs with current phase |
| `GET  /logs/{job_name}` | SSE stream of pod logs for a Job (follows until pod exits) |
| `DELETE /jobs/{job_name}` | Cancels a running Job (foreground deletion) |
| `GET  /healthz` | Health check |

---

## Ollama Hub (`servers/ollama-hub`)

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

Key endpoints:

| Endpoint | Description |
|---|---|
| `POST /chat` | Blocking — returns full JSON response when complete |
| `POST /chat/stream` | SSE — streams `thinking`, `tool_call`, `tool_result`, `done` events |
| `GET  /models` | List available Ollama models |
| `GET/POST /conversations` | Conversation management |

| Variable | Default | Description |
|---|---|---|
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama server base URL |
| `MCP_SERVER_URL` | `http://localhost:3002/mcp` | MCP server endpoint |
| `CONVERSATION_HUB_URL` | `http://localhost:3300` | Conversation Hub endpoint |
| `AGENT_MODEL_OLLAMA` | `llama3.1:8b` | Default model |
| `MAX_TOOL_ITERATIONS` | `10` | Max tool-calling rounds before synthesis |
| `TOOL_REFRESH_SECONDS` | `300` | How often the MCP tool list is re-fetched |
| `DEFAULT_INSTRUCTION` | _(see app.py)_ | System prompt injected into every conversation |
| `ALLOW_ORIGINS` | `*` | Comma-separated CORS origins |
| `PORT` | `3200` | Port to listen on |
