# Ollama Reference

## Ollama in Kubernetes

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

The Agent Hub exposes `POST /chat/stream` as a Server-Sent Events endpoint. As the model reasons and calls tools, the UI receives and renders each step in real time before the final answer arrives:

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

Then deploy without the in-cluster runtime, pointing the hub at your host:

```bash
MAC_IP=$(ipconfig getifaddr en0 || ipconfig getifaddr en1)
helm upgrade todea ./helm/todea -n todea --reuse-values \
  --set ollamaRuntime.enabled=false \
  --set ollamaHub.ollamaHost=http://$MAC_IP:11434
```

---

## Tool-calling behaviour

The Agent Hub fetches the tool list at startup and presents it to the Ollama model. The root agent sees only 5 virtual tools (`call_*_agent`); sub-agent loops receive only the MCP tools owned by that sub-agent. To work reliably with smaller local models (llama3.1:8b), the hub applies several layers of robustness:

### 3-tier tool-call extraction

Handles models that don't reliably use the structured `tool_calls` API:

1. **Structured `tool_calls`** field in the Ollama response (ideal path)
2. **Inline JSON scanner** — finds `{"name": "...", "parameters": {...}}` embedded in the content text
3. **Constrained re-prompt** — re-asks the model with `format=json` to extract the tool call when a known tool name appears in content but no JSON was found

### Argument sanitisation

Before every MCP tool call, any argument key not present in the tool's JSON Schema is stripped. This prevents Pydantic validation errors when the model guesses wrong parameter names (e.g. `repo-url` instead of `repo_url`). Tools with all-optional parameters (like `helm_repo_add`) succeed with their defaults.

### Tool name fuzzy matching

Hallucinated tool names are matched against known tools by substring and token-overlap scoring before the call is rejected.

### Model recommendations

| Model | Tool use reliability |
|---|---|
| `llama3.1:8b` | Good — recommended default |
| `llama3.2:3b` / `llama3.2:1b` | Poor — often outputs bash commands or prose instead of structured `tool_calls` |

### Debugging

When the model outputs tool calls as text but they don't execute, check the Agent Hub server logs for:

| Log message | Meaning |
|---|---|
| `Loaded N MCP tools` | MCP is reachable and tools were fetched |
| `Found N inline tool call(s)` | Inline JSON was detected (tier 2) |
| `Extracted tool call via model` | Third-tier re-prompt was triggered |
| `Calling MCP tool '...'` | Actual tool execution |

If none of these appear, the server was not restarted after a code change or the Docker image was not rebuilt.
