# Todea-Assistant

Kubernetes-native AI demo platform with a React chat UI for installing, managing, and diagnosing a Linkerd service mesh through natural language. Supports Google Gemini (via ADK) or a fully in-cluster Ollama runtime — no cloud API key required for the Ollama path.

![Screenshot of the Todea-Assistant demo](assets/sample.png)

---

## Architecture

Todea-Assistant is composed of the following services:

| Service | Path | Port | Role |
|---|---|---|---|
| **Web** | `web/` | 80 | React SPA + Express static server |
| **Agent Hub** | `servers/agent-hub/` | 3100 | LLM orchestrator (Google Gemini via ADK) + MCP client |
| **MCP Server** | `servers/mcp/` | 3002 | FastMCP tool server; hosts the `linkerd_agent` with `openssl_agent` and `kubernetes_agent` sub-agents |
| **Helm Agent** | `servers/mcp/helm-agent/` | 3400 | Generic HTTP wrapper around `helm` and `kubectl`; called by the MCP server |
| **Conversation Hub** | `servers/conversation-hub/` | 3300 | Shared conversation + message store for all providers |
| **Ollama Hub** _(optional)_ | `servers/ollama-hub/` | 3200 | Drop-in chat gateway for Ollama models; streams live tool-call steps via SSE |
| **Ollama Runtime** _(optional)_ | `servers/ollama-runtime/` | 11434 | Custom Ollama image with the model pre-baked; no pull delay at startup |

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
  todea-helm-agent        :3400  ← called by todea-mcp for all helm/kubectl operations
  todea-conversation-hub  :3300  ← called by agent-hub and ollama-hub
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
docker build -t todea-helm-agent:local        ./servers/mcp/helm-agent
docker build -t todea-agent-hub:local         ./servers/agent-hub
docker build -t todea-conversation-hub:local  ./servers/conversation-hub

k3d image import --cluster todea \
  todea-web:local \
  todea-mcp:local \
  todea-helm-agent:local \
  todea-agent-hub:local \
  todea-conversation-hub:local
```

Deploy:

```bash
helm upgrade --install todea ./helm/todea \
  --namespace todea --create-namespace \
  --set web.image.repository=todea-web              --set web.image.tag=local \
  --set mcp.image.repository=todea-mcp              --set mcp.image.tag=local \
  --set helmAgent.image.repository=todea-helm-agent --set helmAgent.image.tag=local \
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

The Ollama runtime image is built locally with the model weights baked in so the pod starts immediately — no pull delay at startup.

```bash
docker build -t todea-web:local               ./web
docker build -t todea-mcp:local               ./servers/mcp
docker build -t todea-helm-agent:local        ./servers/mcp/helm-agent
docker build -t todea-ollama-hub:local        ./servers/ollama-hub
docker build -t todea-conversation-hub:local  ./servers/conversation-hub
docker build -t todea-ollama-runtime:local    ./servers/ollama-runtime

k3d image import --cluster todea \
  todea-web:local \
  todea-mcp:local \
  todea-helm-agent:local \
  todea-ollama-hub:local \
  todea-conversation-hub:local \
  todea-ollama-runtime:local
```

> **Note:** The `todea-ollama-runtime` build pulls `llama3.1:8b` (~5 GB) once and bakes it into the image layer. Subsequent builds use Docker's layer cache and are instant. The model is available on disk the moment the pod starts.

Deploy:

```bash
helm upgrade --install todea ./helm/todea \
  --namespace todea --create-namespace \
  --set web.image.repository=todea-web \
  --set web.image.tag=local \
  --set mcp.image.repository=todea-mcp \
  --set mcp.image.tag=local \
  --set helmAgent.image.repository=todea-helm-agent \
  --set helmAgent.image.tag=local \
  --set agentHub.enabled=false \
  --set ollamaHub.enabled=true \
  --set ollamaHub.image.repository=todea-ollama-hub \
  --set ollamaHub.image.tag=local \
  --set conversationHub.image.repository=todea-conversation-hub \
  --set conversationHub.image.tag=local \
  --set ollamaRuntime.enabled=true \
  --set web.ingress.enabled=true \
  --set 'web.ingress.hosts[0].host=localhost' \
  --set 'web.ingress.hosts[0].paths[0].path=/' \
  --set 'web.ingress.hosts[0].paths[0].pathType=Prefix'
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
  --set ollamaRuntime.enabled=true
```

```bash
# Example: switch model — rebuild the runtime image with a different model, re-import, then redeploy
docker build --build-arg MODEL=mistral -t todea-ollama-runtime:local ./servers/ollama-runtime
k3d image import todea-ollama-runtime:local -c todea
kubectl rollout restart deployment/todea-ollama -n todea
```

---

## Ollama in Kubernetes — reference

### Model management

The model is baked into the `todea-ollama-runtime` image at build time — no pull happens at pod startup. To change the model, rebuild the image with a different `MODEL` build arg:

```bash
docker build --build-arg MODEL=mistral -t todea-ollama-runtime:local ./servers/ollama-runtime
k3d image import todea-ollama-runtime:local -c todea
kubectl rollout restart deployment/todea-ollama -n todea
```

To pull additional models into a running pod:

```bash
kubectl exec -n todea deploy/todea-ollama -- ollama pull mistral
```

### Persistence

Persistence is not required for the primary model because it is already embedded in the image. Enable it only if you want models pulled at runtime to survive pod restarts:

```bash
--set ollamaRuntime.persistence.enabled=true \
--set ollamaRuntime.persistence.size=10Gi
```

k3d uses the `local-path` storage class by default, which works out of the box.

### Live streaming output

The Ollama Hub exposes `POST /chat/stream` as a Server-Sent Events endpoint. As the model reasons and calls tools, the UI receives and renders each step in real time before the final answer arrives:

| Event type | What it represents |
|---|---|
| `thinking` | Intermediate model text (reasoning / scratchpad) |
| `tool_call` | A tool the model has decided to invoke, and its arguments |
| `tool_result` | The raw output returned by that tool |
| `done` | Final answer — ends the stream |
| `error` | Unrecoverable failure |

The `/chat` endpoint (non-streaming, returns full JSON) is still available and unchanged.

### Pointing at an external Ollama

> **macOS users — run Ollama natively for best performance.**
> Docker containers on macOS cannot access the Metal GPU. When `ollamaRuntime` runs inside k3d, Ollama falls back to pure CPU inference and will peg your CPU at 100%. Running Ollama natively lets it use Metal for hardware-accelerated inference, which is dramatically faster and far less power-hungry.

Install and start Ollama on your Mac:

```bash
brew install ollama
ollama pull llama3.1:8b
```

Ollama must listen on all interfaces so that k3d containers can reach it via `host.k3d.internal`. By default Ollama binds to `127.0.0.1` (loopback only), which is not reachable from inside a container. Set `OLLAMA_HOST=0.0.0.0`:

```bash
OLLAMA_HOST=0.0.0.0:11434 ollama serve
```

For better memory efficiency, also enable flash-attention and a quantised KV cache:

```bash
OLLAMA_HOST=0.0.0.0:11434 OLLAMA_FLASH_ATTENTION=1 OLLAMA_KV_CACHE_TYPE=q8_0 ollama serve
```

Once running, verify in the logs:
- `Listening on [::]:11434` — bound to all interfaces (reachable from k3d)
- `inference compute ... library=Metal` — Metal GPU acceleration active

Then deploy without the in-cluster runtime, pointing the hub at your host via the k3d magic hostname `host.k3d.internal`:

```bash
--set ollamaRuntime.enabled=false \
--set ollamaHub.ollamaHost=http://host.k3d.internal:11434
```

---

## Rebuilding a single service

```bash
# MCP server
docker build -t todea-mcp:local ./servers/mcp
k3d image import todea-mcp:local -c todea
kubectl rollout restart deployment/todea-mcp -n todea

# Helm agent
docker build -t todea-helm-agent:local ./servers/mcp/helm-agent
k3d image import todea-helm-agent:local -c todea
kubectl rollout restart deployment/todea-helm-agent -n todea
```

---

## Local development (without k3d)

### React front-end (`web/client`)

```bash
cd web/client
yarn install
yarn start        # http://localhost:3000
```

### Helm Agent (`servers/mcp/helm-agent`)

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

### MCP agent server (`servers/mcp`)

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

---

## Concepts

### MCP agent hierarchy

The MCP server hosts a hierarchy of three ADK agents. The `linkerd_agent` is the root and delegates specialised tasks to two sub-agents via `AgentTool`:

```
linkerd_agent  (root — Helm/Linkerd orchestration)
  ├── openssl_agent      (X.509 certificate generation and inspection)
  └── kubernetes_agent   (kubectl-based cluster diagnostics)
```

When deployed in-cluster, the MCP pod runs with a dedicated ServiceAccount bound to a read-only ClusterRole (`todea-mcp-reader`), which grants the `kubernetes_agent` permission to read pods, logs, events, nodes, namespaces, deployments, and services across the cluster without write access.

### linkerd_agent

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

### openssl_agent

Generates, inspects, and verifies X.509 certificates. Runs entirely in-process using the Python `cryptography` library — no `openssl` or `step` binary required.

| Tool | Description |
|---|---|
| `generate_certificates` | Generate a trust-anchor + issuer cert pair; returns PEM strings ready for Helm |
| `inspect_certificate` | Parse a PEM certificate and return subject, issuer, validity window, days remaining, CA flag, path length, and SANs |
| `verify_certificate_chain` | Verify that an issuer cert was signed by a given CA cert; reports DN match and expiry status |

### kubernetes_agent

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

### Install sequence (fresh install)

The agent follows this exact order — stopping on any error:

```
1. helm_repo_add                    (no args — defaults are always correct)
2. install_gateway_api_crds         (version)
3. generate_certificates            (via openssl_agent — no args)
4. helm_install_linkerd_crds        (version)
5. helm_install_linkerd_control_plane (version, license_key, + 3 PEM strings from step 3)
6. linkerd_check                    (verify — falls back to kubernetes_agent.get_pods if CLI absent)
```

### Ollama Hub — tool-calling behaviour

The Ollama Hub fetches the MCP tool list at startup and makes it available to the Ollama model. To work reliably with smaller local models (llama3.1:8b), it applies several layers of robustness:

**3-tier tool-call extraction** — handles models that don't reliably use the structured `tool_calls` API:
1. Structured `tool_calls` field in the Ollama response (ideal path)
2. Inline JSON scanner — finds `{"name": "...", "parameters": {...}}` embedded in the content text
3. Constrained re-prompt — re-asks the model with `format=json` to extract the tool call when a known tool name appears in content but no JSON was found

**Argument sanitisation** — before every MCP tool call, any argument key not present in the tool's JSON Schema is stripped. This prevents Pydantic validation errors when the model guesses wrong parameter names (e.g. `repo-url` instead of `repo_url`). Tools with all-optional parameters (like `helm_repo_add`) succeed with their defaults.

**Tool name fuzzy matching** — hallucinated tool names are matched against known tools by substring and token-overlap scoring before the call is rejected.

**Excluded tools** — the `chat` MCP tool (which requires a Google API key for Gemini routing) is hidden from Ollama's tool list so the model never attempts to call it.

### Helm Agent

The Helm Agent (`servers/mcp/helm-agent/`) is a generic, domain-agnostic HTTP service that wraps `helm` and `kubectl` as subprocesses. It has no knowledge of Linkerd or Buoyant — chart names, release names, values, and certificate field names are all supplied by the caller. The `set_file_values` field in `POST /helm/upgrade-install` accepts file content as strings; the agent writes them to a temporary directory, passes `--set-file` flags to helm, and cleans up automatically.

---

## Fine-tuning a custom Linkerd model

The `scripts/training/` directory contains a self-contained pipeline for fine-tuning a Llama or Qwen model on Linkerd documentation, producing a LoRA adapter that can be merged and served via Ollama.

### 1. Install dependencies

```bash
cd scripts/training
python3 -m venv .venv && source .venv/bin/activate
pip install torch transformers peft trl accelerate datasets requests \
            beautifulsoup4 html2text
# CUDA only — enables 4-bit quantisation and adamw_8bit:
pip install bitsandbytes
# Optional — needed only if DeepWiki pages require JS rendering:
pip install playwright && playwright install chromium
```

### 2. Collect training data

Two scrapers write JSONL files into `scripts/training/data/`:

#### GitHub markdown docs (`fetch_docs.py`)

Downloads `.md` files from `linkerd/linkerd2` and `linkerd/linkerd2-proxy` using the GitHub API. Set `GITHUB_TOKEN` to avoid the 60 req/hr unauthenticated rate limit.

```bash
export GITHUB_TOKEN=ghp_...
python fetch_docs.py                              # → data/raw_docs.jsonl
python fetch_docs.py --repos linkerd/linkerd2     # single repo
python fetch_docs.py --output data/my_docs.jsonl  # custom output path
```

#### DeepWiki AI-generated docs (`fetch_deepwiki.py`)

Scrapes structured architecture and component documentation from DeepWiki for both Linkerd repos (36 pages).

```bash
python fetch_deepwiki.py                   # → data/raw_deepwiki.jsonl
python fetch_deepwiki.py --playwright      # headless Chromium if pages render blank
```

Both scrapers are **incremental** — they skip records already present in the output file, so re-running after a partial download is safe.

### 3. Fine-tune

`finetune.py` trains a LoRA adapter on ShareGPT-format JSONL data. It auto-detects the device and adjusts precision accordingly:

| Device | Precision | Quantisation |
|---|---|---|
| CUDA (with bitsandbytes) | bfloat16 | 4-bit NF4 |
| CUDA (no bitsandbytes) | bfloat16 | none |
| MPS (Apple Silicon) | float16 | none — requires ~16 GB unified memory |
| CPU | float32 | none — very slow |

```bash
# Default model (Llama 3.1 8B — requires HuggingFace login + license acceptance)
huggingface-cli login
python finetune.py

# Qwen 2.5 7B (no license gate)
python finetune.py --model Qwen/Qwen2.5-7B-Instruct

# Smaller, faster on Mac
python finetune.py --model meta-llama/Meta-Llama-3.2-3B-Instruct

# Full options
python finetune.py \
  --model  Qwen/Qwen2.5-7B-Instruct \
  --data   data/training_data.jsonl \
  --output output \
  --epochs 3 \
  --batch-size 1 \
  --lora-rank 16
```

The adapter is saved to `output/lora-adapter/` when training completes.

### 4. Merge and convert to GGUF

Use [llama.cpp](https://github.com/ggerganov/llama.cpp) to merge the LoRA weights into the base model and quantise to GGUF for Ollama:

```bash
python llama.cpp/convert_hf_to_gguf.py output/lora-adapter --outtype q4_k_m
```

### 5. Serve with Ollama

```bash
# Create a Modelfile pointing at the .gguf
cat > Modelfile <<'EOF'
FROM ./output/lora-adapter/model-q4_k_m.gguf
EOF

ollama create linkerd-custom -f Modelfile
ollama run linkerd-custom
```

To use the custom model in the Todea stack, set it as the default:

```bash
--set ollamaHub.env.AGENT_MODEL_OLLAMA=linkerd-custom
```

---

## License

Refer to the individual directories for licensing terms.
