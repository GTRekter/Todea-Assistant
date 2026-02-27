"""
fetch_issues.py — Download all issues + comments from Linkerd GitHub repos.

Usage:
    export GITHUB_TOKEN=ghp_...
    python fetch_issues.py
    python fetch_issues.py --repos linkerd/linkerd2 --output data/raw_issues.jsonl

Output: JSONL file, one issue per line with embedded comments.
The script is resumable — already-fetched issues are skipped on re-run.
"""

import argparse
import json
import os
import time
from pathlib import Path

import requests

DEFAULT_REPOS = ["linkerd/linkerd2"]
GITHUB_API = "https://api.github.com"


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
                wait = 2 ** attempt  # 1, 2, 4, 8, 16, 32 s
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


def fetch_comments(repo: str, issue_number: int, headers: dict) -> list:
    url = f"{GITHUB_API}/repos/{repo}/issues/{issue_number}/comments"
    try:
        return list(paginate(url, headers))
    except requests.exceptions.RequestException as e:
        print(f"    Warning: could not fetch comments for #{issue_number}: {e}")
        return []


def load_existing_keys(path: Path) -> set:
    """Return set of (repo, number) tuples already saved in the output file."""
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


# ─── Checkpoint helpers ───────────────────────────────────────────────────────
# The checkpoint file stores the `created_at` of the last saved issue per repo.
# On re-run we pass it as `since=` to the GitHub API so it skips already-fetched
# pages server-side instead of paginating from page 1 every time.
#
# Note: GitHub's `since` filters by `updated_at`, not `created_at`.  Using the
# last `created_at` as the cutoff means we may re-fetch a few recently-updated
# old issues, but those are already in `existing` and get skipped instantly.

def _checkpoint_path(output_path: Path) -> Path:
    return output_path.parent / ".checkpoint.json"


def _load_checkpoints(output_path: Path) -> dict:
    cp = _checkpoint_path(output_path)
    if cp.exists():
        try:
            return json.loads(cp.read_text())
        except (json.JSONDecodeError, OSError):
            pass

    # No checkpoint file yet — bootstrap from the existing JSONL output.
    # Find the latest `created_at` per repo so we can resume without re-reading
    # thousands of pages from GitHub.
    if not output_path.exists():
        return {}

    print("  No checkpoint found — building from saved data (one-time scan) ...")
    latest: dict[str, str] = {}
    with open(output_path) as f:
        for line in f:
            try:
                d = json.loads(line)
                repo = d["repo"]
                ts = d.get("created_at", "")
                if ts > latest.get(repo, ""):
                    latest[repo] = ts
            except (json.JSONDecodeError, KeyError):
                pass

    if latest:
        cp.write_text(json.dumps(latest, indent=2))
        print(f"  Checkpoint bootstrapped: {latest}")

    return latest


def _save_checkpoint(output_path: Path, repo: str, created_at: str) -> None:
    cp = _checkpoint_path(output_path)
    checkpoints = _load_checkpoints(output_path)
    checkpoints[repo] = created_at
    cp.write_text(json.dumps(checkpoints, indent=2))


# ─────────────────────────────────────────────────────────────────────────────

def fetch_repo_issues(repo: str, headers: dict, output_path: Path) -> int:
    existing = load_existing_keys(output_path)
    checkpoints = _load_checkpoints(output_path)
    since = checkpoints.get(repo)

    url = f"{GITHUB_API}/repos/{repo}/issues"
    params = {"state": "all", "sort": "created", "direction": "asc"}
    if since:
        params["since"] = since
        print(f"  Resuming from checkpoint: {since}  (skipping already-fetched pages)")

    last_created_at = since
    count = 0

    with open(output_path, "a") as f:
        for issue in paginate(url, headers, params):
            # The issues endpoint also returns PRs — skip them
            if issue.get("pull_request"):
                continue

            key = (repo, issue["number"])
            if key in existing:
                continue

            comments = fetch_comments(repo, issue["number"], headers)

            record = {
                "repo": repo,
                "number": issue["number"],
                "title": issue["title"].strip(),
                "body": (issue.get("body") or "").strip(),
                "state": issue["state"],
                "labels": [lb["name"] for lb in issue.get("labels", [])],
                "author": issue["user"]["login"],
                "created_at": issue["created_at"],
                "closed_at": issue.get("closed_at"),
                "comments": [
                    {
                        "author": c["user"]["login"],
                        "body": (c["body"] or "").strip(),
                        "created_at": c["created_at"],
                    }
                    for c in comments
                ],
            }
            f.write(json.dumps(record) + "\n")
            f.flush()
            count += 1
            last_created_at = issue["created_at"]

            if count % 100 == 0:
                # Save progress so a crash mid-run still preserves the position
                _save_checkpoint(output_path, repo, last_created_at)
                print(f"    {count} issues saved from {repo} ...")

    if last_created_at:
        _save_checkpoint(output_path, repo, last_created_at)

    return count


def main():
    parser = argparse.ArgumentParser(
        description="Fetch Linkerd GitHub issues + comments for LLM fine-tuning"
    )
    parser.add_argument(
        "--repos", nargs="+", default=DEFAULT_REPOS,
        help="GitHub repos to fetch (owner/repo format)",
    )
    parser.add_argument(
        "--output", default="data/raw_issues.jsonl",
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
        print(f"\nFetching issues from {repo} ...")
        n = fetch_repo_issues(repo, headers, output_path)
        print(f"  Done: {n} new issues written")
        total += n

    print(f"\nTotal new issues written: {total}")
    print(f"Output: {output_path.resolve()}")


if __name__ == "__main__":
    main()
