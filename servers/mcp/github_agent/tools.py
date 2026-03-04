from __future__ import annotations

import base64
import json
import os
from typing import Optional

import httpx

GITHUB_API = "https://api.github.com"
TIMEOUT = 20  # seconds


def _headers() -> dict[str, str]:
    token = os.getenv("GITHUB_TOKEN", "")
    h = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _get(url: str, params: Optional[dict] = None) -> dict | list:
    """Execute a GET request and return parsed JSON, or an error dict."""
    try:
        r = httpx.get(url, headers=_headers(), params=params, timeout=TIMEOUT)
        if r.status_code == 403:
            remaining = r.headers.get("X-RateLimit-Remaining", "?")
            return {"error": f"GitHub API rate limit hit (remaining: {remaining}). Set GITHUB_TOKEN to raise the limit."}
        if r.status_code == 404:
            return {"error": f"Not found: {url}"}
        r.raise_for_status()
        return r.json()
    except httpx.TimeoutException:
        return {"error": f"Request timed out after {TIMEOUT}s: {url}"}
    except httpx.HTTPStatusError as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# File retrieval
# ---------------------------------------------------------------------------

def github_get_file(repo: str, path: str, ref: str = "HEAD") -> str:
    """
    Fetch the raw text content of a file from a public GitHub repository.

    repo: owner/repo (e.g. 'linkerd/linkerd2').
    path: file path within the repo (e.g. 'pkg/identity/service.go').
    ref: branch, tag, or commit SHA (default: HEAD).
    """
    data = _get(f"{GITHUB_API}/repos/{repo}/contents/{path}", params={"ref": ref})
    if isinstance(data, dict) and "error" in data:
        return json.dumps(data, indent=2)
    if isinstance(data, list):
        return json.dumps({"error": f"'{path}' is a directory. Use github_list_directory instead."}, indent=2)
    encoding = data.get("encoding", "")
    content_raw = data.get("content", "")
    if encoding == "base64":
        try:
            return base64.b64decode(content_raw).decode("utf-8", errors="replace")
        except Exception as e:
            return json.dumps({"error": f"Failed to decode file content: {e}"}, indent=2)
    return content_raw


# ---------------------------------------------------------------------------
# Directory listing
# ---------------------------------------------------------------------------

def github_list_directory(repo: str, path: str = "", ref: str = "HEAD") -> str:
    """
    List the contents of a directory in a public GitHub repository.

    repo: owner/repo (e.g. 'linkerd/linkerd2').
    path: directory path within the repo. Empty string lists the repo root.
    ref: branch, tag, or commit SHA (default: HEAD).
    """
    url = f"{GITHUB_API}/repos/{repo}/contents/{path}" if path else f"{GITHUB_API}/repos/{repo}/contents"
    data = _get(url, params={"ref": ref})
    if isinstance(data, dict) and "error" in data:
        return json.dumps(data, indent=2)
    if isinstance(data, dict):
        return json.dumps({"error": f"'{path}' is a file. Use github_get_file instead."}, indent=2)
    entries = [
        {"name": e["name"], "type": e["type"], "path": e["path"], "size": e.get("size", 0)}
        for e in data
    ]
    return json.dumps(entries, indent=2)


# ---------------------------------------------------------------------------
# Code search
# ---------------------------------------------------------------------------

def github_search_code(repo: str, query: str) -> str:
    """
    Search for code within a public GitHub repository.

    repo: owner/repo (e.g. 'linkerd/linkerd2').
    query: search terms (e.g. 'IdentityService', 'CrashLoopBackOff handler').
    """
    data = _get(
        f"{GITHUB_API}/search/code",
        params={"q": f"{query} repo:{repo}", "per_page": 10},
    )
    if isinstance(data, dict) and "error" in data:
        return json.dumps(data, indent=2)
    items = data.get("items", [])
    results = []
    for item in items:
        result = {
            "path": item.get("path"),
            "score": item.get("score"),
            "url": item.get("html_url"),
        }
        matches = item.get("text_matches", [])
        if matches:
            result["matches"] = [m.get("fragment", "") for m in matches]
        results.append(result)
    return json.dumps({"total": data.get("total_count", 0), "results": results}, indent=2)


# ---------------------------------------------------------------------------
# Issue retrieval
# ---------------------------------------------------------------------------

def github_get_issue(repo: str, number: int) -> str:
    """
    Fetch a GitHub issue including its comments.

    repo: owner/repo (e.g. 'linkerd/linkerd2').
    number: issue number.
    """
    issue = _get(f"{GITHUB_API}/repos/{repo}/issues/{number}")
    if isinstance(issue, dict) and "error" in issue:
        return json.dumps(issue, indent=2)

    comments_raw = _get(f"{GITHUB_API}/repos/{repo}/issues/{number}/comments")
    comments = []
    if isinstance(comments_raw, list):
        comments = [
            {"author": c["user"]["login"], "body": c["body"], "created_at": c["created_at"]}
            for c in comments_raw
        ]

    return json.dumps({
        "number": issue.get("number"),
        "title": issue.get("title"),
        "state": issue.get("state"),
        "author": issue.get("user", {}).get("login"),
        "created_at": issue.get("created_at"),
        "labels": [l["name"] for l in issue.get("labels", [])],
        "body": issue.get("body", ""),
        "comments": comments,
    }, indent=2)


# ---------------------------------------------------------------------------
# Pull request retrieval
# ---------------------------------------------------------------------------

def github_get_pr(repo: str, number: int) -> str:
    """
    Fetch a GitHub pull request including changed files.

    repo: owner/repo (e.g. 'linkerd/linkerd2').
    number: pull request number.
    """
    pr = _get(f"{GITHUB_API}/repos/{repo}/pulls/{number}")
    if isinstance(pr, dict) and "error" in pr:
        return json.dumps(pr, indent=2)

    files_raw = _get(f"{GITHUB_API}/repos/{repo}/pulls/{number}/files")
    files = []
    if isinstance(files_raw, list):
        files = [
            {"filename": f["filename"], "status": f["status"], "additions": f["additions"], "deletions": f["deletions"]}
            for f in files_raw
        ]

    return json.dumps({
        "number": pr.get("number"),
        "title": pr.get("title"),
        "state": pr.get("state"),
        "author": pr.get("user", {}).get("login"),
        "created_at": pr.get("created_at"),
        "merged": pr.get("merged", False),
        "base": pr.get("base", {}).get("ref"),
        "head": pr.get("head", {}).get("ref"),
        "body": pr.get("body", ""),
        "changed_files": files,
    }, indent=2)
