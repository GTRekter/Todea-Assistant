"""
format_training_data.py — Convert raw GitHub issues + docs into fine-tuning pairs.

Output format: ShareGPT (compatible with Unsloth, Axolotl, LLaMA-Factory)

    {"conversations": [
        {"from": "system", "value": "<system prompt>"},
        {"from": "human", "value": "<question>"},
        {"from": "gpt",   "value": "<answer>"}
    ], "source": "linkerd/linkerd2#1234"}

Usage:
    python format_training_data.py
    python format_training_data.py --issues data/raw_issues.jsonl \\
                                   --prs    data/raw_prs.jsonl    \\
                                   --docs   data/raw_docs.jsonl   \\
                                   --output data/training_data.jsonl
"""

import argparse
import json
import re
from pathlib import Path

# ─── Constants ────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = (
    "You are an expert on Linkerd, the open-source Kubernetes service mesh. "
    "You have deep knowledge of:\n"
    "- The Linkerd2 control plane (Go): identity, proxy-injector, destination, "
    "policy-controller, gateway, multicluster.\n"
    "- The Linkerd2-proxy data-plane sidecar (Rust): its internals, error codes, "
    "and observability.\n"
    "- Linkerd CLI commands and their output.\n"
    "- Kubernetes networking, mTLS, traffic policies, and Linkerd observability "
    "(linkerd viz, tap, stat, edges).\n"
    "- Common Linkerd errors, their root causes, and step-by-step solutions.\n\n"
    "Answer accurately and concisely. Use code blocks for commands and config snippets."
)

# Accounts whose comments we never use as training responses
BOT_ACCOUNTS = frozenset({
    "dependabot[bot]",
    "dependabot-preview[bot]",
    "linkerd-bot",
    "github-actions[bot]",
    "netlify[bot]",
    "codecov[bot]",
    "stale[bot]",
    "welcome[bot]",
})

# Labels that indicate actionable, high-value issues
GOOD_LABELS = frozenset({
    "bug", "enhancement", "question", "help wanted",
    "good first issue", "kind/bug", "kind/feature", "kind/question",
})

# Phrases that indicate a comment is just administrative noise
NOISE_PHRASES = (
    "closing this",
    "closing as",
    "this is a duplicate",
    "duplicate of #",
    "marked this as stale",
    "this issue has been automatically",
    "please reopen",
    "/close",
    "/label",
)

MIN_ISSUE_BODY = 80       # characters
MIN_COMMENT_LEN = 80      # characters for a response
MIN_RESPONSE_LEN = 120    # characters for final response
MAX_PROMPT_LEN = 4000     # truncate very long issue bodies
MAX_RESPONSE_LEN = 3000   # truncate very long comments


# ─── Text helpers ─────────────────────────────────────────────────────────────

def clean(text: str) -> str:
    """Normalize whitespace and strip HTML comments."""
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    text = re.sub(r"\r\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + "\n\n[...truncated]"


def is_bot(author: str) -> bool:
    return author in BOT_ACCOUNTS or author.endswith("[bot]")


# ─── Comment scoring ──────────────────────────────────────────────────────────

def score_comment(comment: dict) -> float:
    """
    Return a quality score for using this comment as a training response.
    Negative score = skip entirely.
    """
    if is_bot(comment["author"]):
        return -1.0

    body = comment["body"]
    if len(body) < MIN_COMMENT_LEN:
        return 0.0

    lower = body.lower()
    if any(phrase in lower for phrase in NOISE_PHRASES):
        return -1.0

    score = min(len(body) / 200, 8.0)  # length bonus, capped

    # Technical content bonuses
    score += body.count("```") * 0.8
    score += len(re.findall(r"`(?:kubectl|linkerd|helm)\s", body)) * 1.5
    score += len(re.findall(r"\b(error|fix|solution|cause|because|resolved)\b", lower)) * 0.3

    return score


# ─── Issue → training pairs ───────────────────────────────────────────────────

def issue_to_pairs(issue: dict) -> list[dict]:
    pairs = []
    title = issue["title"].strip()
    body = clean(issue.get("body") or "")
    comments = issue.get("comments", [])

    if len(title) < 10:
        return pairs

    # Build the human prompt
    if len(body) >= MIN_ISSUE_BODY:
        prompt = truncate(f"**Issue:** {title}\n\n{body}", MAX_PROMPT_LEN)
    else:
        prompt = title

    # Score all comments
    scored = [(score_comment(c), c) for c in comments]
    good = [(s, c) for s, c in scored if s > 1.0]
    if not good:
        return pairs
    good.sort(key=lambda x: x[0], reverse=True)

    # --- Pair 1: best single response ---
    best_score, best_comment = good[0]
    response = truncate(clean(best_comment["body"]), MAX_RESPONSE_LEN)
    if len(response) >= MIN_RESPONSE_LEN:
        pairs.append({
            "conversations": [
                {"from": "system", "value": SYSTEM_PROMPT},
                {"from": "human", "value": prompt},
                {"from": "gpt",   "value": response},
            ],
            "source": f"{issue['repo']}#{issue['number']}",
        })

    # --- Pair 2: multi-turn conversation (if ≥2 good human/bot turns) ---
    # Alternate human/gpt based on comment order; must end on gpt
    if len(good) >= 2:
        turns = [
            {"from": "system", "value": SYSTEM_PROMPT},
            {"from": "human", "value": prompt},
        ]
        for i, (_, c) in enumerate(good[:4]):
            role = "gpt" if i % 2 == 0 else "human"
            turn_text = truncate(clean(c["body"]), MAX_RESPONSE_LEN)
            if len(turn_text) < MIN_COMMENT_LEN:
                break
            turns.append({"from": role, "value": turn_text})

        if turns[-1]["from"] == "gpt":
            pairs.append({
                "conversations": turns,
                "source": f"{issue['repo']}#{issue['number']}-mt",
            })

    return pairs


# ─── Doc → training pairs ─────────────────────────────────────────────────────

def _split_doc_sections(content: str) -> list[tuple[str, str]]:
    """
    Split a markdown doc into (heading, body) pairs.
    Returns [] if the doc has no headings.
    """
    # Match H1/H2 headings
    pattern = re.compile(r"^(#{1,2})\s+(.+)$", re.MULTILINE)
    matches = list(pattern.finditer(content))
    if not matches:
        return []

    sections = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        heading = m.group(2).strip()
        body = content[start:end].strip()
        if body:
            sections.append((heading, body))
    return sections


def doc_to_pairs(doc: dict) -> list[dict]:
    pairs = []
    path: str = doc["path"]
    content = clean(doc.get("content") or "")
    repo = doc["repo"]

    if len(content) < 200:
        return pairs

    # Strategy 1: treat the whole doc as a reference answer
    # Use the explicit title if available (DeepWiki records carry one), else derive from path
    explicit_title = doc.get("title", "").strip()
    filename = explicit_title or Path(path).stem.replace("-", " ").replace("_", " ").title()
    prompt = f"Explain the Linkerd documentation section: {filename}"
    response = truncate(content, MAX_RESPONSE_LEN)
    if len(response) >= MIN_RESPONSE_LEN:
        pairs.append({
            "conversations": [
                {"from": "system", "value": SYSTEM_PROMPT},
                {"from": "human", "value": prompt},
                {"from": "gpt",   "value": response},
            ],
            "source": f"{repo}/{path}",
        })

    # Strategy 2: one pair per H1/H2 section
    for heading, body in _split_doc_sections(content):
        if len(body) < MIN_RESPONSE_LEN:
            continue
        section_prompt = f"Explain '{heading}' in the context of Linkerd."
        section_response = truncate(body, MAX_RESPONSE_LEN)
        pairs.append({
            "conversations": [
                {"from": "system", "value": SYSTEM_PROMPT},
                {"from": "human", "value": section_prompt},
                {"from": "gpt",   "value": section_response},
            ],
            "source": f"{repo}/{path}#{heading}",
        })

    return pairs


# ─── PR → training pairs ──────────────────────────────────────────────────────

# Noise phrases that indicate a review comment is administrative, not educational
_REVIEW_NOISE = (
    "lgtm", "looks good", "approved", "nit:", "/approve", "/lgtm",
    "thanks!", "thank you", "ping", "ptal", "please take a look",
)

MIN_PR_BODY = 100        # minimum chars for a PR body to be useful
MIN_REVIEW_BODY = 80     # minimum chars for a review comment to be useful


def _is_review_noise(body: str) -> bool:
    lower = body.lower().strip()
    return any(lower.startswith(p) or lower == p for p in _REVIEW_NOISE) or len(body) < MIN_REVIEW_BODY


def pr_to_pairs(pr: dict) -> list[dict]:
    pairs = []
    title = pr.get("title", "").strip()
    body = clean(pr.get("body") or "")
    comments = pr.get("comments", [])
    review_threads = pr.get("review_threads", [])
    repo = pr["repo"]
    source = f"{repo}#PR{pr['number']}"

    if not title:
        return pairs

    # --- Pair 1: PR description as explanation ---
    # "What does PR X change and why?" → PR body
    if len(body) >= MIN_PR_BODY:
        prompt = f"Explain the motivation and changes in this Linkerd pull request: {title}"
        response = truncate(body, MAX_RESPONSE_LEN)
        if len(response) >= MIN_RESPONSE_LEN:
            pairs.append({
                "conversations": [
                    {"from": "system", "value": SYSTEM_PROMPT},
                    {"from": "human", "value": prompt},
                    {"from": "gpt",   "value": response},
                ],
                "source": source,
            })

    # --- Pair 2: general discussion comments ---
    good_comments = [
        c for c in comments
        if not _is_review_noise(c.get("body", ""))
    ]
    if good_comments and len(body) >= 50:
        # Build a multi-turn: PR description → first good comment → ...
        turns = [
            {"from": "system", "value": SYSTEM_PROMPT},
            {"from": "human",  "value": truncate(f"{title}\n\n{body}", MAX_PROMPT_LEN)},
        ]
        for i, c in enumerate(good_comments[:4]):
            role = "gpt" if i % 2 == 0 else "human"
            text = truncate(clean(c["body"]), MAX_RESPONSE_LEN)
            turns.append({"from": role, "value": text})

        if turns[-1]["from"] == "gpt":
            pairs.append({"conversations": turns, "source": f"{source}-discussion"})

    # --- Pair 3: review threads (inline code review discussions) ---
    for i, thread in enumerate(review_threads):
        useful = [c for c in thread if not _is_review_noise(c.get("body", ""))]
        if len(useful) < 2:
            continue
        # First comment = question/observation, subsequent = answers
        turns = [
            {"from": "system", "value": SYSTEM_PROMPT},
            {"from": "human",  "value": f"In the context of this Linkerd PR ({title}):\n\n"
                                        + truncate(clean(useful[0]["body"]), MAX_PROMPT_LEN)},
        ]
        for j, c in enumerate(useful[1:4], start=1):
            role = "gpt" if j % 2 == 1 else "human"
            turns.append({"from": role, "value": truncate(clean(c["body"]), MAX_RESPONSE_LEN)})

        if turns[-1]["from"] == "gpt":
            pairs.append({"conversations": turns, "source": f"{source}-review{i}"})

    return pairs


# ─── Main ─────────────────────────────────────────────────────────────────────

def process_file(input_path: Path, converter, output_file) -> tuple[int, int]:
    """Read a JSONL file, convert each record, write pairs. Returns (read, written)."""
    read = written = 0
    with open(input_path) as f:
        for line in f:
            read += 1
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            for pair in converter(record):
                output_file.write(json.dumps(pair) + "\n")
                written += 1
    return read, written


def main():
    parser = argparse.ArgumentParser(
        description="Format raw Linkerd GitHub data into LLM fine-tuning pairs"
    )
    parser.add_argument("--issues",   default="data/raw_issues.jsonl")
    parser.add_argument("--prs",      default="data/raw_prs.jsonl")
    parser.add_argument("--docs",     default="data/raw_docs.jsonl")
    parser.add_argument("--deepwiki", default="data/raw_deepwiki.jsonl")
    parser.add_argument("--websites", default="data/raw_website_docs.jsonl")
    parser.add_argument("--output",   default="data/training_data.jsonl")
    args = parser.parse_args()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    total_read = total_written = 0

    sources = [
        ("Issues  ", Path(args.issues),   issue_to_pairs),
        ("PRs     ", Path(args.prs),      pr_to_pairs),
        ("Docs    ", Path(args.docs),     doc_to_pairs),
        ("DeepWiki", Path(args.deepwiki), doc_to_pairs),
        ("Websites", Path(args.websites), doc_to_pairs),  # linkerd.io + docs.buoyant.io
    ]

    with open(output_path, "w") as fout:
        for label, path, converter in sources:
            if path.exists():
                r, w = process_file(path, converter, fout)
                print(f"{label} — read: {r:>6}  pairs written: {w:>6}")
                total_read += r
                total_written += w
            else:
                print(f"{label} file not found: {path} — skipping")

    print(f"\nTotal   — read: {total_read:>6}  pairs written: {total_written:>6}")
    print(f"Output: {output_path.resolve()}")


if __name__ == "__main__":
    main()
