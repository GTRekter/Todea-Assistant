# Deployment

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
docker build -t todea-training-hub:local      ./servers/training-hub
docker build -t todea-scraper:local  -f ./servers/training-hub/Dockerfile.scraper  ./servers/training-hub
docker build -t todea-trainer:local  -f ./servers/training-hub/Dockerfile.trainer  ./servers/training-hub

k3d image import --cluster todea \
  todea-web:local \
  todea-mcp:local \
  todea-helm-agent:local \
  todea-agent-hub:local \
  todea-conversation-hub:local \
  todea-training-hub:local \
  todea-scraper:local \
  todea-trainer:local
```

Deploy:

```bash
helm upgrade --install todea ./helm/todea \
  --namespace todea --create-namespace \
  --set web.image.repository=todea-web                        --set web.image.tag=local \
  --set mcp.image.repository=todea-mcp                        --set mcp.image.tag=local \
  --set helmAgent.image.repository=todea-helm-agent           --set helmAgent.image.tag=local \
  --set agentHub.image.repository=todea-agent-hub             --set agentHub.image.tag=local \
  --set conversationHub.image.repository=todea-conversation-hub --set conversationHub.image.tag=local \
  --set trainingHub.image.repository=todea-training-hub       --set trainingHub.image.tag=local \
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
docker build -t todea-training-hub:local      ./servers/training-hub
docker build -t todea-scraper:local  -f ./servers/training-hub/Dockerfile.scraper  ./servers/training-hub
docker build -t todea-trainer:local  -f ./servers/training-hub/Dockerfile.trainer  ./servers/training-hub
docker build -t todea-ollama-runtime:local    ./servers/ollama-runtime

k3d image import --cluster todea \
  todea-web:local \
  todea-mcp:local \
  todea-helm-agent:local \
  todea-ollama-hub:local \
  todea-conversation-hub:local \
  todea-training-hub:local \
  todea-scraper:local \
  todea-trainer:local \
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
  --set trainingHub.image.repository=todea-training-hub \
  --set trainingHub.image.tag=local \
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
