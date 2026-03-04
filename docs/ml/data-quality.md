# Training Data Quality

## What you have

| File | Records |
|---|---|
| `raw_issues.jsonl` | 4,014 |
| `raw_prs.jsonl` | 1,395 |
| `raw_website_docs.jsonl` | 339 |
| `raw_deepwiki.jsonl` | 37 |
| **`training_data.jsonl`** | **7,063 examples** |

## Positives

- Good format — `system/human/gpt` conversation triples (standard for instruction fine-tuning with Axolotl/Unsloth)
- Solid average answer length (905 chars), no empty answers
- Mix of sources: GitHub issues/PRs + official docs = real-world Q&A + reference knowledge
- Deduplication is partial (6,322 unique of 7,063 — ~18% duplicates worth cleaning)

## Concerns

- **~18% duplicate questions** — same question mapped to different answers (from multi-threaded issues). Fine-tuning on duplicates wastes compute and can cause instability.
- **Noisy GitHub issue answers** — early issues (e.g. `linkerd2#8`) contain outdated info (references to `conduit`, old CLI names). These will confuse the model.
- **Imbalanced sources** — 70% GitHub issues, 25% docs, 5% structured wiki. The model will lean toward issue-style responses rather than clean documentation style.
- **DeepWiki very sparse** — only 37 records from the structured wiki scrape. This is the highest-quality source and should be expanded.
- **Max answer length 3,016 chars** — fine for 7B models; if you ever go to 3B, you may want to trim very long examples.

> **Verdict:** Decent but not great. Deduplicate + filter old conduit-era issues before training.
