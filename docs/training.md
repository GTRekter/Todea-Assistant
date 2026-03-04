# Training

## Training UI

The `/training` page in the React UI provides a full ML pipeline control panel — scraping, fine-tuning, and monitoring — without needing `kubectl` or a terminal.

### What it does

```
┌─────────────────────────────────────────────────────────────┐
│  Training                                                   │
├─────────────────────────────────────────────────────────────┤
│  1. DATA SOURCES                                            │
│     GitHub token [••••••••]  [Save]                        │
│     Repos:  ☑ linkerd/linkerd2  ☑ linkerd/linkerd2-proxy   │
│     Sites:  ☑ linkerd.io/docs  ☑ docs.buoyant.io           │
│                                          [Start scraping]   │
│                                                             │
│  2. MODEL CONFIGURATION                                     │
│     Base model  [qwen2.5:7b-instruct ▼]                    │
│     Adapter     [adapter-2026-02-28   ]                     │
│     GPU pool    [gpupool              ]                     │
│                                          [Start training]   │
│                                                             │
│  3. JOB STATUS                                              │
│     ● Running  scraper  todea-scraper-20260228-…   [Logs]  │
│     ○ Pending  trainer                                      │
│                                                             │
│  4. LIVE LOGS  ── todea-scraper-20260228-…                  │
│     > Fetching linkerd/linkerd2 (4,014 issues)…            │
│     > Written 127 new examples                             │
└─────────────────────────────────────────────────────────────┘
```

### How it works

1. **Save GitHub token** — stored as Kubernetes Secret `todea-github-token` via the Training Hub API. The token is never persisted in the UI or a database.
2. **Select sources** — choose which GitHub repos and documentation websites to scrape.
3. **Start scraping** — creates a `todea-scraper-{timestamp}` Kubernetes Job. The job is incremental (uses the existing checkpoints in the PVC) and runs on any node.
4. **Configure model** — select the base model, name the output adapter (defaults to today's date), and optionally specify a GPU node pool name.
5. **Start training** — creates a `todea-trainer-{timestamp}` Kubernetes Job targeted to the GPU node pool with a `nvidia.com/gpu: 1` resource request. Spot/preemptible node tolerations are applied automatically.
6. **Monitor** — the Job status table polls every 5 seconds. Click **Logs** on any job to open a live SSE log stream in the terminal panel below. Running jobs can be cancelled directly from the UI.

### Deploying the Training Hub

Add the Training Hub image to your build and import steps:

```bash
docker build -t todea-training-hub:local ./servers/training-hub
k3d image import todea-training-hub:local -c todea
```

The Training Hub is enabled by default (`trainingHub.enabled=true`). It is included in the standard Helm upgrade with no extra flags:

```bash
helm upgrade todea ./helm/todea --namespace todea --reuse-values
```

To use a cloud GPU node pool (e.g. AKS spot `Standard_NC4as_T4_v3`), set the node selector values:

```bash
helm upgrade todea ./helm/todea --namespace todea --reuse-values \
  --set trainingHub.gpuNodeSelectorKey=agentpool \
  --set trainingHub.gpuNodeSelectorValue=gpupool
```

### Kubernetes RBAC

The Training Hub runs with a dedicated ServiceAccount bound to a namespaced `Role` (not a `ClusterRole`) that grants only what is needed:

| Resource | Verbs |
|---|---|
| `batch/jobs` | create, get, list, watch, delete |
| `pods`, `pods/log` | get, list, watch |
| `secrets` | create, get, update |

### PersistentVolumeClaim

Both the scraper and trainer Jobs mount a shared PVC (`todea-training-data` by default) at `/data`. Create it before running your first job:

```bash
kubectl apply -n todea -f - <<'EOF'
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: todea-training-data
spec:
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 20Gi
EOF
```

On AKS use the `managed-csi` storage class; on k3d the default `local-path` class works out of the box.

---

## Fine-tuning a custom Linkerd model

A self-contained pipeline for fine-tuning a Llama or Qwen model on Linkerd documentation, producing a LoRA adapter that can be merged and served via Ollama.

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
