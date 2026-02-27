"""
fetch_website_docs.py — Scrape official Linkerd documentation websites.

Sources:
  linkerd.io    — canonical "how to use Linkerd": features, tasks, reference,
                  common errors (/2/ stable + /2-edge/ preview docs)
  docs.buoyant.io — enterprise Linkerd (HAZL, FIPS, lifecycle automation, etc.)
                    and Buoyant Cloud docs

URL discovery uses each site's sitemap.xml so the list stays current without
hardcoding individual pages.

Output format (compatible with format_training_data.py / doc_to_pairs):
    {"site": "linkerd.io", "path": "/2/tasks/...", "title": "...", "content": "..."}

Usage:
    python fetch_website_docs.py
    python fetch_website_docs.py --output data/raw_website_docs.jsonl
    python fetch_website_docs.py --sites linkerd.io          # one site only
    python fetch_website_docs.py --playwright                # JS-rendered fallback
"""

import argparse
import json
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlparse

import html2text
import requests
from bs4 import BeautifulSoup

# ─── Site configuration ───────────────────────────────────────────────────────

SITES: dict[str, dict] = {
    "linkerd.io": {
        "sitemap": "https://linkerd.io/sitemap.xml",
        # Only scrape documentation paths — exclude blog, community, faq, etc.
        "include_prefixes": (
            "/2/",
            "/2-edge/",
        ),
        "exclude_prefixes": (),
    },
    "docs.buoyant.io": {
        "sitemap": "https://docs.buoyant.io/sitemap.xml",
        "include_prefixes": (
            "/buoyant-enterprise-linkerd/",
            "/buoyant-cloud/",
            "/linkerd-dashboard/",
            "/security/advisories/",
        ),
        # Release notes are mostly version strings and changelogs — low signal
        "exclude_prefixes": (
            "/release-notes/",
        ),
    },
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

POLITE_DELAY = 0.8        # seconds between page fetches
MIN_CONTENT_LEN = 200     # skip pages with very little extracted text
MAX_RETRIES = 4


# ─── Sitemap parsing ──────────────────────────────────────────────────────────

# XML namespaces used by sitemaps
_NS = {
    "sm":  "http://www.sitemaps.org/schemas/sitemap/0.9",
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
}


def _fetch_text(url: str, timeout: int = 20) -> str | None:
    """GET a URL with retries, return text or None on failure."""
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=timeout)
            resp.raise_for_status()
            return resp.text
        except (requests.exceptions.ConnectionError,
                requests.exceptions.Timeout) as e:
            if attempt == MAX_RETRIES - 1:
                print(f"    Error fetching {url}: {e}")
                return None
            time.sleep(2 ** attempt)
        except requests.exceptions.HTTPError as e:
            print(f"    HTTP error fetching {url}: {e}")
            return None
    return None


def _parse_sitemap(url: str) -> list[str]:
    """
    Recursively parse a sitemap or sitemap-index and return all <loc> URLs.
    Handles both <urlset> (regular) and <sitemapindex> (index) formats.
    """
    text = _fetch_text(url)
    if not text:
        return []

    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        print(f"    XML parse error for {url}: {e}")
        return []

    # Strip namespace for easier tag matching
    tag = root.tag.split("}")[-1] if "}" in root.tag else root.tag

    if tag == "sitemapindex":
        # Index pointing to child sitemaps — recurse
        urls = []
        for sitemap_el in root.findall("sm:sitemap", _NS) or root.findall("sitemap"):
            loc_el = sitemap_el.find("sm:loc", _NS)
            if loc_el is None:
                loc_el = sitemap_el.find("loc")
            if loc_el is not None and loc_el.text:
                urls.extend(_parse_sitemap(loc_el.text.strip()))
        return urls
    else:
        # Regular urlset
        urls = []
        for url_el in root.findall("sm:url", _NS) or root.findall("url"):
            loc_el = url_el.find("sm:loc", _NS)
            if loc_el is None:
                loc_el = url_el.find("loc")
            if loc_el is not None and loc_el.text:
                urls.append(loc_el.text.strip())
        return urls


def discover_urls(site_name: str, config: dict) -> list[str]:
    """Return all doc page URLs for a site, filtered by include/exclude prefixes."""
    print(f"  Fetching sitemap: {config['sitemap']}")
    all_urls = _parse_sitemap(config["sitemap"])
    print(f"  Total URLs in sitemap: {len(all_urls)}")

    include = config.get("include_prefixes", ())
    exclude = config.get("exclude_prefixes", ())

    filtered = []
    for url in all_urls:
        path = urlparse(url).path
        if include and not any(path.startswith(p) for p in include):
            continue
        if any(path.startswith(p) for p in exclude):
            continue
        filtered.append(url)

    print(f"  After filtering: {len(filtered)} doc pages")
    return filtered


# ─── HTML → Markdown extraction ───────────────────────────────────────────────

def _make_converter() -> html2text.HTML2Text:
    h = html2text.HTML2Text()
    h.ignore_links = False
    h.ignore_images = True
    h.body_width = 0
    h.unicode_snob = True
    return h


_converter = _make_converter()

# Ordered list of CSS selectors to try for main content
_CONTENT_SELECTORS = (
    "article.td-page-content",   # Docsy theme (used by linkerd.io)
    ".td-content",               # Docsy
    "article",
    "main",
    "[role='main']",
    ".content",
    ".article-body",
    ".doc-content",
    "div[class*='content']",
)

# Elements to remove before extraction (nav, sidebars, footers, etc.)
_REMOVE_SELECTORS = (
    "nav", "header", "footer", "aside",
    "[role='navigation']", "[role='banner']", "[role='complementary']",
    ".td-sidebar", ".td-toc", ".td-page-meta",
    "[class*='sidebar']", "[class*='toc']", "[class*='breadcrumb']",
    "[class*='nav']", "[class*='menu']",
    "script", "style",
)


def extract_content(html: str) -> tuple[str, str]:
    """Return (title, markdown_content) from raw HTML."""
    soup = BeautifulSoup(html, "html.parser")

    # Extract title
    title = ""
    h1 = soup.find("h1")
    if h1:
        title = h1.get_text(strip=True)
    elif soup.title:
        title = soup.title.get_text(strip=True).split("|")[0].split("–")[0].strip()

    # Find main content container
    content_el = None
    for selector in _CONTENT_SELECTORS:
        content_el = soup.select_one(selector)
        if content_el:
            break
    if not content_el:
        content_el = soup.find("body")
    if not content_el:
        return title, ""

    # Remove noise elements
    for sel in _REMOVE_SELECTORS:
        for el in content_el.select(sel):
            el.decompose()

    markdown = _converter.handle(str(content_el)).strip()
    return title, markdown


# ─── Playwright fallback ──────────────────────────────────────────────────────

def fetch_with_playwright(url: str) -> tuple[str, str]:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, wait_until="networkidle", timeout=30_000)
        try:
            page.wait_for_selector("article, main, h1", timeout=10_000)
        except Exception:
            pass
        html = page.content()
        browser.close()
    return extract_content(html)


# ─── Checkpoint ───────────────────────────────────────────────────────────────

def _checkpoint_path(output_path: Path) -> Path:
    return output_path.parent / ".website_checkpoint.json"


def _load_done_urls(output_path: Path) -> set[str]:
    """Return set of URLs already saved (from checkpoint + output file scan)."""
    done: set[str] = set()

    cp = _checkpoint_path(output_path)
    if cp.exists():
        try:
            data = json.loads(cp.read_text())
            done.update(data.get("done", []))
            return done
        except (json.JSONDecodeError, OSError):
            pass

    # Bootstrap from output file
    if output_path.exists():
        print("  No checkpoint — bootstrapping from saved data (one-time scan) ...")
        with open(output_path) as f:
            for line in f:
                try:
                    d = json.loads(line)
                    if "url" in d:
                        done.add(d["url"])
                except (json.JSONDecodeError, KeyError):
                    pass
        _save_done_urls(output_path, done)

    return done


def _save_done_urls(output_path: Path, done: set[str]) -> None:
    cp = _checkpoint_path(output_path)
    cp.write_text(json.dumps({"done": sorted(done)}, indent=2))


# ─── Main fetch logic ─────────────────────────────────────────────────────────

def fetch_site(
    site_name: str,
    config: dict,
    output_path: Path,
    use_playwright: bool,
    done_urls: set[str],
) -> int:
    urls = discover_urls(site_name, config)
    pending = [u for u in urls if u not in done_urls]
    print(f"  {len(pending)} pages to fetch ({len(urls) - len(pending)} already done)")

    count = 0
    with open(output_path, "a") as f:
        for i, url in enumerate(pending, 1):
            try:
                if use_playwright:
                    title, content = fetch_with_playwright(url)
                else:
                    html = _fetch_text(url)
                    if not html:
                        continue
                    title, content = extract_content(html)

                if len(content) < MIN_CONTENT_LEN:
                    print(f"    [{i}/{len(pending)}] Skip (thin content, {len(content)} chars): {url}")
                    # Still mark as done so we don't retry indefinitely
                    done_urls.add(url)
                    continue

                path = urlparse(url).path.rstrip("/")
                record = {
                    # Use "repo"/"path" keys for compatibility with doc_to_pairs()
                    "repo": site_name,
                    "path": path,
                    "url": url,
                    "title": title,
                    "content": content,
                }
                f.write(json.dumps(record) + "\n")
                f.flush()
                done_urls.add(url)
                count += 1

                if count % 20 == 0:
                    _save_done_urls(output_path, done_urls)
                    print(f"    [{i}/{len(pending)}] {count} pages saved from {site_name}")

            except Exception as e:
                print(f"    Error on {url}: {e}")

            time.sleep(POLITE_DELAY)

    _save_done_urls(output_path, done_urls)
    return count


# ─── Entry point ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Scrape official Linkerd docs websites for LLM fine-tuning"
    )
    parser.add_argument(
        "--sites", nargs="+", default=list(SITES.keys()),
        choices=list(SITES.keys()),
        help="Which sites to scrape (default: all)",
    )
    parser.add_argument(
        "--output", default="data/raw_website_docs.jsonl",
    )
    parser.add_argument(
        "--playwright", action="store_true",
        help="Use headless Chromium (needed if pages are JS-rendered). "
             "Install: pip install playwright && playwright install chromium",
    )
    args = parser.parse_args()

    if args.playwright:
        try:
            import playwright  # noqa: F401
        except ImportError:
            print("ERROR: pip install playwright && playwright install chromium")
            raise SystemExit(1)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    done_urls = _load_done_urls(output_path)
    total = 0

    for site_name in args.sites:
        config = SITES[site_name]
        print(f"\nScraping {site_name} ...")
        n = fetch_site(site_name, config, output_path, args.playwright, done_urls)
        print(f"  Done: {n} new pages written")
        total += n

    print(f"\nTotal new pages written: {total}")
    print(f"Output: {output_path.resolve()}")


if __name__ == "__main__":
    main()
