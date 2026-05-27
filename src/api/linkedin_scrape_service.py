"""
linkedin_scrape_service.py
==========================
Background service that runs the LinkedIn scraping pipeline inside a thread,
emitting live status/logs to callers and persisting to LocalBackend.
"""

from __future__ import annotations

import random
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

load_dotenv()
load_dotenv(_PROJECT_ROOT / ".env.local", override=True)


@dataclass
class ScrapeLogEntry:
    ts: float
    text: str
    level: str = "info"


@dataclass
class ScrapeStatus:
    state: str = "idle"  # idle|phase1|phase2|phase3|completed|failed|stopping|stopped
    phase: str = "-"
    progress: str = "-"
    total_jobs: int = 0
    enriched_jobs: int = 0
    error: str = ""


class LinkedInScrapeService:
    """Manages a single LinkedIn scraping run in a background thread."""

    MAX_LOG_LINES = 3000

    def __init__(self, backend: Any) -> None:
        self._backend = backend
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

        self.status = ScrapeStatus()
        self.logs: list[ScrapeLogEntry] = []

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(
        self,
        *,
        keywords: str = "Software Engineer",
        location: str = "India",
        geo_id: str = "102713980",
        distance: str = "25",
        experience_levels: str = "1",
        work_types: str = "2,1",
        job_types: str = "",
        posted_within: str = "",
        salary_tag: str = "",
        sort_by: str = "R",
        easy_apply: bool = False,
        target_count: int = 50,
        direct_url: str = "",
    ) -> None:
        if self.is_running:
            raise RuntimeError("A LinkedIn scrape run is already in progress")

        self._stop_event.clear()
        self.logs = []
        self.status = ScrapeStatus(state="starting")

        self._thread = threading.Thread(
            target=self._run,
            kwargs=dict(
                keywords=keywords,
                location=location,
                geo_id=geo_id,
                distance=distance,
                experience_levels=experience_levels,
                work_types=work_types,
                job_types=job_types,
                posted_within=posted_within,
                salary_tag=salary_tag,
                sort_by=sort_by,
                easy_apply=easy_apply,
                target_count=target_count,
                direct_url=direct_url,
            ),
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        if not self.is_running:
            return
        self.status.state = "stopping"
        self._stop_event.set()

    def _log(self, text: str, level: str = "info") -> None:
        with self._lock:
            self.logs.append(ScrapeLogEntry(ts=time.time(), text=text, level=level))
            if len(self.logs) > self.MAX_LOG_LINES:
                self.logs = self.logs[-self.MAX_LOG_LINES:]

    def _run(
        self,
        *,
        keywords: str,
        location: str,
        geo_id: str,
        distance: str,
        experience_levels: str,
        work_types: str,
        job_types: str,
        posted_within: str,
        salary_tag: str,
        sort_by: str,
        easy_apply: bool,
        target_count: int,
        direct_url: str,
    ) -> None:
        session_id = uuid.uuid4().hex[:12]
        try:
            self._run_pipeline(
                keywords=keywords,
                location=location,
                geo_id=geo_id,
                distance=distance,
                experience_levels=experience_levels,
                work_types=work_types,
                job_types=job_types,
                posted_within=posted_within,
                salary_tag=salary_tag,
                sort_by=sort_by,
                easy_apply=easy_apply,
                target_count=target_count,
                direct_url=direct_url,
                session_id=session_id,
            )
        except Exception as exc:
            self.status.state = "failed"
            self.status.error = str(exc)
            self._log(f"Fatal error: {exc}", "error")

    def _run_pipeline(
        self,
        *,
        keywords: str,
        location: str,
        geo_id: str,
        distance: str,
        experience_levels: str,
        work_types: str,
        job_types: str,
        posted_within: str,
        salary_tag: str,
        sort_by: str,
        easy_apply: bool,
        target_count: int,
        direct_url: str,
        session_id: str,
    ) -> None:
        from scrapling.fetchers import StealthySession

        from src.linkedin_scraping.crawl_linkedin import (
            build_linkedin_search_url,
            extract_job_id,
            fetch_deep_job_details,
            parse_basic_jobs_from_html,
            extract_salary_from_description,
            filter_technical_skills,
            with_start_param,
        )

        is_single_job_direct = False
        single_job_id = ""
        if direct_url.strip():
            maybe_job_id = extract_job_id(direct_url.strip())
            if "/jobs/view/" in direct_url and maybe_job_id:
                is_single_job_direct = True
                single_job_id = maybe_job_id
                url_base = direct_url.strip()
            else:
                url_base = direct_url.strip()
        else:
            url_base = build_linkedin_search_url(
                keywords=keywords,
                location=location,
                geo_id=geo_id,
                distance=distance,
                experience_levels=experience_levels,
                work_types=work_types,
                job_types=job_types,
                posted_within=posted_within,
                salary_tag=salary_tag,
                sort_by=sort_by,
                easy_apply=easy_apply,
            )

        self._log(f"Scrape session: {session_id}")
        self._log(f"Direct URL provided: {bool(direct_url.strip())}")
        self._log("=" * 50, "event")
        self._log(f"TARGET URL: {url_base}", "event")
        self._log("=" * 50, "event")

        chrome_profile = _PROJECT_ROOT / "src" / "scraping" / "output" / "chrome_profile"
        chrome_profile.mkdir(parents=True, exist_ok=True)

        all_jobs: list[dict] = []
        existing_jobs = self._backend.list_scraped_jobs()
        db_seen_ids = {j["id"] for j in existing_jobs if "id" in j}

        if is_single_job_direct and single_job_id:
            if single_job_id in db_seen_ids:
                self._log("=" * 50, "event")
                self._log(
                    f"SKIPPING — Direct job {single_job_id} already exists in database.",
                    "event",
                )
                self._log("=" * 50, "event")
                self.status.state = "completed"
                self.status.phase = "Completed"
                self.status.progress = "0 jobs processed (already exists)"
                return

            self._log("=" * 50, "event")
            self._log(
                f"SKIPPING PHASE 1 — Direct single job link detected ({single_job_id})",
                "event",
            )
            self._log("=" * 50, "event")
            all_jobs.append(
                {
                    "id": single_job_id,
                    "link": f"https://www.linkedin.com/jobs/view/{single_job_id}/",
                    "status": "basic",
                    "scrape_session": session_id,
                    "scrape_source": "linkedin",
                }
            )
            self.status.total_jobs = 1
        else:
            self.status.state = "phase1"
            self.status.phase = "Phase 1 — Scraping listings"
            self._log("=" * 50, "event")
            self._log("PHASE 1 — Scraping basic job listings", "event")
            self._log("=" * 50, "event")

        seen_ids: set[str] = set()
        start_offset = 0
        pagination_step = 25
        max_page_retries = 3

        with StealthySession(headless=False, user_data_dir=str(chrome_profile)) as session:
            while not is_single_job_direct and len(all_jobs) < target_count:
                if self._stop_event.is_set():
                    self.status.state = "stopped"
                    self._log("Scrape stopped by user.", "warn")
                    return

                page_url = with_start_param(url_base, start_offset)
                self._log(f"Fetching page (start={start_offset})...")

                html = None
                for attempt in range(1, max_page_retries + 1):
                    try:
                        page = session.fetch(
                            page_url,
                            network_idle=False,
                            timeout=45_000,
                            google_search=False,
                        )
                        if page.status != 200:
                            self._log(f"HTTP {page.status} on attempt {attempt}", "warn")
                            if attempt < max_page_retries:
                                time.sleep(random.uniform(5, 10))
                            continue
                        html = page.html_content
                        break
                    except Exception as exc:
                        self._log(
                            f"Page fetch attempt {attempt}/{max_page_retries} failed: {exc}",
                            "error",
                        )
                        if attempt < max_page_retries:
                            backoff = random.uniform(6, 12) * attempt
                            self._log(f"Retrying in {backoff:.1f}s...")
                            time.sleep(backoff)

                if html is None:
                    self._log("Could not fetch page after retries. Stopping.", "error")
                    break

                if "linkedin" not in html.lower():
                    self._log("Page does not look like LinkedIn. Possible challenge/login wall.", "warn")
                    break

                jobs_on_page = parse_basic_jobs_from_html(html)
                if not jobs_on_page:
                    self._log("No jobs found on page. End of results.", "warn")
                    break

                new_jobs: list[dict] = []
                for job in jobs_on_page:
                    job_id = job.get("id")
                    if job_id and job_id in db_seen_ids:
                        continue
                    if job_id and job_id not in seen_ids:
                        seen_ids.add(job_id)
                        new_jobs.append(job)

                if len(new_jobs) < 3:
                    self._log(f"Only {len(new_jobs)} new jobs on page — stopping.", "warn")
                    all_jobs.extend(new_jobs)
                    break

                all_jobs.extend(new_jobs)
                self.status.total_jobs = len(all_jobs)
                self.status.progress = f"{len(all_jobs)}/{target_count} basic records"
                self._log(f"Collected {len(all_jobs)}/{target_count} unique jobs")

                if len(all_jobs) >= target_count:
                    break

                start_offset += pagination_step
                delay = random.uniform(3, 7)
                self._log(f"Sleeping {delay:.1f}s...")
                time.sleep(delay)

            if len(all_jobs) > target_count:
                all_jobs = all_jobs[:target_count]

            self._log(f"Phase 1 complete. {len(all_jobs)} basic records.", "success")
            self.status.total_jobs = len(all_jobs)
            for job in all_jobs:
                job["scrape_session"] = session_id
                job["status"] = "basic"
                job["scrape_source"] = "linkedin"

            if self._stop_event.is_set():
                self.status.state = "stopped"
                self._log("Scrape stopped by user.", "warn")
                return

            self.status.state = "phase2"
            self.status.phase = "Phase 2 — Deep-fetching job pages"
            self._log("=" * 50, "event")
            self._log(f"PHASE 2 — Deep-fetching {len(all_jobs)} job pages", "event")
            self._log("=" * 50, "event")

            enriched_jobs: list[dict] = []
            dropped = 0
            for idx, job in enumerate(all_jobs, start=1):
                if self._stop_event.is_set():
                    self.status.state = "stopped"
                    self._log("Scrape stopped by user.", "warn")
                    return

                job_id = str(job.get("id", "")).strip()
                if not job_id:
                    dropped += 1
                    continue

                self._log(f"[{idx}/{len(all_jobs)}] Deep-fetching: {job_id}")
                self.status.progress = f"{idx}/{len(all_jobs)} deep fetches"
                time.sleep(random.uniform(4.0, 8.0))

                details = fetch_deep_job_details(session, job_id, max_retries=3)
                if details is None:
                    self._log(f"Dropping job {job_id} (deep fetch failed).", "warn")
                    dropped += 1
                    continue

                job.update(details)
                job["status"] = "enriched"
                enriched_jobs.append(job)
                self._backend.upsert_scraped_job(job)

            all_jobs = enriched_jobs
            self.status.enriched_jobs = len(all_jobs)
            self._log(
                f"Phase 2 complete. {len(all_jobs)} enriched, {dropped} dropped.",
                "success",
            )

        if self._stop_event.is_set():
            self.status.state = "stopped"
            self._log("Scrape stopped by user.", "warn")
            return

        self.status.state = "phase3"
        self.status.phase = "Phase 3 — NLP enrichment"
        self._log("=" * 50, "event")
        self._log(f"PHASE 3 — NLP enrichment on {len(all_jobs)} jobs", "event")
        self._log("=" * 50, "event")

        for idx, job in enumerate(all_jobs, start=1):
            if self._stop_event.is_set():
                self.status.state = "stopped"
                self._log("Scrape stopped by user.", "warn")
                return

            self._log(
                f"[{idx}/{len(all_jobs)}] NLP: {job.get('title', '?')} @ {job.get('company', '?')}"
            )
            self.status.progress = f"{idx}/{len(all_jobs)} NLP processed"

            # Salary extraction from description (only if no pay already)
            if not job.get("pay") and job.get("description"):
                self._log("  Extracting salary from description via Mistral...")
                try:
                    result = extract_salary_from_description(str(job["description"]))
                    pay_text = result.get("pay_text")
                    if pay_text:
                        job["pay"] = pay_text
                        self._log(f"  Salary found: {pay_text}", "success")
                except Exception as exc:
                    self._log(f"  Salary NLP failed: {exc}", "warn")

            # Technical skill filter
            raw_attrs = job.pop("raw_attributes", None)
            if raw_attrs:
                self._log(f"  Filtering {len(raw_attrs)} attributes via Mistral...")
                try:
                    job["technical_skills"] = filter_technical_skills(raw_attrs)
                    self._log(f"  Skills: {job['technical_skills']}", "success")
                except Exception as exc:
                    self._log(f"  Skill filter NLP failed: {exc}", "warn")

            job["status"] = "nlp_done"
            self._backend.upsert_scraped_job(job)

        self._log("Phase 3 complete. NLP enrichment done.", "success")
        self.status.state = "completed"
        self.status.phase = "Completed"
        self.status.progress = f"{len(all_jobs)} jobs fully processed"
        self._log(f"Scrape finished. {len(all_jobs)} jobs saved.", "success")

