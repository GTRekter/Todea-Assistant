# Linkerd Agent — Fine-Tuning Pipeline

This directory contains scripts to collect training data from Linkerd's public
resources and fine-tune a local `llama3.1:8b` model to become a Linkerd expert.

The fine-tuned model replaces the base model in the Ollama Hub service without
changing any other part of the stack.

---

## Overview

```
┌─────────────────────────────────────────────────────────────┐
│  Data collection                                            │
│                                                             │
│  fetch_issues.py   ──►  data/raw_issues.jsonl   (~5k items) │
│  fetch_docs.py     ──►  data/raw_docs.jsonl     (~100 items)│
│  fetch_deepwiki.py ──►  data/raw_deepwiki.jsonl  (37 items) │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
              format_training_data.py
                            │
                            ▼
               data/training_data.jsonl
               (ShareGPT format, ~3-8k pairs)
                            │
                            ▼
           Fine-tune llama3.1:8b  (Unsloth)
                            │
                            ▼
            Export to GGUF  (llama.cpp)
                            │
                            ▼
          Import into Ollama  (Modelfile)
                            │
                            ▼
     Update AGENT_MODEL_OLLAMA in values.yaml
```

---

## Prerequisites

### Python environment

```bash
cd scripts/training
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### GitHub token (for data collection)

Create a **classic personal access token** at <https://github.com/settings/tokens>.
No scopes are needed — the repos are public.

```bash
export GITHUB_TOKEN=ghp_...
```

---

## Step 1 — Collect training data

Run the three fetch scripts. Each is **resumable** — re-running skips already
downloaded items.

### 1a. GitHub issues + comments

Downloads all open and closed issues (with comments) from both Linkerd repos.
Issues with good resolution comments become Q&A training pairs.

```bash
python fetch_issues.py
# Options:
#   --repos  linkerd/linkerd2 linkerd/linkerd2-proxy   (default)
#   --output data/raw_issues.jsonl                     (default)
# Runtime: ~15–25 min with a GitHub token
```

### 1b. Markdown documentation from the repos

Fetches all `.md` files from `docs/`, `design/`, `rfcs/`, `CHANGELOG`, etc.

```bash
python fetch_docs.py
# Options:
#   --repos  linkerd/linkerd2 linkerd/linkerd2-proxy   (default)
#   --output data/raw_docs.jsonl                       (default)
# Runtime: ~2–3 min
```

### 1c. DeepWiki AI-generated wiki pages

Scrapes 37 structured pages from DeepWiki covering architecture, components,
deployment, proxy internals, error handling, and more.

```bash
python fetch_deepwiki.py
# Options:
#   --output data/raw_deepwiki.jsonl   (default)
# Runtime: ~1–2 min
```

> **If pages come back with very little content** (DeepWiki may require
> JavaScript rendering), install Playwright and use the `--playwright` flag:
>
> ```bash
> pip install playwright
> playwright install chromium
> python fetch_deepwiki.py --playwright
> ```

---

## Step 2 — Format training data

Converts all three raw sources into ShareGPT-format conversation pairs.
Filters out low-quality entries (bot noise, very short responses, etc.).

```bash
python format_training_data.py
# Options:
#   --issues   data/raw_issues.jsonl    (default)
#   --docs     data/raw_docs.jsonl      (default)
#   --deepwiki data/raw_deepwiki.jsonl  (default)
#   --output   data/training_data.jsonl (default)
```

Expected output:
```
Issues   — read:   5241  pairs written:   2108
Docs     — read:     97  pairs written:    312
DeepWiki — read:     37  pairs written:    180

Total    — read:   5375  pairs written:   2600
Output: .../data/training_data.jsonl
```

Each training pair looks like this:
```json
{
  "conversations": [
    {"from": "system", "value": "You are an expert on Linkerd..."},
    {"from": "human",  "value": "Issue: Proxy failing TLS handshake\n\n..."},
    {"from": "gpt",    "value": "This typically means the identity controller..."}
  ],
  "source": "linkerd/linkerd2#3421"
}
```

---

## Step 3 — Fine-tune the model

### Hardware requirements

| GPU VRAM | What fits |
|----------|-----------|
| 8 GB     | llama3.1:8b with 4-bit quantization (minimum) |
| 16 GB    | Comfortable 4-bit, can increase batch size |
| 24 GB+   | Full fine-tune or 8-bit |

On CPU only: possible but very slow (hours per epoch vs. minutes on GPU).

### Install Unsloth

[Unsloth](https://github.com/unslothai/unsloth) dramatically reduces VRAM usage
and speeds up fine-tuning.

```bash
# CUDA 12.1
pip install "unsloth[colab-new] @ git+https://github.com/unslothai/unsloth.git"
pip install --no-deps trl peft accelerate bitsandbytes
```

> For other CUDA versions or CPU-only, see the
> [Unsloth installation guide](https://github.com/unslothai/unsloth#installation).

### Fine-tuning script

Run it:
```bash
python finetune.py
# Runtime: ~30–90 min on a 16GB GPU for 3 epochs over ~2500 pairs
```

---

## Step 4 — Export to GGUF

Convert the fine-tuned model to GGUF format so Ollama can load it.

### Option A — Export directly with Unsloth (simplest)

Add this to the end of `finetune.py` (or run separately after loading the adapter):

```python
# Merge LoRA into base model and export to GGUF
model.save_pretrained_gguf(
    "output/linkerd-llama3.1-8b",
    tokenizer,
    quantization_method="q4_k_m",   # good balance of size vs quality
)
# Produces: output/linkerd-llama3.1-8b-Q4_K_M.gguf
```

### Option B — Export with llama.cpp (more control)

```bash
git clone https://github.com/ggerganov/llama.cpp
cd llama.cpp && make

# Merge adapter into base model first
python -c "
from unsloth import FastLanguageModel
model, tokenizer = FastLanguageModel.from_pretrained('output/lora-adapter', load_in_4bit=True)
model.save_pretrained_merged('output/merged-model', tokenizer)
"

# Convert to GGUF
python convert_hf_to_gguf.py ../output/merged-model \
    --outfile ../output/linkerd-llama3.1-8b.gguf \
    --outtype q4_k_m
```

---

## Step 5 — Import into Ollama

Create a `Modelfile` in the output directory:

```
FROM ./linkerd-llama3.1-8b-Q4_K_M.gguf

SYSTEM """
You are an expert on Linkerd, the open-source Kubernetes service mesh.
You have deep knowledge of the control plane (Go), the data-plane proxy (Rust),
Linkerd CLI commands, mTLS, traffic policies, and observability.
Answer accurately and concisely. Use code blocks for commands and config snippets.
"""

PARAMETER temperature 0.3
PARAMETER top_p 0.9
PARAMETER num_ctx 4096
```

Then create the model in Ollama:

```bash
cd output
ollama create linkerd-llama3.1:8b -f Modelfile
ollama run linkerd-llama3.1:8b "What causes a 'certificate verify failed' error in Linkerd?"
```

---

## Step 6 — Deploy the new model

Update the model name in the Helm values:

```yaml
# helm/todea/values.yaml
ollamaHub:
  env:
    AGENT_MODEL_OLLAMA: "linkerd-llama3.1:8b"
```

If running in k3d, the model file needs to be accessible to the Ollama pod.
The simplest approach is to push it to your local Ollama instance (which the
cluster already calls) and just update the model name.

```bash
# Verify the model is listed in Ollama
ollama list

# Apply the Helm change
helm upgrade todea ./helm/todea
```

---

## Iterating and improving

### Adding your own corrections

When you notice the model gives a wrong answer, save the correct version:

```bash
cat >> data/corrections.jsonl << 'EOF'
{"conversations": [{"from": "system", "value": "You are a Linkerd expert..."}, {"from": "human", "value": "<your question>"}, {"from": "gpt", "value": "<correct answer>"}], "source": "manual"}
EOF
```

Then merge it into training data and fine-tune again:
```bash
cat data/training_data.jsonl data/corrections.jsonl > data/training_data_v2.jsonl
```

### Refreshing data from GitHub

The fetch scripts are resumable but only append new items. To do a full refresh:
```bash
rm data/raw_issues.jsonl  # or just keep appending for incremental updates
python fetch_issues.py
python format_training_data.py
```

### Evaluating quality

Before deploying, test the model on known questions:
```bash
ollama run linkerd-llama3.1:8b "List the ports used by the Linkerd proxy sidecar and their purpose."
ollama run linkerd-llama3.1:8b "How does Linkerd's identity controller issue mTLS certificates?"
ollama run linkerd-llama3.1:8b "What does 'linkerd viz stat deploy' show?"
```

Compare against the base `llama3.1:8b` responses to confirm improvement.
