# Local Development

Instructions for running each service locally without k3d.

---

## React front-end (`web/client`)

```bash
cd web/client
yarn install
REACT_APP_HUB_URL=http://localhost:3100 yarn start   # http://localhost:3000
```

`REACT_APP_HUB_URL` must be set when running the React dev server directly (bypassing the Express proxy). When the app is served through the Express server (`web/server/index.js`) — either locally or in-cluster — leave it unset so requests use relative paths and the Express proxy forwards them to the agent-hub.

---

## Helm Agent (`servers/mcp/helm_agent`)

Requires `helm` and `kubectl` installed and configured to reach a cluster.

```bash
cd servers/mcp/helm_agent
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

## OpenSSL Agent (`servers/mcp/openssl_agent`)

No external binaries required — uses the Python `cryptography` library.

```bash
cd servers/mcp/openssl_agent
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 app.py
```

| Variable | Default | Description |
|---|---|---|
| `PORT` | `3500` | Port to listen on |
| `ALLOW_ORIGINS` | `*` | Comma-separated CORS origins |

Key endpoints:

| Endpoint | Description |
|---|---|
| `POST /certificates/generate` | Generate a trust anchor + issuer cert pair |
| `POST /certificates/inspect` | Parse and display a PEM certificate |
| `POST /certificates/verify` | Verify an issuer cert was signed by a given CA |
| `GET  /healthz` | Health check |

---

## GitHub Agent (`servers/mcp/github_agent`)

```bash
cd servers/mcp/github_agent
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
GITHUB_TOKEN=<your-token> python3 app.py
```

| Variable | Default | Description |
|---|---|---|
| `PORT` | `3600` | Port to listen on |
| `GITHUB_TOKEN` | _(optional)_ | Personal access token — raises rate limit from 60 to 5 000 req/h |
| `ALLOW_ORIGINS` | `*` | Comma-separated CORS origins |

Key endpoints:

| Endpoint | Description |
|---|---|
| `GET /github/file?repo=&path=&ref=` | Fetch raw file content |
| `GET /github/directory?repo=&path=&ref=` | List directory contents |
| `GET /github/search?repo=&query=` | Search code within a repository |
| `GET /github/issue?repo=&number=` | Fetch an issue with its comments |
| `GET /github/pr?repo=&number=` | Fetch a pull request with changed files |
| `GET /healthz` | Health check |

---

## Kubernetes Agent (`servers/mcp/kubernetes_agent`)

Requires `kubectl` installed and configured to reach a cluster.

```bash
cd servers/mcp/kubernetes_agent
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 app.py
```

| Variable | Default | Description |
|---|---|---|
| `PORT` | `3700` | Port to listen on |
| `ALLOW_ORIGINS` | `*` | Comma-separated CORS origins |

Key endpoints:

| Endpoint | Description |
|---|---|
| `GET /kubernetes/namespaces` | List all namespaces |
| `GET /kubernetes/nodes` | List nodes with status and version |
| `GET /kubernetes/pods?namespace=` | List pods; cluster-wide when omitted |
| `GET /kubernetes/pods/{pod}/logs?namespace=&container=&previous=&tail_lines=` | Fetch logs |
| `GET /kubernetes/pods/{pod}/diagnose?namespace=` | Composite crash diagnostic |
| `GET /healthz` | Health check |

---

## Linkerd Agent (`servers/mcp/linkerd_agent`)

Requires the Helm Agent running. The `linkerd` CLI is optional — `linkerd_check` falls back gracefully when absent.

> **Note:** The Linkerd Agent imports `openssl_agent.tools`. When running locally outside Docker, set `PYTHONPATH` so the `openssl_agent` package is importable:

```bash
cd servers/mcp
python3 -m venv .venv && source .venv/bin/activate
pip install -r linkerd_agent/requirements.txt -r openssl_agent/requirements.txt
PYTHONPATH=. PORT=3800 python3 linkerd_agent/app.py
```

| Variable | Default | Description |
|---|---|---|
| `PORT` | `3800` | Port to listen on |
| `HELM_AGENT_URL` | `http://localhost:3400` | Helm Agent base URL |
| `ALLOW_ORIGINS` | `*` | Comma-separated CORS origins |

Key endpoints:

| Endpoint | Description |
|---|---|
| `GET  /linkerd/versions?minor=` | List available BEL chart versions |
| `POST /linkerd/repo/add` | Register the Buoyant Helm repository |
| `POST /linkerd/control-plane/install` | Generate certs + install control plane (composite) |
| `POST /linkerd/upgrade` | Upgrade CRDs and control plane |
| `GET  /linkerd/status?release=&namespace=` | Helm release status |
| `GET  /linkerd/check?proxy=&namespace=` | Run `linkerd check` |
| `POST /certificates/generate` | Generate trust anchor + issuer cert pair |
| `GET  /healthz` | Health check |

---

## MCP agent server (`servers/mcp`)

Start the **Helm Agent**, **Kubernetes Agent**, and **Linkerd Agent** first. `kubectl` must be on `$PATH` and configured to reach a cluster.

```bash
cd servers/mcp
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 app.py
```

| Variable | Default | Description |
|---|---|---|
| `MCP_PORT` | `3002` | Port to listen on |
| `MCP_ALLOW_ORIGINS` | `http://localhost:3000` | Comma-separated CORS origins |
| `HELM_AGENT_URL` | `http://localhost:3400` | Helm Agent base URL (used by `linkerd_agent.tools`) |

The MCP server exposes two endpoints:
- `GET /mcp` — FastMCP protocol endpoint (all raw tools)
- `GET /agents` — JSON list of sub-agent configs (name, instructions, tool list); consumed by the Agent Hub at runtime

No LLM API key is required to run the MCP server. All orchestration logic lives in the Agent Hub.

---

## Conversation Hub (`servers/conversation-hub`)

Start this before running the Hub locally.

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

Unified LLM gateway — routes requests to Google (Gemini), Azure OpenAI, or Ollama based on the `provider` field sent by the UI. Runs the root dispatcher agent and all sub-agent loops. Only the providers whose credentials are set will be available in the model dropdown.

```bash
cd servers/agent-hub
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --port 3100
```

Set credentials for the providers you want to use:

```bash
# Google
export GOOGLE_API_KEY=AIza...

# Azure OpenAI
export AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com/
export AZURE_OPENAI_API_KEY=...
export AZURE_OPENAI_DEPLOYMENT=gpt-4o
export AZURE_OPENAI_API_VERSION=2024-12-01-preview

# Ollama (defaults to localhost:11434 if not set)
export OLLAMA_HOST=http://localhost:11434
```

| Variable | Default | Description |
|---|---|---|
| `MCP_SERVER_URL` | `http://localhost:3002/mcp` | MCP server endpoint |
| `CONVERSATION_HUB_URL` | `http://localhost:3300` | Conversation Hub endpoint |
| `GOOGLE_API_KEY` | _(optional)_ | Google GenAI API key — enables Google provider |
| `AGENT_MODEL_GOOGLE` | `gemini-2.5-flash` | Default Gemini model |
| `AZURE_OPENAI_ENDPOINT` | _(optional)_ | Azure OpenAI resource URL — enables Azure provider |
| `AZURE_OPENAI_API_KEY` | _(optional)_ | Azure OpenAI API key |
| `AZURE_OPENAI_DEPLOYMENT` | `gpt-4o` | Deployment name as shown in Azure AI Foundry |
| `AZURE_OPENAI_API_VERSION` | `2024-12-01-preview` | Azure OpenAI API version |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama server base URL — enables Ollama provider |
| `AGENT_MODEL_OLLAMA` | `llama3.1:8b` | Default Ollama model |
| `MAX_TOOL_ITERATIONS` | `10` | Max tool-calling rounds before synthesis |
| `TOOL_REFRESH_SECONDS` | `300` | How often the MCP tool list is re-fetched |
| `ALLOW_ORIGINS` | `*` | Comma-separated CORS origins |
| `PORT` | `3100` | Port to listen on |

Key endpoints:

| Endpoint | Description |
|---|---|
| `GET  /models` | Returns `{models: [{id, provider}], default, default_provider}` |
| `POST /chat/stream` | SSE — streams `thinking`, `tool_call`, `tool_result`, `done` events; dispatches by `provider` field |
| `POST /settings` | Writes/patches provider credentials into the `todea-api-keys` K8s secret |
| `GET  /settings/status` | Returns `{exists, providers: {google, azure, ollama}}` |
| `GET  /settings/cluster` | Returns the active cluster API server URL |
| `POST /settings/cluster` | Sets the cluster API server URL |
| `GET  /healthz` | Health check |

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

