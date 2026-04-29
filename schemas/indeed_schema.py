"""
indeed_schema.py — Pydantic model for a scraped Indeed job card.
"""

from __future__ import annotations

from pydantic import BaseModel


class IndeedJob(BaseModel):
    """Represents one job card scraped from an Indeed search results page."""

    job_id: str
    title: str
    company: str
    location: str
    salary: str           # Empty string when not listed
    snippet: str          # Short description blurb from the search results card
    job_url: str          # https://in.indeed.com/viewjob?jk={job_id}

    # Populated only when fetch_details=True in scrape_indeed_search()
    description: str = ""  # Full plain-text job description from the viewjob page
    apply_url: str = ""    # External employer apply URL (empty for Indeed-Apply jobs)
