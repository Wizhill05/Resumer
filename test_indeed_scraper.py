"""
test_indeed_scraper.py — Console test for the Indeed scraper.

Usage:
    # Search results only (fast, ~8s):
    uv run python test_indeed_scraper.py

    # With full description + external apply URL (slower, visits each job page):
    uv run python test_indeed_scraper.py --details

    # Custom URL:
    uv run python test_indeed_scraper.py "https://in.indeed.com/jobs?q=..." [--details]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.resumer.tools.indeed_scraper import scrape_indeed_search  # noqa: E402

DEFAULT_URL = (
    "https://in.indeed.com/jobs"
    "?q=summer+internship+computer+science+students"
    "&l=Bengaluru%2C+Karnataka"
    "&salaryType=%E2%82%B91%2C20%2C000%2B"
    "&radius=25"
)

DIVIDER = "=" * 72
THIN = "-" * 72


def main() -> None:
    args = sys.argv[1:]
    fetch_details = "--details" in args
    url_args = [a for a in args if not a.startswith("--")]
    url = url_args[0] if url_args else DEFAULT_URL

    mode = "FULL DETAILS" if fetch_details else "SEARCH RESULTS ONLY"
    print(f"\nMode    : {mode}")
    print(f"Scraping: {url}\n")

    try:
        jobs = scrape_indeed_search(url, fetch_details=fetch_details)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    if not jobs:
        print("No jobs found. Page may be blocked or structure changed.")
        sys.exit(0)

    print(f"\nFound {len(jobs)} job(s)\n")
    print(DIVIDER)

    for i, job in enumerate(jobs, 1):
        salary_str = f"Salary  : {job.salary}" if job.salary else "Salary  : (not listed)"
        snippet_str = job.snippet[:200] + ("..." if len(job.snippet) > 200 else "")

        print(f"[{i:02d}] {job.title}")
        print(f"      Company : {job.company}")
        print(f"      Location: {job.location}")
        print(f"      {salary_str}")
        if fetch_details:
            # Show first 400 chars of full description
            desc_preview = job.description[:400].replace("\n", " ")
            if len(job.description) > 400:
                desc_preview += "..."
            print(f"      Desc    : {desc_preview if desc_preview else '(none)'}")
            apply_display = job.apply_url if job.apply_url else "(Indeed Apply / not external)"
            print(f"      ApplyURL: {apply_display}")
        else:
            print(f"      Snippet : {snippet_str}")
        print(f"      JobURL  : {job.job_url}")
        print(THIN)

    print(f"\nTotal: {len(jobs)} jobs scraped.")
    if not fetch_details:
        print("Tip: Run with --details to also fetch full descriptions and apply URLs.")
    print()


if __name__ == "__main__":
    main()
