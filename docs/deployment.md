# Deployment

## Quick start (k3d)

### 1. Create the cluster

```bash
k3d cluster create todea --agents 1 --port "8080:80@loadbalancer"
```

### 2. Build and import images

```bash
docker build -t todea-web:local               ./web
docker build -t todea-mcp:local               ./servers/mcp
docker build -t todea-agent-hub:local         ./servers/agent-hub
docker build -t todea-helm-agent:local        ./servers/mcp/helm_agent
docker build -t todea-openssl-agent:local     ./servers/mcp/openssl_agent
docker build -t todea-github-agent:local      ./servers/mcp/github_agent
docker build -t todea-kubernetes-agent:local  ./servers/mcp/kubernetes_agent
# Linkerd Agent must be built from servers/mcp/ (needs openssl_agent package):
docker build -t todea-linkerd-agent:local  -f ./servers/mcp/linkerd_agent/Dockerfile  ./servers/mcp
docker build -t todea-conversation-hub:local  ./servers/conversation-hub
docker build -t todea-training-hub:local      ./servers/training-hub
docker build -t todea-scraper:local  -f ./servers/training-hub/Dockerfile.scraper  ./servers/training-hub
docker build -t todea-trainer:local  -f ./servers/training-hub/Dockerfile.trainer  ./servers/training-hub

k3d image import --cluster todea \
  todea-web:local \
  todea-mcp:local \
  todea-agent-hub:local \
  todea-helm-agent:local \
  todea-openssl-agent:local \
  todea-github-agent:local \
  todea-kubernetes-agent:local \
  todea-linkerd-agent:local \
  todea-conversation-hub:local \
  todea-training-hub:local \
  todea-scraper:local \
  todea-trainer:local
```

To use Ollama in-cluster, also build and import the runtime image (pulls `llama3.1:8b` ~5 GB on first build, cached after that):

```bash
docker build -t todea-ollama-runtime:local ./servers/ollama-runtime
k3d image import todea-ollama-runtime:local --cluster todea
```

### 3. Deploy

```bash
helm upgrade --install todea ./helm/todea \
  --namespace todea --create-namespace \
  --set web.image.repository=todea-web                          --set web.image.tag=local \
  --set mcp.image.repository=todea-mcp                          --set mcp.image.tag=local \
  --set agentHub.image.repository=todea-agent-hub               --set agentHub.image.tag=local \
  --set helmAgent.image.repository=todea-helm-agent             --set helmAgent.image.tag=local \
  --set conversationHub.image.repository=todea-conversation-hub --set conversationHub.image.tag=local \
  --set trainingHub.image.repository=todea-training-hub         --set trainingHub.image.tag=local \
  --set web.ingress.enabled=true \
  --set 'web.ingress.hosts[0].host=localhost' \
  --set 'web.ingress.hosts[0].paths[0].path=/' \
  --set 'web.ingress.hosts[0].paths[0].pathType=Prefix'
```

Add `--set ollamaRuntime.enabled=true` if you imported the Ollama runtime image.

### 4. Configure provider credentials

No API keys are passed through Helm. Credentials are stored in the `todea-api-keys` Kubernetes secret and managed through the **Settings** page in the UI.

Open the UI:

```bash
open http://localhost:8080
```

Navigate to **Settings** and fill in the credentials for each provider you want to use:

| Provider | Fields |
|---|---|
| Google | API key (`GOOGLE_API_KEY`) |
| Azure OpenAI | Endpoint, API key, deployment name, API version |
| Ollama | Host URL (defaults to `http://localhost:11434` if left blank) |

Saving any provider's form patches the `todea-api-keys` secret without overwriting keys for other providers. The agent-hub pod reads credentials from this secret at startup via `envFrom`.

> **Note:** After saving credentials for the first time, the agent-hub pod must be restarted to pick up the new secret:
> ```bash
> kubectl rollout restart deployment/todea-agent-hub -n todea
> ```
> Subsequent updates patch the existing secret — the agent-hub reads credentials on startup so a restart is only needed when the pod has not yet seen the secret.

> **Note:** k3d's image store is isolated from the host Docker daemon. Run `k3d image import` every time you rebuild a local image, then restart the affected deployment:
> ```bash
> kubectl rollout restart deployment/<name> -n todea
> ```

Or port-forward if not using an ingress:

```bash
kubectl -n todea port-forward svc/todea-web 8080:80
```

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
# Example: switch Ollama model — rebuild the runtime image with a different model, re-import, then redeploy
docker build --build-arg MODEL=mistral -t todea-ollama-runtime:local ./servers/ollama-runtime
k3d image import todea-ollama-runtime:local -c todea
kubectl rollout restart deployment/todea-ollama -n todea
```

---

## Rebuilding a single service

```bash
# Agent Hub (unified LLM gateway)
docker build -t todea-agent-hub:local ./servers/agent-hub
k3d image import todea-agent-hub:local -c todea
kubectl rollout restart deployment/todea-agent-hub -n todea

# MCP server
docker build -t todea-mcp:local ./servers/mcp
k3d image import todea-mcp:local -c todea
kubectl rollout restart deployment/todea-mcp -n todea

# Helm agent
docker build -t todea-helm-agent:local ./servers/mcp/helm_agent
k3d image import todea-helm-agent:local -c todea
kubectl rollout restart deployment/todea-helm-agent -n todea

# Kubernetes agent
docker build -t todea-kubernetes-agent:local ./servers/mcp/kubernetes_agent
k3d image import todea-kubernetes-agent:local -c todea
kubectl rollout restart deployment/todea-kubernetes-agent -n todea

# Linkerd agent (must be built from servers/mcp/ for the openssl_agent package)
docker build -t todea-linkerd-agent:local -f ./servers/mcp/linkerd_agent/Dockerfile ./servers/mcp
k3d image import todea-linkerd-agent:local -c todea
kubectl rollout restart deployment/todea-linkerd-agent -n todea

# Training Hub
docker build -t todea-training-hub:local ./servers/training-hub
k3d image import todea-training-hub:local -c todea
kubectl rollout restart deployment/todea-training-hub -n todea

# Scraper job image (used by Training Hub to create Kubernetes scrape jobs)
docker build -t todea-scraper:local -f ./servers/training-hub/Dockerfile.scraper ./servers/training-hub
k3d image import todea-scraper:local -c todea

# Trainer job image (used by Training Hub to create Kubernetes fine-tune jobs)
docker build -t todea-trainer:local -f ./servers/training-hub/Dockerfile.trainer ./servers/training-hub
k3d image import todea-trainer:local -c todea
```

> **Note:** The scraper and trainer are short-lived job images — there is no deployment to restart. The Training Hub spawns them as Kubernetes Jobs on demand.
