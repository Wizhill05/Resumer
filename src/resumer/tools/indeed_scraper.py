"""
indeed_scraper.py — Scrapes an Indeed job search results page using Playwright.

DOM strategy (confirmed against in.indeed.com 2026-04):
  - [data-jk] selects the job-title <a> tag (NOT the full card)
  - el.closest('li') walks up to the full card container
  - company  : [data-testid="company-name"]
  - location : [data-testid="text-location"]
  - salary   : .salary-snippet-container  (first match)
  - snippet  : parsed from <li> innerText (after "Easily apply\n", before "View all ")

When fetch_details=True, each job's viewjob page is also visited to extract:
  - Full plain-text job description (from #jobDescriptionText or _initialData)
  - External employer apply URL (from _initialData.job.url)
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from schemas.indeed_schema import IndeedJob  # noqa: E402

_CARD_WAIT_TIMEOUT_MS = 15_000

# ---------------------------------------------------------------------------
# JavaScript: extract all job cards from the SERP page in one pass
# ---------------------------------------------------------------------------
_EXTRACT_SERP_JS = """
() => {
    const anchors = document.querySelectorAll('[data-jk]');
    const results = [];

    anchors.forEach(anchor => {
        const jobId = anchor.getAttribute('data-jk');
        if (!jobId) return;

        const li = anchor.closest('li');
        if (!li) return;

        // Title from aria-label (most reliable)
        const ariaLabel = anchor.getAttribute('aria-label') || '';
        const title = ariaLabel.replace(/^full details of /i, '').trim()
            || (anchor.querySelector('span[title]') || {}).title
            || anchor.innerText.trim();
        if (!title) return;

        // Company
        const companyEl = li.querySelector('[data-testid="company-name"]');
        const company = companyEl ? companyEl.innerText.trim() : '';

        // Location
        const locationEl = li.querySelector('[data-testid="text-location"]');
        const location = locationEl ? locationEl.innerText.trim() : '';

        // Salary (first .salary-snippet-container in the card)
        const salaryEl = li.querySelector('.salary-snippet-container');
        const salary = salaryEl ? salaryEl.innerText.trim() : '';

        // Snippet: parse from <li> innerText after "Easily apply", before "View all "
        let snippet = '';
        const fullText = li.innerText || '';
        const applyMarker = 'Easily apply';
        const viewAllMarker = 'View all ';
        const applyIdx = fullText.indexOf(applyMarker);
        if (applyIdx !== -1) {
            const afterApply = fullText.slice(applyIdx + applyMarker.length).trim();
            const viewAllIdx = afterApply.indexOf(viewAllMarker);
            snippet = (viewAllIdx !== -1
                ? afterApply.slice(0, viewAllIdx)
                : afterApply
            ).trim().replace(/\\s+/g, ' ');
        }

        results.push({ jobId, title, company, location, salary, snippet });
    });

    return results;
}
"""

# ---------------------------------------------------------------------------
# JavaScript: extract description + apply URL from a viewjob page
# ---------------------------------------------------------------------------
_EXTRACT_VIEWJOB_JS = """
() => {
    // ── Full description text ──────────────────────────────────────────
    let description = '';

    // Method 1: DOM element (most pages)
    const descEl = document.getElementById('jobDescriptionText');
    if (descEl) {
        description = descEl.innerText.trim();
    }

    // Method 2: fall back to _initialData embedded JSON
    if (!description && window._initialData) {
        try {
            // Path for viewjob pages
            const vjModel = window._initialData.jobInfoWrapperModel;
            if (vjModel) {
                const raw = vjModel.jobInfoModel
                    && vjModel.jobInfoModel.jobDescriptionSectionModel
                    && vjModel.jobInfoModel.jobDescriptionSectionModel.jobDetailsSection;
                // sanitizedJobDescription is HTML, prefer plain text from _initialData
            }
            // Alternative path
            const twoPane = window._initialData.autoOpenTwoPaneViewjobResponse;
            if (twoPane && twoPane.body && twoPane.body.hostQueryExecutionResult) {
                const results = twoPane.body.hostQueryExecutionResult.data
                    && twoPane.body.hostQueryExecutionResult.data.jobData
                    && twoPane.body.hostQueryExecutionResult.data.jobData.results;
                if (results && results.length > 0) {
                    const jobDesc = results[0].job && results[0].job.description;
                    if (jobDesc && jobDesc.text) {
                        description = jobDesc.text.trim();
                    }
                }
            }
        } catch (e) {}
    }

    // ── External apply URL ─────────────────────────────────────────────
    let applyUrl = '';

    // Method 1: _initialData.job.url (employer's website)
    try {
        const twoPane = window._initialData && window._initialData.autoOpenTwoPaneViewjobResponse;
        if (twoPane && twoPane.body && twoPane.body.hostQueryExecutionResult) {
            const results = twoPane.body.hostQueryExecutionResult.data
                && twoPane.body.hostQueryExecutionResult.data.jobData
                && twoPane.body.hostQueryExecutionResult.data.jobData.results;
            if (results && results.length > 0) {
                const jobUrl = results[0].job && results[0].job.url;
                if (jobUrl && !jobUrl.includes('indeed.com')) {
                    applyUrl = jobUrl;
                }
            }
        }
    } catch (e) {}

    // Method 2: "Apply now" button href (external jobs show a direct link)
    if (!applyUrl) {
        const applyBtn = document.querySelector(
            'a[data-testid="applyButton"], '
            + 'a.indeed-apply-button, '
            + 'a[id*="apply-button-link"]'
        );
        if (applyBtn && applyBtn.href && !applyBtn.href.includes('indeed.com/rc/')) {
            applyUrl = applyBtn.href;
        }
    }

    return { description, applyUrl };
}
"""


def _fetch_details(browser, job: IndeedJob, url: str, cookie_val: str) -> IndeedJob:
    """Visit a single viewjob page and enrich the job with description + apply_url."""
    from playwright.sync_api import TimeoutError as PlaywrightTimeout

    # Use a fresh context so Indeed doesn't redirect us to the two-pane SERP layout
    context = browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1440, "height": 900},
        locale="en-IN",
    )

    if cookie_val:
        domain = ".in.indeed.com" if "in.indeed.com" in url else ".indeed.com"
        context.add_cookies([{
            "name": "CTK",
            "value": cookie_val,
            "domain": domain,
            "path": "/",
        }])

    page = context.new_page()
    try:
        page.goto(job.job_url, wait_until="domcontentloaded", timeout=20_000)
        # Wait for description container or at least some content
        try:
            page.wait_for_selector(
                "#jobDescriptionText, [data-testid='jobDescriptionText']",
                timeout=8_000
            )
        except PlaywrightTimeout:
            pass  # Continue even if specific selector missing — JS fallback will handle it
        page.wait_for_timeout(1_000)

        result: dict = page.evaluate(_EXTRACT_VIEWJOB_JS)
        job = job.model_copy(update={
            "description": result.get("description", ""),
            "apply_url": result.get("applyUrl", ""),
        })
    except Exception as exc:
        print(f"  [warn] Could not fetch details for {job.job_url}: {exc}", file=sys.stderr)
    finally:
        context.close()

    return job


def scrape_indeed_search(
    url: str,
    fetch_details: bool = False,
    details_delay_ms: int = 1_500,
) -> list[IndeedJob]:
    """Scrape an Indeed search results page and return a list of IndeedJob objects.

    Args:
        url: Full Indeed job search URL.
        fetch_details: If True, visits each job's viewjob page to get the full
            description and external apply URL. Slower but necessary for the
            resume generation pipeline.
        details_delay_ms: Milliseconds to wait between viewjob requests when
            fetch_details=True (rate-limit protection).

    Returns:
        List of IndeedJob instances.

    Raises:
        ImportError: If Playwright is not installed.
        RuntimeError: If scraping fails or times out.
    """
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
    except ImportError:
        raise ImportError(
            "Playwright is not installed. Run: uv run playwright install chromium"
        )

    # Ensure Windows asyncio policy supports Playwright subprocesses inside Streamlit threads
    import os
    if os.name == "nt":
        import asyncio
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        except Exception:
            pass

    base = "https://in.indeed.com" if "in.indeed.com" in url else "https://www.indeed.com"
    jobs: list[IndeedJob] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
            ],
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

        # Optional session cookie
        cookie_val = os.environ.get("INDEED_SESSION_COOKIE", "").strip()
        if cookie_val:
            domain = ".in.indeed.com" if "in.indeed.com" in url else ".indeed.com"
            context.add_cookies([{
                "name": "CTK",
                "value": cookie_val,
                "domain": domain,
                "path": "/",
            }])

        # ── Step 1: scrape the SERP page ──────────────────────────────────
        page = context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_selector("[data-jk]", timeout=_CARD_WAIT_TIMEOUT_MS)
            page.wait_for_timeout(2_500)
        except PlaywrightTimeout:
            browser.close()
            raise RuntimeError(
                f"Timed out waiting for job cards on: {url}\n"
                "The page may require login or the selector has changed."
            )

        raw_jobs: list[dict] = page.evaluate(_EXTRACT_SERP_JS)
        page.close()

        # Build initial job objects
        for raw in raw_jobs:
            job_id = raw.get("jobId", "")
            if not job_id:
                continue
            jobs.append(IndeedJob(
                job_id=job_id,
                title=raw.get("title", ""),
                company=raw.get("company", ""),
                location=raw.get("location", ""),
                salary=raw.get("salary", ""),
                snippet=raw.get("snippet", ""),
                job_url=f"{base}/viewjob?jk={job_id}",
            ))

        # ── Step 2 (optional): visit each viewjob page for full details ──
        if fetch_details:
            enriched: list[IndeedJob] = []
            for i, job in enumerate(jobs):
                print(f"  Fetching details {i + 1}/{len(jobs)}: {job.title[:50]}...",
                      flush=True)
                job = _fetch_details(browser, job, url, cookie_val)
                enriched.append(job)
                if i < len(jobs) - 1:
                    __import__("time").sleep(details_delay_ms / 1000)
            jobs = enriched

        browser.close()

    return jobs
