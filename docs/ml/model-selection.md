# Model Selection & Infrastructure

## llama3.1:8b vs Qwen2.5-7B-Instruct

### Head-to-head

| Dimension | Llama 3.1 8B | Qwen2.5-7B-Instruct | Winner |
|---|---|---|---|
| **Tool calling** | Decent, needs 3-tier fallback | Native, more reliable structured output | Qwen2.5 |
| **Code understanding** (Go/Rust) | Average | Strong — trained heavily on code | Qwen2.5 |
| **Instruction following** | Good | Better, more consistent | Qwen2.5 |
| **Knowledge cutoff** | Mar 2024 | Sep 2024 | Qwen2.5 |
| **Context window** | 128k | 128k | Tie |
| **Fine-tuning (LoRA/QLoRA)** | Well-documented | Well-documented | Tie |
| **Benchmarks** (MMLU, HumanEval, etc.) | Lower | Consistently higher at 7B | Qwen2.5 |
| **Ollama support** | Native, well-tested | Supported | Tie |
| **RAG integration** | Good | Good | Tie |

### The tool-calling point deserves emphasis

The entire 3-tier fallback system in `ollama-hub` exists because `llama3.1:8b` is unreliable at structured tool output. Qwen2.5-7B-Instruct handles function calling more natively — you might be able to simplify or remove some of that fallback logic.

### The one caveat

Qwen2.5 was trained by Alibaba. If your environment has restrictions on model provenance (enterprise, regulated industry), that's worth checking. For most use cases it's a non-issue.

### Practical recommendation

Switch to Qwen2.5-7B-Instruct as the **base model** for both inference and fine-tuning:

- [`servers/ollama-hub/app.py`](../../servers/ollama-hub/app.py) — `AGENT_MODEL_OLLAMA` default
- [`helm/todea/values.yaml`](../../helm/todea/values.yaml) — `ollamaHub.env.AGENT_MODEL_OLLAMA`

```bash
ollama pull qwen2.5:7b-instruct
```

Then test the tool-calling flow — you'll likely find it needs fewer fallback tiers, which means simpler, faster responses.

---

## AKS vs Home GPU

| | Home GPU (RTX 3090) | AKS Spot GPU |
|---|---|---|
| **Upfront cost** | ~$700 | $0 |
| **Per training run** | ~$0.05 (electricity) | ~$0.30–0.75 |
| **Monthly (weekly runs)** | ~$3–5 | ~$1–3 |
| **Setup complexity** | Medium | Medium |
| **Hardware maintenance** | Yes | None |
| **Availability** | Always on | Node spins up in ~5 min |
| **Scales to zero** | No | Yes |
| **Fits existing k8s stack** | Separate machine | Native |

For your scale (7B QLoRA, ~7k examples, weekly retraining), AKS spot is cheap enough that it beats buying hardware — especially since you're not training 24/7.

### GPU node SKUs on Azure

| SKU | GPU | VRAM | Spot price | Training time |
|---|---|---|---|---|
| `Standard_NC4as_T4_v3` | 1× T4 | 16 GB | ~$0.10–0.15/hr | ~90–120 min |
| `Standard_NVadsA10_v5` | 1× A10 | 24 GB | ~$0.30–0.50/hr | ~40–60 min |
| `Standard_NC24ads_A100_v4` | 1× A100 | 80 GB | ~$1.00–1.50/hr | ~15–25 min |

> **Recommendation:** `Standard_NC4as_T4_v3` spot — cheapest, T4 handles 7B QLoRA fine with 16 GB, each run costs ~$0.25.

---

## MLOps Tool Landscape

```
Complexity / Scale
     ▲
High │  Kubeflow    Vertex AI    SageMaker
     │  (Google)    (Google)     (AWS)
     │
     │  Ray + KubeRay             Azure ML
     │
     │  Flyte        Metaflow
     │               (Netflix)
     │
     │  Argo Workflows + MLflow   ← most common sweet spot
     │
Low  │  Plain K8s Jobs + MLflow
     └──────────────────────────────────────► Team size / Budget
          Small                          Large
```

### What each tier actually uses

**Big tech (Google, Meta, OpenAI, Anthropic)**
- Fully custom internal systems; Ray for distributed training; hundreds/thousands of GPUs
- Irrelevant to your use case

**Enterprise (banks, large SaaS, Fortune 500)**
- Kubeflow (on GKE), Azure ML (Azure shops), SageMaker (AWS shops)
- Heavy governance, audit trails, model registries

**Mid-size ML teams (50–500 engineers)**
- Argo Workflows + MLflow; Ray/KubeRay for distributed training; W&B for experiment tracking

**Startups / small teams**
- Plain Kubernetes Jobs — this is very common in practice
- MLflow self-hosted for tracking

### The honest truth about Kubeflow

| | Kubeflow | Reality |
|---|---|---|
| **Setup** | Complex (10+ components) | Teams spend weeks just getting it running |
| **Maintenance** | High | Upgrades are painful |
| **Who uses it** | Large orgs with dedicated MLOps teams | Not startups |
| **Overkill for** | Single-model fine-tuning | Your use case |

### What's actually popular for LLM fine-tuning

The LLM fine-tuning space converged on a simpler stack:

```
Data prep      →  plain Python scripts
Training       →  Axolotl or Unsloth (just a container)
Orchestration  →  Kubernetes Job (or Argo if complex)
Tracking       →  W&B or MLflow
Model registry →  Hugging Face Hub (private) or MLflow
Serving        →  vLLM / Ollama
```

### Recommended stack for AKS

```
┌─────────────────────────────────────────────────────┐
│  Recommended stack for your AKS setup               │
│                                                     │
│  Orchestration:   Argo Workflows                    │
│  ├── Scraper Job  (your existing scripts)           │
│  ├── Trainer Job  (Unsloth container)               │
│  └── Deploy Job   (patch + rollout)                 │
│                                                     │
│  Tracking:        MLflow (self-hosted in AKS)       │
│  ├── Logs loss curves per run                       │
│  ├── Stores hyperparameters                         │
│  └── Model registry (promote adapter to prod)       │
│                                                     │
│  Storage:         Azure Blob (data + adapters)      │
│  Images:          ACR (training container)          │
│  GPU nodes:       Spot NC4as_T4_v3 (scale to 0)    │
└─────────────────────────────────────────────────────┘
```

- **Why Argo over plain K8s Jobs:** Argo lets you chain scrape → train → eval → deploy as a single workflow with retry logic and step dependencies.
- **Why not Azure ML:** For one model, one team, it's overkill.

### The progression path

Start simple, add complexity only when you hit real problems:

```
Now:        Plain K8s Jobs  (works fine for first training runs)
    ↓
Next:       + MLflow        (once you want to compare runs)
    ↓
Later:      + Argo Workflows (once scrape→train→deploy needs automation)
    ↓
If/when:    + Ray + KubeRay  (only if training across multiple GPUs)
```

> **Don't install Kubeflow.** Unless you have a dedicated MLOps engineer who does nothing else.
