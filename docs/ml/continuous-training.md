# Continuous Training

## The loop

```
New data arrives         Trigger training        Deploy updated model
(GitHub issues/PRs) ──► (Kubernetes Job)    ──► (Ollama reload)
      ▲                                               │
      └───────────────────────────────────────────────┘
              Model improves over time
```

## What "continuous" means in practice

### 1. Scheduled retraining (simpler, recommended to start)

A Kubernetes CronJob runs weekly/nightly:

1. Scrape new issues/PRs/docs since last checkpoint
2. Append to training data
3. Launch a training Job (QLoRA fine-tune from the *previous* adapter, not from scratch)
4. Swap the adapter in Ollama

> **Key insight:** The scrapers already use `.pr_checkpoint.json` and `.checkpoint.json` — incremental data collection is already in place.

### 2. Event-triggered retraining (more sophisticated)

Trigger training when:
- N new examples accumulated (e.g. 500 new issues)
- A GitHub webhook fires on a new release
- Weekly regardless

## Full pipeline architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Kubernetes Cluster                    │
│                                                         │
│  CronJob (weekly)                                       │
│  ┌──────────────┐                                       │
│  │ 1. Scraper   │ → PVC: /data/training_data.jsonl      │
│  │   Job        │   (incremental, uses checkpoints)     │
│  └──────┬───────┘                                       │
│         │ triggers                                      │
│  ┌──────▼───────┐                                       │
│  │ 2. Trainer   │ → PVC: /models/adapter-{date}/        │
│  │   Job (GPU)  │   (QLoRA, ~2-4h on T4)               │
│  └──────┬───────┘                                       │
│         │ on success                                    │
│  ┌──────▼───────┐                                       │
│  │ 3. Deploy    │ → Patch Ollama Hub env                │
│  │   Job        │   ADAPTER_PATH=adapter-{date}         │
│  └──────────────┘   Rolling restart ollama-hub          │
│                                                         │
│  ollama-hub  ←──── loads base model + latest adapter   │
└─────────────────────────────────────────────────────────┘
```

## Key design decisions

### Training strategy

| Strategy | How | Cost | Risk |
|---|---|---|---|
| **Full retrain** | Train adapter from scratch each time | High (hours) | Safe, no drift |
| **Continual LoRA** | Fine-tune previous adapter on new data | Low (minutes) | Catastrophic forgetting |
| **Replay buffer** | Mix new + old data each run | Medium | Best quality |

> **Recommended:** Replay buffer — keep the last ~2,000 old examples + all new ones each training run. This prevents the model from forgetting what it learned before.

### Model versioning

Store adapters with timestamps: `adapter-2026-02-28/`. Never overwrite — roll back if the new model regresses.

### Regression detection (optional but important)

Before deploying, run a small eval set (e.g. 50 golden Q&A pairs) and only promote the adapter if it scores better than the previous one. Otherwise you risk silently degrading the model.

## What you'd need to build

- **Scraper CronJob** — wrap existing scripts in a K8s CronJob (checkpointing logic is already in place)
- **Trainer Job** — Axolotl or Unsloth container, reads from PVC, writes adapter to PVC
- **Deploy Job** — calls Ollama API or patches the Deployment to pick up new adapter
- **PersistentVolumeClaim** — shared storage between all three jobs
- **Optional eval gate** — simple script comparing new adapter vs previous on golden examples

## What you'd need externally

- A GPU node (cloud spot instance) — k3d local cluster can't do GPU training on macOS
- Or a hybrid: trigger a [Modal](https://modal.com) or [RunPod](https://runpod.io) GPU job from within the cluster, write results back to PVC
