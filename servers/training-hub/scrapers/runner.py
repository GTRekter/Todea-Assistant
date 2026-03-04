"""
runner.py — Orchestrate all data-scraping scripts for the Todea training pipeline.

Called by the training-hub as a Kubernetes Job:
    python scrapers/runner.py --repos=linkerd/linkerd2,linkerd/linkerd2-proxy \
                              --websites=linkerd.io,docs.buoyant.io,deepwiki

Steps:
  1. Fetch GitHub docs, issues, and PRs for each requested repo
  2. Scrape website docs (linkerd.io / docs.buoyant.io)
  3. Scrape DeepWiki (if requested)
  4. Format all raw data into /data/training_data.jsonl
"""

import argparse
import subprocess
import sys
from pathlib import Path

DATA_DIR = Path("/data")

GITHUB_SCRAPERS = [
    ("scrapers/docs.py",          DATA_DIR / "raw_docs.jsonl"),
    ("scrapers/issues.py",        DATA_DIR / "raw_issues.jsonl"),
    ("scrapers/pull_requests.py", DATA_DIR / "raw_prs.jsonl"),
]

WEBSITE_SITES = {"linkerd.io", "docs.buoyant.io"}


def run(cmd: list) -> None:
    print(f"\n>>> {' '.join(str(c) for c in cmd)}", flush=True)
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        print(f"WARNING: {cmd[1]} exited with code {result.returncode}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Orchestrate Todea training scrapers")
    parser.add_argument(
        "--repos", default="",
        help="Comma-separated GitHub repos (owner/repo)",
    )
    parser.add_argument(
        "--websites", default="",
        help="Comma-separated site ids: linkerd.io, docs.buoyant.io, deepwiki",
    )
    args = parser.parse_args()

    repos    = [r.strip() for r in args.repos.split(",")    if r.strip()]
    websites = [w.strip() for w in args.websites.split(",") if w.strip()]

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # ── GitHub scrapers ────────────────────────────────────────────────────────
    if repos:
        for script, output in GITHUB_SCRAPERS:
            run([sys.executable, script, "--repos", *repos, f"--output={output}"])
    else:
        print("No repos specified — skipping GitHub scrapers", flush=True)

    # ── Website scrapers ───────────────────────────────────────────────────────
    web_sites = [w for w in websites if w in WEBSITE_SITES]
    if web_sites:
        run([
            sys.executable, "scrapers/website_docs.py",
            "--sites", *web_sites,
            f"--output={DATA_DIR / 'raw_website_docs.jsonl'}",
        ])

    if "deepwiki" in websites:
        run([
            sys.executable, "scrapers/deepwiki.py",
            f"--output={DATA_DIR / 'raw_deepwiki.jsonl'}",
        ])

    # ── Format all raw data into training pairs ────────────────────────────────
    run([
        sys.executable, "scrapers/format_data.py",
        f"--issues={DATA_DIR / 'raw_issues.jsonl'}",
        f"--prs={DATA_DIR / 'raw_prs.jsonl'}",
        f"--docs={DATA_DIR / 'raw_docs.jsonl'}",
        f"--websites={DATA_DIR / 'raw_website_docs.jsonl'}",
        f"--deepwiki={DATA_DIR / 'raw_deepwiki.jsonl'}",
        f"--output={DATA_DIR / 'training_data.jsonl'}",
    ])

    print("\nScraping pipeline complete.", flush=True)


if __name__ == "__main__":
    main()
