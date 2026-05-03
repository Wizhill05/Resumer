"""
fetch_indeed_html.py
====================
Downloads the HTML of an Indeed job-search page using Scrapling's
StealthyFetcher (headless Camoufox browser that bypasses Cloudflare).

The raw HTML is written to:
    src/scraping/output/indeed_raw.html

Run:
    uv run src/scraping/fetch_indeed_html.py
    # or
    python src/scraping/fetch_indeed_html.py
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

TARGET_URL = (
    "https://in.indeed.com/jobs"
    "?q=ai+engineer"
    "&l=Bengaluru%2C+Karnataka"
    "&salaryType=%E2%82%B91%2C80%2C000"
    "&radius=25"
    "&sc=0kf%3Aattr%28VDTG7%29%3B"
    "&vjk=a0a97140c7bb59ec"
)

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_HTML = OUTPUT_DIR / "indeed_raw.html"
OUTPUT_META = OUTPUT_DIR / "fetch_meta.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def save_html(html: str) -> None:
    """Write the HTML content to disk."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_HTML.write_text(html, encoding="utf-8")
    print(f"[OK] HTML saved -> {OUTPUT_HTML.resolve()}")


def save_meta(url: str, status: int, fetcher_used: str, byte_size: int) -> None:
    """Write a small JSON sidecar with fetch metadata."""
    meta = {
        "url": url,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "http_status": status,
        "fetcher": fetcher_used,
        "html_bytes": byte_size,
        "html_file": str(OUTPUT_HTML.resolve()),
    }
    OUTPUT_META.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[OK] Metadata  -> {OUTPUT_META.resolve()}")
    print(json.dumps(meta, indent=2))


# ---------------------------------------------------------------------------
# Fetch logic
# ---------------------------------------------------------------------------


def fetch_with_stealthy() -> tuple[str, int]:
    """
    Primary strategy: StealthyFetcher (Camoufox headless browser).

    StealthyFetcher spoofs browser fingerprints and can solve Cloudflare
    Turnstile / interstitial challenges automatically.
    """
    from scrapling.fetchers import StealthyFetcher

    print("[*] Trying StealthyFetcher (Camoufox) ...")
    page = StealthyFetcher.fetch(
        TARGET_URL,
        headless=True,
        network_idle=True,     # Wait until network is quiet (JS rendered)
        timeout=60_000,        # 60 s timeout (ms for Playwright)
        google_search=False,   # Don't pretend to come from Google
    )
    return page.html_content, page.status


def fetch_with_dynamic() -> tuple[str, int]:
    """
    Fallback strategy: DynamicFetcher (standard Playwright Chromium).

    Less stealthy than Camoufox but useful as a fallback.
    """
    from scrapling.fetchers import DynamicFetcher

    print("[*] Falling back to DynamicFetcher (Playwright Chromium) ...")
    page = DynamicFetcher.fetch(
        TARGET_URL,
        headless=True,
        network_idle=True,
        timeout=60_000,
        disable_resources=False,
    )
    return page.html_content, page.status


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    fetcher_name = "StealthyFetcher"
    html = ""
    status = 0

    # --- Primary: StealthyFetcher ---
    try:
        html, status = fetch_with_stealthy()
        print(f"[*] HTTP status: {status}  |  HTML length: {len(html):,} chars")
    except Exception as exc:
        print(f"[!] StealthyFetcher failed: {exc}", file=sys.stderr)

        # --- Fallback: DynamicFetcher ---
        try:
            fetcher_name = "DynamicFetcher"
            html, status = fetch_with_dynamic()
            print(f"[*] HTTP status: {status}  |  HTML length: {len(html):,} chars")
        except Exception as exc2:
            print(f"[!] DynamicFetcher also failed: {exc2}", file=sys.stderr)
            sys.exit(1)

    if not html:
        print("[!] Empty HTML returned - aborting.", file=sys.stderr)
        sys.exit(1)

    # Sanity-check: Indeed should mention "Jobs" somewhere in the page
    if "jobs" not in html.lower() and "indeed" not in html.lower():
        print(
            "[!] WARNING: Response does not look like an Indeed page. "
            "Cloudflare may have blocked the request.",
            file=sys.stderr,
        )

    save_html(html)
    save_meta(TARGET_URL, status, fetcher_name, len(html.encode("utf-8")))

    print("\n[OK] Done. Open the HTML file in a browser to inspect the result.")


if __name__ == "__main__":
    main()
