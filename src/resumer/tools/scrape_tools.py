"""
scrape_tools.py — CrewAI tool for scraping web pages using Playwright.

The Job Researcher agent uses this tool to fetch and clean the text content
of a job posting URL before the LLM extracts the job description.
"""

from __future__ import annotations

import re
import sys

# Force UTF-8 on Windows
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

# Maximum characters of page text to send to the LLM (keeps token cost low)
_MAX_CHARS = 12_000

def _clean_html_to_text(html: str) -> str:
    """Strip HTML tags and boilerplate, returning readable plain text."""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript", "iframe"]):
            tag.decompose()
        text = soup.get_text(separator="\n")
    except ImportError:
        text = re.sub(r"<[^>]+>", " ", html)

    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    deduped: list[str] = []
    for line in lines:
        if not deduped or deduped[-1] != line:
            deduped.append(line)
    return "\n".join(deduped)

def scrape_url(url: str) -> str:
    """Scrapes the given URL using a headless browser and returns cleaned page text.

    Use this whenever you need to read the content of a web page, especially
    job postings on LinkedIn, Indeed, Wellfound, company career pages, etc.

    Args:
        url: The full URL of the job posting or any webpage to scrape.

    Returns:
        A string containing the cleaned, readable text of the page (up to 12,000 chars),
        or an error message describing why the scrape failed.
    """
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
    except ImportError:
        return "ERROR: Playwright is not installed. Run: playwright install chromium"

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox"],
            )
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 900},
            )

            # Inject LinkedIn session cookie if available and target is LinkedIn
            import os
            li_cookie = os.environ.get("LINKEDIN_SESSION_COOKIE")
            if li_cookie and "linkedin.com" in url:
                context.add_cookies([
                    {
                        "name": "li_at",
                        "value": li_cookie.strip(),
                        "domain": ".linkedin.com",
                        "path": "/",
                    }
                ])

            page = context.new_page()

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                # Give JS-rendered content a moment to settle
                page.wait_for_timeout(2000)
                html = page.content()
            except PlaywrightTimeout:
                browser.close()
                return f"ERROR: Timed out loading {url} — page took too long to respond."
            finally:
                browser.close()

        text = _clean_html_to_text(html)

        if not text.strip():
            return f"ERROR: No readable text found on {url} — the page may be empty or require login."

        # Truncate to token-safe length
        truncated = text[:_MAX_CHARS]
        if len(text) > _MAX_CHARS:
            truncated += f"\n\n[... content truncated at {_MAX_CHARS} chars ...]"

        return truncated

    except Exception as exc:
        return f"ERROR scraping {url}: {type(exc).__name__}: {exc}"
