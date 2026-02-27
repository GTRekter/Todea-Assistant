"""
fetch_pull_requests.py — Download merged PRs + review discussions from Linkerd repos.

Complementary to fetch_issues.py. PRs provide:
- "Why was this change made" reasoning (PR body / description)
- Design discussions and trade-off analysis (review comment threads)
- Accepted solutions to real problems (merged = approved by maintainers)

Filters applied:
- Merged PRs only (closed-without-merge are excluded)
- Skip bot authors (dependabot, github-actions, etc.)
- Skip noise PRs by title pattern (dependency bumps, CI chores, typos)
- Collect both general PR comments AND inline review comment threads

Usage:
    export GITHUB_TOKEN=ghp_...
    python fetch_pull_requests.py
    python fetch_pull_requests.py --repos linkerd/linkerd2 --output data/raw_prs.jsonl

Output: JSONL file, one PR per line:
    {"repo": ..., "number": ..., "title": ..., "body": ..., "merged_at": ...,
     "labels": [...], "author": ...,
     "comments": [...],          # general discussion comments
     "review_threads": [...]}    # inline review comment threads grouped by thread
The script is resumable — already-fetched PRs are skipped on re-run.
"""

import argparse
import json
import os
import re
import time
from pathlib import Path

import requests

DEFAULT_REPOS = ["linkerd/linkerd2", "linkerd/linkerd2-proxy"]
GITHUB_API = "https://api.github.com"

BOT_ACCOUNTS = frozenset({
    "dependabot[bot]",
    "dependabot-preview[bot]",
    "linkerd-bot",
    "github-actions[bot]",
    "netlify[bot]",
    "codecov[bot]",
    "stale[bot]",
    "welcome[bot]",
    "renovate[bot]",
})

# PRs whose titles match these patterns are noise — skip them
NOISE_TITLE_PATTERNS = re.compile(
    r"""
    ^\s*(
        bump\s               |   # "bump X from Y to Z"
        update\s.*\sto\s     |   # "update foo to 1.2.3"
        chore[:/]            |   # "chore: ..."
        ci[:/]               |   # "ci: ..."
        deps[:/]             |   # "deps: ..."
        build[:/]            |   # "build: update ..."
        fix\stypo            |   # "fix typo in ..."
        typo                 |   # "typo: ..."
        \[bot\]              |   # "[bot] something"
        dependabot
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Stop paginating when this many consecutive pages have all-known PRs
EARLY_STOP_PAGES = 3


# ─── HTTP helpers (same pattern as fetch_issues.py) ──────────────────────────

def build_headers(token: str | None) -> dict:
    h = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def wait_for_rate_limit(response: requests.Response) -> None:
    remaining = int(response.headers.get("X-RateLimit-Remaining", 10))
    if remaining < 5:
        reset_ts = int(response.headers.get("X-RateLimit-Reset", time.time() + 60))
        wait = max(reset_ts - time.time() + 2, 0)
        print(f"    [rate limit] {remaining} requests left — sleeping {wait:.0f}s")
        time.sleep(wait)


def paginate(url: str, headers: dict, params: dict | None = None, max_retries: int = 6):
    """Yield all items from a paginated GitHub API endpoint, with exponential backoff."""
    params = {**(params or {}), "per_page": 100}
    page = 1
    while True:
        params["page"] = page
        for attempt in range(max_retries):
            try:
                resp = requests.get(url, headers=headers, params=params, timeout=30)
                resp.raise_for_status()
                wait_for_rate_limit(resp)
                break
            except (requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout) as e:
                if attempt == max_retries - 1:
                    raise
                wait = 2 ** attempt
                print(f"    Network error (attempt {attempt + 1}/{max_retries}), "
                      f"retrying in {wait}s: {e}")
                time.sleep(wait)
        data = resp.json()
        if not data:
            break
        yield from data
        if "next" not in resp.links:
            break
        page += 1


def fetch_all_pages(url: str, headers: dict, params: dict | None = None) -> list:
    try:
        return list(paginate(url, headers, params))
    except requests.exceptions.RequestException as e:
        print(f"    Warning: failed to fetch {url}: {e}")
        return []


# ─── PR filtering ─────────────────────────────────────────────────────────────

def is_bot(author: str) -> bool:
    return author in BOT_ACCOUNTS or author.endswith("[bot]")


def is_noise_pr(pr: dict) -> bool:
    """Return True for PRs that are unlikely to contain useful training signal."""
    title = pr.get("title", "")
    if NOISE_TITLE_PATTERNS.match(title):
        return True
    if is_bot(pr["user"]["login"]):
        return True
    return False


# ─── Fetching PR sub-resources ────────────────────────────────────────────────

def fetch_pr_comments(repo: str, pr_number: int, headers: dict) -> list:
    """Fetch general (issue-style) comments on a PR."""
    url = f"{GITHUB_API}/repos/{repo}/issues/{pr_number}/comments"
    raw = fetch_all_pages(url, headers)
    return [
        {
            "author": c["user"]["login"],
            "body": (c["body"] or "").strip(),
            "created_at": c["created_at"],
        }
        for c in raw
        if not is_bot(c["user"]["login"]) and len((c.get("body") or "")) >= 20
    ]


def fetch_review_threads(repo: str, pr_number: int, headers: dict) -> list[list[dict]]:
    """
    Fetch inline review comments grouped into threads.
    GitHub review comments have an `in_reply_to_id` field that links replies
    to the top-level comment. We group them so each thread is a list of
    (author, body) pairs — useful for multi-turn training examples.
    """
    url = f"{GITHUB_API}/repos/{repo}/pulls/{pr_number}/comments"
    raw = fetch_all_pages(url, headers)

    # Group by thread: top-level comments start new threads, replies extend them
    threads: dict[int, list[dict]] = {}   # root_id → [comment, ...]
    for c in raw:
        if is_bot(c["user"]["login"]):
            continue
        body = (c.get("body") or "").strip()
        if len(body) < 30:
            continue
        entry = {
            "author": c["user"]["login"],
            "body": body,
            "created_at": c["created_at"],
        }
        root_id = c.get("in_reply_to_id") or c["id"]
        threads.setdefault(root_id, []).append(entry)

    # Only keep threads with at least 2 turns (discussion, not lone comment)
    # Single-comment threads are still included if the comment is long enough
    result = []
    for thread in threads.values():
        if len(thread) >= 2 or (len(thread) == 1 and len(thread[0]["body"]) >= 100):
            result.append(thread)
    return result


# ─── Checkpoint helpers ───────────────────────────────────────────────────────

def _checkpoint_path(output_path: Path) -> Path:
    return output_path.parent / ".pr_checkpoint.json"


def _load_checkpoints(output_path: Path) -> dict:
    cp = _checkpoint_path(output_path)
    if cp.exists():
        try:
            return json.loads(cp.read_text())
        except (json.JSONDecodeError, OSError):
            pass

    # Bootstrap from existing JSONL: find the max PR number per repo
    if not output_path.exists():
        return {}

    print("  No checkpoint found — bootstrapping from saved data (one-time scan) ...")
    max_number: dict[str, int] = {}
    with open(output_path) as f:
        for line in f:
            try:
                d = json.loads(line)
                repo = d["repo"]
                n = d.get("number", 0)
                if n > max_number.get(repo, 0):
                    max_number[repo] = n
            except (json.JSONDecodeError, KeyError):
                pass

    if max_number:
        cp.write_text(json.dumps(max_number, indent=2))
        print(f"  Checkpoint bootstrapped: {max_number}")
    return max_number


def _save_checkpoint(output_path: Path, repo: str, pr_number: int) -> None:
    cp = _checkpoint_path(output_path)
    checkpoints = _load_checkpoints(output_path)
    if pr_number > checkpoints.get(repo, 0):
        checkpoints[repo] = pr_number
        cp.write_text(json.dumps(checkpoints, indent=2))


# ─── Existing keys ────────────────────────────────────────────────────────────

def load_existing_keys(path: Path) -> set:
    keys = set()
    if not path.exists():
        return keys
    with open(path) as f:
        for line in f:
            try:
                d = json.loads(line)
                keys.add((d["repo"], d["number"]))
            except (json.JSONDecodeError, KeyError):
                pass
    return keys


# ─── Main fetch logic ─────────────────────────────────────────────────────────

def fetch_repo_prs(repo: str, headers: dict, output_path: Path) -> int:
    existing = load_existing_keys(output_path)
    checkpoints = _load_checkpoints(output_path)
    last_known_number = checkpoints.get(repo, 0)

    url = f"{GITHUB_API}/repos/{repo}/pulls"
    # Sort by created ascending so new PRs always appear at the end.
    # We use early-stop logic (EARLY_STOP_PAGES) to skip pages we've already seen.
    params = {"state": "closed", "sort": "created", "direction": "asc"}

    if last_known_number:
        print(f"  Last saved PR: #{last_known_number} — will skip known pages")

    count = 0
    consecutive_known_pages = 0
    current_page_new = 0

    with open(output_path, "a") as f:
        for pr in paginate(url, headers, params):
            # Track page boundaries (every 100 items)
            is_page_boundary = (count + len(existing)) % 100 == 0 and count > 0
            if is_page_boundary:
                if current_page_new == 0:
                    consecutive_known_pages += 1
                else:
                    consecutive_known_pages = 0
                current_page_new = 0

                if consecutive_known_pages >= EARLY_STOP_PAGES:
                    print(f"    {EARLY_STOP_PAGES} consecutive pages of known PRs — stopping early")
                    break

            # Skip unmerged PRs (closed without merge)
            if not pr.get("merged_at"):
                continue

            # Skip noise
            if is_noise_pr(pr):
                continue

            key = (repo, pr["number"])
            if key in existing:
                continue

            # Fetch sub-resources
            comments = fetch_pr_comments(repo, pr["number"], headers)
            review_threads = fetch_review_threads(repo, pr["number"], headers)

            record = {
                "repo": repo,
                "number": pr["number"],
                "title": pr["title"].strip(),
                "body": (pr.get("body") or "").strip(),
                "merged_at": pr["merged_at"],
                "author": pr["user"]["login"],
                "labels": [lb["name"] for lb in pr.get("labels", [])],
                "comments": comments,
                "review_threads": review_threads,
            }
            f.write(json.dumps(record) + "\n")
            f.flush()
            count += 1
            current_page_new += 1
            _save_checkpoint(output_path, repo, pr["number"])

            if count % 100 == 0:
                print(f"    {count} PRs saved from {repo} ...")

    return count


# ─── Entry point ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Fetch merged Linkerd PRs + review discussions for LLM fine-tuning"
    )
    parser.add_argument(
        "--repos", nargs="+", default=DEFAULT_REPOS,
        help="GitHub repos to fetch (owner/repo format)",
    )
    parser.add_argument(
        "--output", default="data/raw_prs.jsonl",
        help="Output JSONL file path",
    )
    parser.add_argument(
        "--token", default=os.environ.get("GITHUB_TOKEN"),
        help="GitHub personal access token (or set GITHUB_TOKEN env var)",
    )
    args = parser.parse_args()

    if not args.token:
        print(
            "WARNING: No GITHUB_TOKEN found. Unauthenticated rate limit is 60 req/hr.\n"
            "         Set GITHUB_TOKEN for 5000 req/hr.\n"
        )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    headers = build_headers(args.token)
    total = 0

    for repo in args.repos:
        print(f"\nFetching merged PRs from {repo} ...")
        n = fetch_repo_prs(repo, headers, output_path)
        print(f"  Done: {n} new PRs written")
        total += n

    print(f"\nTotal new PRs written: {total}")
    print(f"Output: {output_path.resolve()}")


if __name__ == "__main__":
    main()
