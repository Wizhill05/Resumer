"""
debug_viewjob.py — Raw debug dump for a single Indeed viewjob page.

Usage:
    uv run python debug_viewjob.py 2>&1 | Out-File -Encoding utf8 viewjob_debug.txt; Get-Content viewjob_debug.txt
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

TARGET_URL = "https://in.indeed.com/viewjob?jk=9abc96f629374319"

DIVIDER = "=" * 80
THIN = "-" * 60


def main() -> None:
    url = sys.argv[1] if len(sys.argv) > 1 else TARGET_URL

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("ERROR: Playwright not installed.", file=sys.stderr)
        sys.exit(1)

    print(DIVIDER)
    print(f"TARGET: {url}")
    print(DIVIDER)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1440, "height": 900},
            locale="en-IN",
        )
        page = context.new_page()

        print("\n[1] Navigating...")
        page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_timeout(3_000)

        # ── Basic info ────────────────────────────────────────────────────
        print(f"\n[2] FINAL URL: {page.url}")
        print(f"\n[3] PAGE TITLE: {page.title()}")

        # ── Try description selectors ─────────────────────────────────────
        print(f"\n[4] DESCRIPTION SELECTOR TESTS:")
        desc_selectors = [
            "#jobDescriptionText",
            "[data-testid='jobDescriptionText']",
            ".jobsearch-jobDescriptionText",
            "[id*='jobDescription']",
            "[class*='jobDescription']",
            "[class*='description']",
            ".job-description",
            "[data-testid='job-description']",
        ]
        for sel in desc_selectors:
            el = page.query_selector(sel)
            if el:
                txt = el.inner_text().strip()[:200].replace("\n", " ")
                print(f"  FOUND  [{sel}] => '{txt}'")
            else:
                print(f"  MISS   [{sel}]")

        # ── Check _initialData keys ───────────────────────────────────────
        print(f"\n[5] window._initialData top-level keys:")
        keys = page.evaluate("""
            () => {
                if (!window._initialData) return ['_initialData NOT FOUND'];
                return Object.keys(window._initialData);
            }
        """)
        for k in keys:
            print(f"  - {k}")

        # ── Try to get description from _initialData ──────────────────────
        print(f"\n[6] Description from _initialData paths:")

        paths_to_try = [
            # viewjob page structure
            "window._initialData?.jobInfoWrapperModel?.jobInfoModel?.sanitizedJobDescription",
            # two-pane structure
            "window._initialData?.autoOpenTwoPaneViewjobResponse?.body?.hostQueryExecutionResult?.data?.jobData?.results?.[0]?.job?.description?.text",
            # older path
            "window._initialData?.jobDescription",
            "window._initialData?.sanitizedJobDescription",
        ]
        for path in paths_to_try:
            result = page.evaluate(f"""
                () => {{
                    try {{
                        const val = {path};
                        if (val) return val.substring(0, 300);
                        return null;
                    }} catch(e) {{ return 'ERROR: ' + e.message; }}
                }}
            """)
            if result:
                preview = str(result).replace("\n", " ")[:300]
                print(f"  PATH: {path}")
                print(f"  VALUE: '{preview}'")
                print()
            else:
                print(f"  NULL: {path}")

        # ── jobInfoWrapperModel structure ────────────────────────────────
        print(f"\n[7] jobInfoWrapperModel keys (if exists):")
        jiwm_keys = page.evaluate("""
            () => {
                const m = window._initialData?.jobInfoWrapperModel;
                if (!m) return ['NOT FOUND'];
                return Object.keys(m);
            }
        """)
        for k in jiwm_keys:
            print(f"  - {k}")

        print(f"\n[8] jobInfoWrapperModel.jobInfoModel keys (if exists):")
        jim_keys = page.evaluate("""
            () => {
                const m = window._initialData?.jobInfoWrapperModel?.jobInfoModel;
                if (!m) return ['NOT FOUND'];
                return Object.keys(m);
            }
        """)
        for k in jim_keys:
            print(f"  - {k}")

        # ── Try jobDescriptionSectionModel ────────────────────────────────
        print(f"\n[9] sanitizedJobDescription (first 1000 chars):")
        sjd = page.evaluate("""
            () => {
                const m = window._initialData?.jobInfoWrapperModel?.jobInfoModel;
                if (!m) return null;
                return m.sanitizedJobDescription || null;
            }
        """)
        if sjd:
            print(str(sjd)[:1000])
        else:
            print("  NOT FOUND")

        # ── Raw HTML (first 4000 chars) ───────────────────────────────────
        html = page.content()
        print(f"\n[10] RAW HTML (first 4000 chars of {len(html)} total):")
        print(THIN)
        print(html[:4000])
        print(THIN)

        browser.close()

    print(f"\n{DIVIDER}")
    print("DONE")
    print(DIVIDER)


if __name__ == "__main__":
    main()
