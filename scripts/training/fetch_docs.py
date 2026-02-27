"""
fetch_docs.py — Download Markdown documentation from Linkerd GitHub repos.

Uses the GitHub Git Trees API to list all .md files recursively, then
fetches only the ones inside doc-relevant directories.

Usage:
    export GITHUB_TOKEN=ghp_...
    python fetch_docs.py
    python fetch_docs.py --output data/raw_docs.jsonl

Output: JSONL file, one doc per line:
    {"repo": "linkerd/linkerd2", "path": "doc/...", "content": "..."}
"""

import argparse
import base64
import json
import os
import time
from pathlib import Path

import requests

DEFAULT_REPOS = ["linkerd/linkerd2", "linkerd/linkerd2-proxy"]
GITHUB_API = "https://api.github.com"

# Only include markdown files under these path prefixes (case-insensitive)
INCLUDE_PREFIXES = (
    "doc",
    "docs",
    "design",
    "rfcs",
    "rfc",
    "readme",
    "CHANGELOG",
    "ARCHITECTURE",
    "CONTRIBUTING",
)

# Skip generated / boilerplate files
EXCLUDE_SUBSTRINGS = (
    "vendor/",
    "node_modules/",
    "testdata/",
    ".github/",
)

MAX_FILE_BYTES = 200_000  # skip very large files (auto-generated, etc.)


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


def get_default_branch(repo: str, headers: dict) -> str:
    resp = requests.get(f"{GITHUB_API}/repos/{repo}", headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json().get("default_branch", "main")


def list_markdown_files(repo: str, branch: str, headers: dict) -> list[dict]:
    """Return list of {path, sha, size} for all .md files in the repo tree."""
    url = f"{GITHUB_API}/repos/{repo}/git/trees/{branch}?recursive=1"
    resp = requests.get(url, headers=headers, timeout=60)
    resp.raise_for_status()
    wait_for_rate_limit(resp)

    tree = resp.json().get("tree", [])
    results = []
    for item in tree:
        if item.get("type") != "blob":
            continue
        path: str = item["path"]
        if not path.lower().endswith(".md"):
            continue
        if any(excl in path for excl in EXCLUDE_SUBSTRINGS):
            continue
        path_lower = path.lower()
        # Accept if path starts with one of our include prefixes OR is a top-level README/CHANGELOG
        if any(
            path_lower.startswith(pfx.lower()) or path_lower == pfx.lower() + ".md"
            for pfx in INCLUDE_PREFIXES
        ):
            results.append({"path": path, "sha": item["sha"], "size": item.get("size", 0)})
    return results


def fetch_blob_content(repo: str, sha: str, headers: dict) -> str | None:
    url = f"{GITHUB_API}/repos/{repo}/git/blobs/{sha}"
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    wait_for_rate_limit(resp)
    blob = resp.json()
    encoding = blob.get("encoding")
    content = blob.get("content", "")
    if encoding == "base64":
        return base64.b64decode(content).decode("utf-8", errors="replace")
    return content


def load_existing_keys(path: Path) -> set:
    keys = set()
    if not path.exists():
        return keys
    with open(path) as f:
        for line in f:
            try:
                d = json.loads(line)
                keys.add((d["repo"], d["path"]))
            except (json.JSONDecodeError, KeyError):
                pass
    return keys


def fetch_repo_docs(repo: str, headers: dict, output_path: Path) -> int:
    existing = load_existing_keys(output_path)

    branch = get_default_branch(repo, headers)
    print(f"  Default branch: {branch}")

    files = list_markdown_files(repo, branch, headers)
    print(f"  Found {len(files)} relevant markdown files")

    count = 0
    with open(output_path, "a") as f:
        for item in files:
            key = (repo, item["path"])
            if key in existing:
                continue
            if item["size"] > MAX_FILE_BYTES:
                print(f"  Skipping {item['path']} (too large: {item['size']} bytes)")
                continue

            content = fetch_blob_content(repo, item["sha"], headers)
            if not content or len(content.strip()) < 100:
                continue

            record = {
                "repo": repo,
                "path": item["path"],
                "content": content.strip(),
            }
            f.write(json.dumps(record) + "\n")
            f.flush()
            count += 1

    return count


def main():
    parser = argparse.ArgumentParser(
        description="Fetch Linkerd markdown docs from GitHub for LLM fine-tuning"
    )
    parser.add_argument("--repos", nargs="+", default=DEFAULT_REPOS)
    parser.add_argument("--output", default="data/raw_docs.jsonl")
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN"))
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
        print(f"\nFetching docs from {repo} ...")
        n = fetch_repo_docs(repo, headers, output_path)
        print(f"  Done: {n} new docs written")
        total += n

    print(f"\nTotal new docs written: {total}")
    print(f"Output: {output_path.resolve()}")


if __name__ == "__main__":
    main()
