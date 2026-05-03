"""
crawl_indeed.py
===============
A multi-page crawler for Indeed jobs that fetches search pages
using Scrapling's StealthyFetcher, parses the HTML in memory,
extracts job details, normalizes salaries using Mistral API, and
filters technical skills using Mistral API.

Workflow (three sequential phases):
  Phase 1 — Scrape basic info for ALL jobs across all pages.
  Phase 2 — Deep-fetch every job's individual page (description + attributes).
  Phase 3 — Run NLP (salary normalisation + skill filter) on all jobs.

Configuration:
- TARGET_JOBS_COUNT: Adjust this to change how many jobs to scrape.
"""

import json
import os
import sys
import time
import random
import re
from pathlib import Path
from dotenv import load_dotenv

from scrapling.fetchers import StealthyFetcher, StealthySession
from scrapling.parser import Selector
from pydantic import BaseModel
from litellm import completion

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

TARGET_JOBS_COUNT = 50  # <--- Change this to scrape more or fewer jobs

TARGET_URL_BASE = (
    "https://in.indeed.com/jobs"
    "?q=ai+engineer"
    "&l=Bengaluru%2C+Karnataka"
    "&salaryType=%E2%82%B91%2C80%2C000"
    "&radius=25"
    "&sc=0kf%3Aattr%28VDTG7%29%3B"
)
# Note: we removed the static `&vjk=...` from the base URL so pagination works cleanly

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_JSON = OUTPUT_DIR / "parsed_jobs.json"
CHROME_PROFILE_DIR = OUTPUT_DIR / "chrome_profile"

# Load environment variables
load_dotenv(Path(__file__).parents[2] / ".env.local")
if os.getenv("MISTRAL_API_KEY"):
    os.environ["MISTRAL_API_KEY"] = os.getenv("MISTRAL_API_KEY")

# ---------------------------------------------------------------------------
# NLP Setup
# ---------------------------------------------------------------------------


class SalaryExtraction(BaseModel):
    min_salary_inr_per_year: float | None
    max_salary_inr_per_year: float | None


def normalize_salary(pay_str: str) -> dict:
    """Use Mistral via LiteLLM to normalize a salary string into min/max INR per year.
    Kept as an API call because currency parsing (handling $, €, ₹, £, lpa, etc.)
    requires language understanding beyond simple regex.
    """
    if not os.environ.get("MISTRAL_API_KEY"):
        return {"min_salary_inr_per_year": None, "max_salary_inr_per_year": None}

    try:
        response = completion(
            model="mistral/ministral-3b-2512",
            messages=[
                {
                    "role": "system",
                    "content": "You are a helpful assistant that converts salary strings into normalized INR per year. If given a range, extract min and max. If given a single number, set both min and max to that number. Assume standard working hours for hourly rates. 1 month = 12 months/year. Convert foreign currencies to INR at current approximate exchange rates.",
                },
                {
                    "role": "user",
                    "content": f"Extract normalized salary in INR per year from: {pay_str}",
                },
            ],
            response_format=SalaryExtraction,
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        print(f"[!] Salary NLP failed for '{pay_str}': {e}", file=sys.stderr)
        return {"min_salary_inr_per_year": None, "max_salary_inr_per_year": None}


# ---------------------------------------------------------------------------
# Mistral — Technical Skill Filter
# ---------------------------------------------------------------------------


class SkillFilter(BaseModel):
    technical_skills: list[str]


def filter_technical_skills(attributes: list[str]) -> list[str]:
    """Run attributes through Mistral to keep only technical skills."""
    if not attributes:
        return []
    if not os.environ.get("MISTRAL_API_KEY"):
        return attributes

    try:
        response = completion(
            model="mistral/ministral-3b-2512",
            messages=[
                {
                    "role": "system",
                    "content": "You are a helpful assistant that filters a list of job attributes and returns ONLY the hard technical skills (e.g., programming languages, frameworks, tools, databases). Exclude soft skills like 'English', 'Communication', 'Teamwork', 'Leadership', 'Problem Solving'. Also Exclude noise data like 'CI\\\\u002FCD",
                },
                {
                    "role": "user",
                    "content": f"Filter these attributes to only technical skills: {json.dumps(attributes)}",
                },
            ],
            response_format=SkillFilter,
        )
        result = json.loads(response.choices[0].message.content)
        return result.get("technical_skills", [])
    except Exception as e:
        print(f"[!] Skill filter NLP failed: {e}", file=sys.stderr)
        return attributes


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def extract_text(element):
    """Recursively extract and join all text from an element and its descendants."""
    if not element:
        return ""
    texts = element.xpath(".//text()").getall()
    return " ".join("".join(texts).split())


# ---------------------------------------------------------------------------
# Phase 1 — Parse basic info from a search-results page (no network calls)
# ---------------------------------------------------------------------------


def parse_basic_jobs_from_html(html_content: str) -> list[dict]:
    """Parse lightweight job records from raw Indeed search-results HTML.

    Only extracts fields available on the listing card (title, company,
    location, posted_date, raw pay string, metadata, snippet).
    No deep-fetch or NLP happens here.
    """
    page = Selector(html_content)
    job_cards = page.css(".job_seen_beacon")

    parsed_jobs = []

    for card in job_cards:
        job = {}

        # Link and ID
        title_link = card.css(".jcs-JobTitle")
        if title_link:
            job["id"] = title_link[0].attrib.get("data-jk", "")
            href = title_link[0].attrib.get("href", "")
            job["link"] = f"https://in.indeed.com{href}" if href else ""

            # Title text
            title_span = title_link[0].css("span[title]")
            if title_span:
                job["title"] = extract_text(title_span[0])
            else:
                job["title"] = extract_text(title_link[0])

        # Company
        company_elem = card.css('.company_location [data-testid="company-name"]')
        if company_elem:
            job["company"] = extract_text(company_elem[0])

        # Location
        location_elem = card.css('.company_location [data-testid="text-location"]')
        if location_elem:
            job["location"] = extract_text(location_elem[0])

        # Date Posted
        date_elems = card.css('[data-testid="myJobsStateDate"]')
        if date_elems:
            job["posted_date"] = extract_text(date_elems[0])
        else:
            all_spans = card.css("span")
            for sp in all_spans:
                t = extract_text(sp)
                if "Posted" in t or "posted" in t or "Active" in t:
                    job["posted_date"] = t
                    break

        # Metadata (Pay, Job Type, etc.)
        metadata_elems = card.css(".metadataContainer li")
        metadata = []
        for el in metadata_elems:
            text = extract_text(el)
            if text:
                metadata.append(text)

        # Stash raw pay string (NLP happens in Phase 3)
        pay_info = [
            m
            for m in metadata
            if any(char.isdigit() for char in m)
            and ("a year" in m or "a month" in m or "₹" in m)
        ]
        if pay_info:
            raw_pay = pay_info[0]
            job["pay"] = raw_pay
            metadata.remove(raw_pay)

        job["metadata"] = metadata

        # Description snippet
        snippet_elem = card.css(".job-snippet li")
        if snippet_elem:
            job["snippet"] = [
                extract_text(el) for el in snippet_elem if extract_text(el)
            ]

        parsed_jobs.append(job)

    return parsed_jobs


# ---------------------------------------------------------------------------
# Phase 2 — Deep-fetch a single job page
# ---------------------------------------------------------------------------


def captcha_recovery(session, job_id: str) -> None:
    """Navigate the visible browser to the Indeed homepage so the user can
    solve any CAPTCHA/bot-challenge that appeared, then wait for confirmation.

    Called automatically when a 403 is detected after initial retries.
    """
    print()
    print("  " + "!" * 56)
    print("  [CAPTCHA] Indeed returned 403 — bot challenge detected.")
    print("  [CAPTCHA] Navigating browser to Indeed homepage...")
    print("  " + "!" * 56)
    try:
        # Navigate to homepage — this surfaces the CAPTCHA in the open browser
        session.fetch(
            "https://in.indeed.com/",
            network_idle=False,
            timeout=45_000,
            google_search=False,
        )
    except Exception:
        pass  # best-effort; browser is still open for user interaction
    print()
    print("  >>> Please check the browser window and solve the CAPTCHA if present.")
    print("  >>> Press Enter here once the page looks normal to resume scraping...")
    input()
    print(f"  [CAPTCHA] Resuming. Waiting 5s before retrying job {job_id}...")
    time.sleep(5)


def fetch_deep_job_details(session, job_id: str, max_retries: int = 3) -> dict | None:
    """Fetch description and raw attributes from the individual job page.

    Returns a dict with 'description' and 'raw_attributes' (list[str]) on
    success, or None if the job page could not be fetched after all retries
    (any non-200 status, timeout, or exception). Returning None signals to
    the caller that this job should be dropped from the final output.
    NLP filtering happens later in Phase 3.
    Uses network_idle=False (wait_until='load') so Playwright doesn't hang
    waiting for Indeed's infinite background XHRs.
    """
    url = f"https://in.indeed.com/viewjob?jk={job_id}"
    print(f"      [*] Deep Fetch: {url}")

    captcha_triggered = False
    for attempt in range(1, max_retries + 1):
        try:
            page = session.fetch(
                url, network_idle=False, timeout=45_000, google_search=False
            )
            if page.status == 403:
                print(
                    f"      [!] HTTP 403 on attempt {attempt} — rate-limited / bot challenge."
                )
                if not captcha_triggered:
                    # Trigger recovery once; subsequent attempts retry silently
                    captcha_triggered = True
                    captcha_recovery(session, job_id)
                elif attempt < max_retries:
                    time.sleep(random.uniform(8, 15))
                continue
            if page.status != 200:
                print(f"      [!] HTTP {page.status} on attempt {attempt}.")
                if attempt < max_retries:
                    time.sleep(random.uniform(3, 6))
                    continue
                return None  # non-200: drop this job
            html = page.html_content
            page_sel = Selector(html)

            details = {}
            # Description
            desc_elem = page_sel.css("#jobDescriptionText")
            if desc_elem:
                details["description"] = extract_text(desc_elem[0])

            # Raw attributes (NLP deferred to Phase 3)
            pattern = re.compile(
                r'"__typename":"JobAttribute","key":"[^"]+","label":"([^"]+)"'
            )
            matches = pattern.findall(html)
            if matches:
                details["raw_attributes"] = list(set(matches))

            return details
        except Exception as e:
            print(f"      [!] Deep fetch attempt {attempt}/{max_retries} failed: {e}")
            if attempt < max_retries:
                backoff = random.uniform(4, 8) * attempt
                print(f"      [*] Retrying in {backoff:.1f}s...")
                time.sleep(backoff)

    print(f"      [!] All {max_retries} attempts failed for job {job_id}. Dropping.")
    return None  # all retries exhausted: drop this job


# ---------------------------------------------------------------------------
# Phase 3 — NLP: salary normalisation + skill filter
# ---------------------------------------------------------------------------


def run_nlp_on_job(job: dict) -> dict:
    """Enrich a single job dict with NLP-derived fields.

    - Normalises 'pay' → 'min_salary_inr' / 'max_salary_inr'
    - Filters 'raw_attributes' → 'technical_skills' via Mistral
    """
    # Salary normalisation
    if job.get("pay"):
        raw_pay = job["pay"]
        safe_pay_print = raw_pay.encode("ascii", "ignore").decode("ascii")
        print(f"      [NLP] Normalizing salary: {safe_pay_print}")
        normalized = normalize_salary(raw_pay)
        if normalized:
            job["min_salary_inr"] = normalized.get("min_salary_inr_per_year")
            job["max_salary_inr"] = normalized.get("max_salary_inr_per_year")

    # Skill extraction
    raw_attrs = job.pop("raw_attributes", None)
    if raw_attrs:
        print(f"      [NLP] Filtering {len(raw_attrs)} attributes via Mistral...")
        job["technical_skills"] = filter_technical_skills(raw_attrs)

    return job


# ---------------------------------------------------------------------------
# Main Crawler Loop
# ---------------------------------------------------------------------------


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    CHROME_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    # -----------------------------------------------------------------------
    # PHASE 1: Scrape basic info for ALL jobs
    # -----------------------------------------------------------------------
    print(f"\n{'=' * 60}")
    print(f"  PHASE 1 — Scraping basic job listings")
    print(f"  Target: {TARGET_JOBS_COUNT} jobs")
    print(f"{'=' * 60}\n")

    all_jobs: list[dict] = []
    seen_ids: set[str] = set()
    start_offset = 0

    print(f"[*] Using Chrome profile directory: {CHROME_PROFILE_DIR}")

    with StealthySession(
        headless=False, user_data_dir=str(CHROME_PROFILE_DIR)
    ) as session:
        # --- Phase 1: collect all basic job cards ---
        MAX_PAGE_RETRIES = 3
        while len(all_jobs) < TARGET_JOBS_COUNT:
            url = f"{TARGET_URL_BASE}&start={start_offset}"
            print(f"\n[*] Fetching page (start={start_offset}): {url}")

            html = None
            for attempt in range(1, MAX_PAGE_RETRIES + 1):
                try:
                    page = session.fetch(
                        url, network_idle=False, timeout=45_000, google_search=False
                    )
                    if page.status != 200:
                        print(
                            f"[!] HTTP {page.status} on attempt {attempt}.",
                            file=sys.stderr,
                        )
                        if attempt < MAX_PAGE_RETRIES:
                            time.sleep(random.uniform(5, 10))
                            continue
                        break
                    html = page.html_content
                    break  # success
                except Exception as e:
                    print(
                        f"[!] Page fetch attempt {attempt}/{MAX_PAGE_RETRIES} failed: {e}",
                        file=sys.stderr,
                    )
                    if attempt < MAX_PAGE_RETRIES:
                        backoff = random.uniform(6, 12) * attempt
                        print(f"[*] Retrying in {backoff:.1f}s...")
                        time.sleep(backoff)

            if html is None:
                print(
                    "[!] Could not fetch page after retries. Stopping.", file=sys.stderr
                )
                break

            # Sanity check
            if "jobs" not in html.lower() and "indeed" not in html.lower():
                print(
                    "[!] WARNING: Page doesn't look like Indeed. Cloudflare block or Login screen?"
                )
                break

            jobs_on_page = parse_basic_jobs_from_html(html)
            if not jobs_on_page:
                print(
                    "[*] No jobs found on page. We may have reached the end of results."
                )
                break

            print(f"[*] Found {len(jobs_on_page)} jobs on page.")

            # Filter duplicates
            new_jobs = []
            for job in jobs_on_page:
                jid = job.get("id")
                if jid and jid not in seen_ids:
                    seen_ids.add(jid)
                    new_jobs.append(job)

            if len(new_jobs) < 3:
                print(
                    f"[*] Only found {len(new_jobs)} new jobs on this page. Stopping scraper as per <3 threshold."
                )
                all_jobs.extend(new_jobs)
                break

            all_jobs.extend(new_jobs)
            print(
                f"[*] Total unique jobs collected so far: {len(all_jobs)} / {TARGET_JOBS_COUNT}"
            )

            if len(all_jobs) >= TARGET_JOBS_COUNT:
                break

            # Pagination step
            start_offset += 10

            # Respectful delay
            delay = random.uniform(3, 7)
            print(f"[*] Sleeping for {delay:.1f} seconds to avoid blocks...")
            time.sleep(delay)

        # Trim to target count
        if len(all_jobs) > TARGET_JOBS_COUNT:
            all_jobs = all_jobs[:TARGET_JOBS_COUNT]

        print(f"\n[OK] Phase 1 complete. Collected {len(all_jobs)} basic job records.")

        # Save Phase 1 snapshot
        with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
            json.dump(all_jobs, f, indent=4, ensure_ascii=False)
        print(f"[*] Phase 1 snapshot saved to {OUTPUT_JSON.resolve()}")

        # -----------------------------------------------------------------------
        # PHASE 2: Deep-fetch every job's individual page
        # -----------------------------------------------------------------------
        print(f"\n{'=' * 60}")
        print(f"  PHASE 2 — Deep-fetching {len(all_jobs)} job pages")
        print(f"{'=' * 60}\n")

        enriched_jobs: list[dict] = []
        dropped = 0
        for idx, job in enumerate(all_jobs, start=1):
            job_id = job.get("id")
            if not job_id:
                print(f"  [{idx}/{len(all_jobs)}] Skipping job with no ID.")
                dropped += 1
                continue

            print(f"  [{idx}/{len(all_jobs)}] Deep-fetching job: {job_id}")
            time.sleep(
                random.uniform(4.0, 8.0)
            )  # slower = less likely to trigger rate limits
            deep_details = fetch_deep_job_details(session, job_id)

            if deep_details is None:
                # fetch failed — exclude this job from all downstream processing
                print(f"      [-] Dropping job {job_id} (deep fetch failed).")
                dropped += 1
                continue

            job.update(deep_details)
            enriched_jobs.append(job)

        all_jobs = enriched_jobs
        print(
            f"\n[OK] Phase 2 complete. {len(all_jobs)} jobs enriched, {dropped} dropped."
        )

        # Save Phase 2 snapshot
        with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
            json.dump(all_jobs, f, indent=4, ensure_ascii=False)
        print(
            f"[*] Phase 2 snapshot saved to {OUTPUT_JSON.resolve()} ({len(all_jobs)} jobs)"
        )

    # -----------------------------------------------------------------------
    # PHASE 3: NLP — salary normalisation + GLiNER skill filtering
    # (session not needed — all network work is done)
    # -----------------------------------------------------------------------
    print(f"\n{'=' * 60}")
    print(f"  PHASE 3 — NLP enrichment on {len(all_jobs)} jobs")
    print(f"{'=' * 60}\n")

    for idx, job in enumerate(all_jobs, start=1):
        print(
            f"  [{idx}/{len(all_jobs)}] NLP: {job.get('title', 'Unknown')} @ {job.get('company', '?')}"
        )
        run_nlp_on_job(job)

    print(f"\n[OK] Phase 3 complete. NLP enrichment done.")

    # Final save
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(all_jobs, f, indent=4, ensure_ascii=False)

    print(
        f"\n[OK] Crawler finished. Saved {len(all_jobs)} jobs to {OUTPUT_JSON.resolve()}"
    )


if __name__ == "__main__":
    main()
