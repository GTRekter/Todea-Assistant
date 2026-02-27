"""
fetch_deepwiki.py — Scrape AI-generated wiki documentation from DeepWiki for Linkerd repos.

DeepWiki produces rich, structured explanations of source code: architecture diagrams,
component tables, data flow descriptions, and error taxonomy — ideal training material.

Output format is compatible with format_training_data.py (same as raw_docs.jsonl):
    {"repo": "linkerd/linkerd2", "path": "<section-slug>", "title": "...", "content": "..."}

Usage:
    # Primary method (requests + BeautifulSoup):
    pip install requests beautifulsoup4 html2text
    python fetch_deepwiki.py

    # If pages render blank (JS-only), use Playwright:
    pip install playwright && playwright install chromium
    python fetch_deepwiki.py --playwright

    python fetch_deepwiki.py --output data/raw_deepwiki.jsonl
"""

import argparse
import json
import time
from pathlib import Path

import html2text
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://deepwiki.com"

# Complete page inventory (discovered from sidebar navigation, Feb 2026)
PAGES: dict[str, list[str]] = {
    "linkerd/linkerd2": [
        "1-linkerd2-overview",
        "2-architecture",
        "2.1-control-plane",
        "2.2-data-plane",
        "2.3-service-discovery",
        "2.4-policy-system",
        "3-components",
        "3.1-cli-tool",
        "3.2-web-dashboard",
        "3.3-policy-controller",
        "3.4-health-checker",
        "4-deployment",
        "4.1-installation",
        "4.2-helm-charts",
        "4.3-proxy-injection",
        "5-extensions",
        "5.1-viz-extension",
        "5.2-multicluster",
        "6-development",
        "6.1-build-process",
        "6.2-testing",
        "6.3-cicd-pipeline",
    ],
    "linkerd/linkerd2-proxy": [
        "1-overview",
        "1.1-architecture",
        "2-inbound-proxy",
        "2.1-connection-acceptance-and-protocol-detection",
        "3.1-service-discovery-and-routing",
        "3.2-load-balancing-and-retry",
        "3.3-sidecar-and-gateway-modes",
        "4-transport-layer",
        "5-observability",
        "5.1-error-handling-and-classification",
        "6-configuration",
        "7-development",
        "7.1-build-system",
        "7.2-testing-and-fuzzing",
        "7.3-cicd-pipeline",
    ],
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

MIN_CONTENT_LEN = 300   # if extracted text is shorter, assume JS rendering failed
POLITE_DELAY = 1.5      # seconds between requests


# ─── HTML → Markdown extraction ───────────────────────────────────────────────

def _make_converter() -> html2text.HTML2Text:
    h = html2text.HTML2Text()
    h.ignore_links = False
    h.ignore_images = True
    h.ignore_emphasis = False
    h.body_width = 0          # don't wrap lines
    h.unicode_snob = True
    return h


_converter = _make_converter()


def _find_main_content(soup: BeautifulSoup) -> str:
    """Extract the main article content from the page HTML."""
    # Try semantic containers first
    for selector in (
        "article",
        "main",
        "[role='main']",
        "div.prose",
        "div[class*='article']",
        "div[class*='content']",
        "div[class*='wiki']",
        "div[class*='page']",
    ):
        el = soup.select_one(selector)
        if el:
            # Remove navigation sidebars embedded inside main
            for nav in el.select("nav, aside, [role='navigation'], [class*='sidebar']"):
                nav.decompose()
            return _converter.handle(str(el)).strip()

    # Last resort: full body minus nav/header/footer
    body = soup.find("body")
    if body:
        for tag in body.select("nav, header, footer, aside, script, style"):
            tag.decompose()
        return _converter.handle(str(body)).strip()

    return ""


def _extract_title(soup: BeautifulSoup) -> str:
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(strip=True)
    title = soup.find("title")
    if title:
        return title.get_text(strip=True).split("|")[0].strip()
    return ""


# ─── Fetching strategies ──────────────────────────────────────────────────────

def fetch_with_requests(url: str) -> tuple[str, str]:
    """Return (title, content) using requests + BeautifulSoup. May fail on SPA pages."""
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    return _extract_title(soup), _find_main_content(soup)


def fetch_with_playwright(url: str) -> tuple[str, str]:
    """Return (title, content) using Playwright (headless Chromium). Handles JS rendering."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, wait_until="networkidle", timeout=30_000)
        # Wait for main content to appear
        try:
            page.wait_for_selector("article, main, h1", timeout=10_000)
        except Exception:
            pass
        html = page.content()
        browser.close()

    soup = BeautifulSoup(html, "html.parser")
    return _extract_title(soup), _find_main_content(soup)


# ─── Main logic ───────────────────────────────────────────────────────────────

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


def fetch_all(output_path: Path, use_playwright: bool) -> None:
    existing = load_existing_keys(output_path)
    total = sum(len(pages) for pages in PAGES.values())
    done = 0

    with open(output_path, "a") as fout:
        for repo, slugs in PAGES.items():
            for slug in slugs:
                done += 1
                key = (repo, slug)
                if key in existing:
                    print(f"  [{done}/{total}] Skip (cached): {repo}/{slug}")
                    continue

                url = f"{BASE_URL}/{repo}/{slug}"
                print(f"  [{done}/{total}] Fetching: {url}")

                try:
                    if use_playwright:
                        title, content = fetch_with_playwright(url)
                    else:
                        title, content = fetch_with_requests(url)

                    if len(content) < MIN_CONTENT_LEN:
                        print(
                            f"    WARNING: content too short ({len(content)} chars). "
                            "Page may need JS rendering. Try --playwright."
                        )
                        if not use_playwright:
                            # Still save what we got, can re-fetch later
                            pass

                    record = {
                        "repo": repo,
                        "path": slug,
                        "title": title,
                        "content": content,
                    }
                    fout.write(json.dumps(record) + "\n")
                    fout.flush()

                except Exception as e:
                    print(f"    ERROR fetching {url}: {e}")

                time.sleep(POLITE_DELAY)

    print(f"\nOutput: {output_path.resolve()}")


def main():
    parser = argparse.ArgumentParser(
        description="Scrape DeepWiki documentation for Linkerd repos"
    )
    parser.add_argument("--output", default="data/raw_deepwiki.jsonl")
    parser.add_argument(
        "--playwright", action="store_true",
        help="Use headless Chromium via Playwright (needed if pages are JS-rendered). "
             "Install with: pip install playwright && playwright install chromium",
    )
    args = parser.parse_args()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if args.playwright:
        try:
            import playwright  # noqa: F401
        except ImportError:
            print("ERROR: Playwright not installed.")
            print("  pip install playwright && playwright install chromium")
            raise SystemExit(1)

    fetch_all(output_path, args.playwright)


if __name__ == "__main__":
    main()
