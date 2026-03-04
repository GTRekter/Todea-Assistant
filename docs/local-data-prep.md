# Local Data Scraping & Preparation

This guide shows how to run the scraping pipeline locally and produce a `training_data.jsonl` file ready for upload to **Azure AI Studio** (or any other fine-tuning service that accepts ShareGPT-format JSONL).

---

## Prerequisites

| Tool | Version |
|---|---|
| Python | 3.10+ |
| GitHub personal access token | `repo:read` scope (for private/rate-limited requests) |

---

## 1. Install dependencies

```bash
cd servers/training-hub
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

> On Windows use `.venv\Scripts\activate` instead.

---

## 2. Set your GitHub token

```bash
export GITHUB_TOKEN=ghp_...
```

The token is only used for GitHub API calls (docs, issues, PRs). You can skip it for website-only scraping, but you will hit the unauthenticated rate limit quickly.

---

## 3. Create a local data directory

```bash
mkdir -p data
```

All raw JSONL files and the final `training_data.jsonl` land here.

---

## 4. Run individual scrapers (optional)

You can run each scraper independently if you only need specific data:

```bash
# GitHub markdown docs
python3 scrapers/docs.py \
  --repos linkerd/linkerd2 linkerd/linkerd2-proxy \
  --output data/raw_docs.jsonl

# GitHub issues
python3 scrapers/issues.py \
  --repos linkerd/linkerd2 linkerd/linkerd2-proxy \
  --output data/raw_issues.jsonl

# GitHub pull requests
python3 scrapers/pull_requests.py \
  --repos linkerd/linkerd2 linkerd/linkerd2-proxy \
  --output data/raw_prs.jsonl

# Website docs (linkerd.io and/or docs.buoyant.io)
python3 scrapers/website_docs.py \
  --sites linkerd.io docs.buoyant.io \
  --output data/raw_website_docs.jsonl

# DeepWiki
python3 scrapers/deepwiki.py \
  --output data/raw_deepwiki.jsonl
```

---

## 5. Run the full pipeline at once

`runner.py` orchestrates all scrapers and calls the formatter at the end:

```bash
python3 scrapers/runner.py \
  --repos linkerd/linkerd2,linkerd/linkerd2-proxy \
  --websites linkerd.io,docs.buoyant.io,deepwiki
```

Output: `data/training_data.jsonl`

> The runner **skips missing source files** gracefully, so you can omit `--repos` to scrape only websites, or omit `--websites` to scrape only GitHub.

---

## 6. Format raw data into training pairs

If you ran the scrapers individually and want to (re-)format:

```bash
python3 scrapers/format_data.py \
  --issues   data/raw_issues.jsonl \
  --prs      data/raw_prs.jsonl \
  --docs     data/raw_docs.jsonl \
  --websites data/raw_website_docs.jsonl \
  --deepwiki data/raw_deepwiki.jsonl \
  --output   data/training_data.jsonl
```

The formatter prints a summary:

```
Issues   — read:   1234  pairs written:    876
PRs      — read:    456  pairs written:    312
Docs     — read:    789  pairs written:   1540
...
Total    — read:   2479  pairs written:   2728
Output: /…/data/training_data.jsonl
```

---

## 7. Output format

Each line of `training_data.jsonl` is a **ShareGPT conversation object**:

```json
{
  "conversations": [
    {"from": "system", "value": "You are an expert on Linkerd…"},
    {"from": "human",  "value": "Explain the Linkerd identity component."},
    {"from": "gpt",    "value": "The identity component issues…"}
  ],
  "source": "linkerd/linkerd2/doc/identity.md"
}
```

This format is accepted by Unsloth, Axolotl, LLaMA-Factory, and is compatible with the Azure AI Studio custom fine-tuning format after a minor conversion (see section 8).

---

## 8. Convert for Azure AI Studio

Azure AI Studio fine-tuning expects **OpenAI chat format**:

```json
{"messages": [
  {"role": "system",    "content": "…"},
  {"role": "user",      "content": "…"},
  {"role": "assistant", "content": "…"}
]}
```

Run the one-liner conversion:

```bash
python - <<'EOF'
import json, sys

role_map = {"system": "system", "human": "user", "gpt": "assistant"}

with open("data/training_data.jsonl") as fin, \
     open("data/training_data_azure.jsonl", "w") as fout:
    for line in fin:
        rec = json.loads(line)
        messages = [
            {"role": role_map[t["from"]], "content": t["value"]}
            for t in rec["conversations"]
        ]
        fout.write(json.dumps({"messages": messages}) + "\n")

print("Done — data/training_data_azure.jsonl")
EOF
```

Upload `data/training_data_azure.jsonl` to Azure AI Studio.

---

## 9. Quick sanity check

```bash
# Count training pairs
wc -l data/training_data.jsonl

# Preview the first record (pretty-printed)
python -c "import json; print(json.dumps(json.loads(open('data/training_data.jsonl').readline()), indent=2))"

# Check for malformed lines
python -c "
import json
bad = 0
for i, l in enumerate(open('data/training_data.jsonl'), 1):
    try: json.loads(l)
    except: print(f'line {i}: {l[:80]}'); bad += 1
print(f'{bad} bad lines')
"
```

---

## 10. Typical run times (MacBook M-series)

| Source | Records | Time |
|---|---|---|
| GitHub docs (2 repos) | ~800 files | ~2 min |
| GitHub issues (2 repos, 500 issues) | ~500 | ~5 min |
| GitHub PRs (2 repos, 200 PRs) | ~200 | ~3 min |
| linkerd.io website | ~150 pages | ~4 min |
| deepwiki | ~80 pages | ~2 min |
| **Total** | — | **~15 min** |

Rate-limit pauses are built into the scrapers; no manual throttling is needed.
