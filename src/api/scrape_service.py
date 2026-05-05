"""
scrape_service.py
=================
Background service that runs the Indeed scraping pipeline inside a thread,
emitting live status/logs to the caller.  Persists results into the DB
after each phase via ``LocalBackend``.

Phases:
  1 — Scrape basic job cards from search-results pages.
  2 — Deep-fetch every job's individual page (description + attributes).
  3 — NLP enrichment (salary normalisation + skill filter via Mistral).
"""

from __future__ import annotations

import json
import os
import random
import re
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ── Path bootstrap ────────────────────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()
load_dotenv(_PROJECT_ROOT / ".env.local", override=True)

if os.getenv("MISTRAL_API_KEY"):
    os.environ["MISTRAL_API_KEY"] = os.getenv("MISTRAL_API_KEY")

# ── Lazy imports for scraping libs ────────────────────────────────────────────
# We import these inside methods so the module loads quickly and doesn't fail
# if scrapling is not installed in the current environment.


# ── Data classes ──────────────────────────────────────────────────────────────


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


class ScrapeService:
    """Manages a single scraping run in a background thread."""

    MAX_LOG_LINES = 3000

    def __init__(self, backend: Any) -> None:
        self._backend = backend
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

        self.status = ScrapeStatus()
        self.logs: list[ScrapeLogEntry] = []

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(
        self,
        *,
        query: str = "ai engineer",
        location: str = "Bengaluru, Karnataka",
        job_type: str = "",
        radius: str = "25",
        fromage: str = "",
        target_count: int = 50,
        salary_filter: str = "",
        direct_url: str = "",
    ) -> None:
        if self.is_running:
            raise RuntimeError("A scrape run is already in progress")

        self._stop_event.clear()
        self.logs = []
        self.status = ScrapeStatus(state="starting")

        self._thread = threading.Thread(
            target=self._run,
            kwargs=dict(
                query=query,
                location=location,
                job_type=job_type,
                radius=radius,
                fromage=fromage,
                target_count=target_count,
                salary_filter=salary_filter,
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

    # ── Logging helper ────────────────────────────────────────────────────────

    def _log(self, text: str, level: str = "info") -> None:
        with self._lock:
            self.logs.append(ScrapeLogEntry(ts=time.time(), text=text, level=level))
            if len(self.logs) > self.MAX_LOG_LINES:
                self.logs = self.logs[-self.MAX_LOG_LINES:]

    # ── The main pipeline ─────────────────────────────────────────────────────

    def _run(
        self,
        *,
        query: str,
        location: str,
        job_type: str,
        radius: str,
        fromage: str,
        target_count: int,
        salary_filter: str,
        direct_url: str,
    ) -> None:
        session_id = uuid.uuid4().hex[:12]

        try:
            self._run_pipeline(
                query=query,
                location=location,
                job_type=job_type,
                radius=radius,
                fromage=fromage,
                target_count=target_count,
                salary_filter=salary_filter,
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
        query: str,
        location: str,
        job_type: str,
        radius: str,
        fromage: str,
        target_count: int,
        salary_filter: str,
        direct_url: str,
        session_id: str,
    ) -> None:
        from scrapling.fetchers import StealthySession
        from scrapling.parser import Selector
        from pydantic import BaseModel
        from litellm import completion

        # ── Build URL ─────────────────────────────────────────────────────────
        import urllib.parse

        JOB_TYPES = {
            "fulltime": "fulltime",
            "parttime": "parttime",
            "internship": "internship",
            "contract": "contract",
            "temporary": "temporary",
            "permanent": "permanent",
            "fresher": "fresher",
        }

        is_single_job_direct = False
        single_job_id = ""

        SC_CODES = {
            "internship": "0kf:attr(VDTG7);",
            "fulltime": "0kf:attr(DSQF7);",
            "parttime": "0kf:attr(1JR19);",
            "contract": "0kf:attr(8S2R9);",
            "temporary": "0kf:attr(12B4P);",
            "fresher": "0kf:attr(FCH);",
        }

        if direct_url.strip():
            # If it's a specific job view
            if "viewjob?jk=" in direct_url or "&vjk=" in direct_url:
                is_single_job_direct = True
                # Extract JK
                import urllib.parse as uparse
                parsed = uparse.urlparse(direct_url)
                qs = uparse.parse_qs(parsed.query)
                if "jk" in qs:
                    single_job_id = qs["jk"][0]
                elif "vjk" in qs:
                    single_job_id = qs["vjk"][0]
                
                url_base = direct_url
            else:
                # It's a search URL
                url_base = direct_url.strip()
        else:
            params: list[tuple[str, str]] = []
            if query.strip():
                params.append(("q", query.strip()))
            if location.strip():
                params.append(("l", location.strip()))
            if job_type and job_type in JOB_TYPES:
                params.append(("jt", JOB_TYPES[job_type]))
                if job_type in SC_CODES:
                    params.append(("sc", SC_CODES[job_type]))
            if radius:
                params.append(("radius", radius))
            if fromage:
                params.append(("fromage", fromage))
            if salary_filter.strip():
                sf = salary_filter.strip()
                if not sf.endswith("+"):
                    sf += "+"
                params.append(("salaryType", sf))

            url_base = "https://in.indeed.com/jobs?" + urllib.parse.urlencode(params)

        self._log(f"Scrape session: {session_id}")
        self._log(f"Direct URL provided: {bool(direct_url.strip())}")
        self._log("=" * 50, "event")
        self._log(f"TARGET URL: {url_base}", "event")
        self._log("=" * 50, "event")

        chrome_profile = _PROJECT_ROOT / "src" / "scraping" / "output" / "chrome_profile"
        chrome_profile.mkdir(parents=True, exist_ok=True)

        # ── NLP helpers (inline to capture imports) ───────────────────────────

        class SalaryExtraction(BaseModel):
            min_salary_inr_per_year: float | None
            max_salary_inr_per_year: float | None

        class SkillFilter(BaseModel):
            technical_skills: list[str]

        def normalize_salary(pay_str: str) -> dict:
            if not os.environ.get("MISTRAL_API_KEY"):
                return {"min_salary_inr_per_year": None, "max_salary_inr_per_year": None}
            try:
                response = completion(
                    model="mistral/ministral-3b-2512",
                    messages=[
                        {"role": "system", "content": "You are a helpful assistant that converts salary strings into normalized INR per year. If given a range, extract min and max. If given a single number, set both min and max to that number. Assume standard working hours for hourly rates. 1 month = 12 months/year. Convert foreign currencies to INR at current approximate exchange rates."},
                        {"role": "user", "content": f"Extract normalized salary in INR per year from: {pay_str}"},
                    ],
                    response_format=SalaryExtraction,
                )
                return json.loads(response.choices[0].message.content)
            except Exception as e:
                self._log(f"Salary NLP failed for '{pay_str}': {e}", "warn")
                return {"min_salary_inr_per_year": None, "max_salary_inr_per_year": None}

        def filter_technical_skills(attributes: list[str]) -> list[str]:
            if not attributes:
                return []
            if not os.environ.get("MISTRAL_API_KEY"):
                return attributes
            try:
                response = completion(
                    model="mistral/ministral-3b-2512",
                    messages=[
                        {"role": "system", "content": "You are a helpful assistant that filters a list of job attributes and returns ONLY the hard technical skills (e.g., programming languages, frameworks, tools, databases). Exclude soft skills like 'English', 'Communication', 'Teamwork', 'Leadership', 'Problem Solving'. Also Exclude noise data like 'CI\\\\u002FCD'"},
                        {"role": "user", "content": f"Filter these attributes to only technical skills: {json.dumps(attributes)}"},
                    ],
                    response_format=SkillFilter,
                )
                result = json.loads(response.choices[0].message.content)
                return result.get("technical_skills", [])
            except Exception as e:
                self._log(f"Skill filter NLP failed: {e}", "warn")
                return attributes

        def extract_text(element) -> str:
            if not element:
                return ""
            texts = element.xpath(".//text()").getall()
            return " ".join("".join(texts).split())

        # ── PHASE 1: Basic scrape ─────────────────────────────────────────────
        all_jobs: list[dict] = []
        
        # Load existing job IDs from the database to avoid re-scraping
        existing_jobs = self._backend.list_scraped_jobs()
        db_seen_ids = {j["id"] for j in existing_jobs if "id" in j}
        
        if is_single_job_direct and single_job_id:
            if single_job_id in db_seen_ids:
                self._log("=" * 50, "event")
                self._log(f"SKIPPING — Direct job {single_job_id} already exists in database.", "event")
                self._log("=" * 50, "event")
                self.status.state = "completed"
                self.status.phase = "Completed"
                self.status.progress = "0 jobs processed (already exists)"
                return

            self._log("=" * 50, "event")
            self._log(f"SKIPPING PHASE 1 — Direct single job link detected ({single_job_id})", "event")
            self._log("=" * 50, "event")
            
            # Seed the single job to bypass Phase 1
            all_jobs.append({
                "id": single_job_id,
                "link": f"https://in.indeed.com/viewjob?jk={single_job_id}",
                "status": "basic",
                "scrape_session": session_id,
            })
            self.status.total_jobs = 1
        else:
            self.status.state = "phase1"
            self.status.phase = "Phase 1 — Scraping listings"
            self._log("=" * 50, "event")
            self._log("PHASE 1 — Scraping basic job listings", "event")
            self._log("=" * 50, "event")

        seen_ids: set[str] = set()
        start_offset = 0

        with StealthySession(headless=False, user_data_dir=str(chrome_profile)) as session:
            MAX_PAGE_RETRIES = 3
            
            # Run Phase 1 only if not direct single job
            while not is_single_job_direct and len(all_jobs) < target_count:
                if self._stop_event.is_set():
                    self.status.state = "stopped"
                    self._log("Scrape stopped by user.", "warn")
                    return

                url = f"{url_base}&start={start_offset}"
                self._log(f"Fetching page (start={start_offset})...")

                html = None
                for attempt in range(1, MAX_PAGE_RETRIES + 1):
                    try:
                        page = session.fetch(url, network_idle=False, timeout=45_000, google_search=False)
                        if page.status != 200:
                            self._log(f"HTTP {page.status} on attempt {attempt}", "warn")
                            if attempt < MAX_PAGE_RETRIES:
                                time.sleep(random.uniform(5, 10))
                                continue
                            break
                        html = page.html_content
                        break
                    except Exception as e:
                        self._log(f"Page fetch attempt {attempt}/{MAX_PAGE_RETRIES} failed: {e}", "error")
                        if attempt < MAX_PAGE_RETRIES:
                            backoff = random.uniform(6, 12) * attempt
                            self._log(f"Retrying in {backoff:.1f}s...")
                            time.sleep(backoff)

                if html is None:
                    self._log("Could not fetch page after retries. Stopping.", "error")
                    break

                if "jobs" not in html.lower() and "indeed" not in html.lower():
                    self._log("Page doesn't look like Indeed. Possible Cloudflare block.", "warn")
                    break

                # Parse cards
                page_sel = Selector(html)
                job_cards = page_sel.css(".job_seen_beacon")
                jobs_on_page: list[dict] = []

                for card in job_cards:
                    job: dict = {}
                    title_link = card.css(".jcs-JobTitle")
                    if title_link:
                        job["id"] = title_link[0].attrib.get("data-jk", "")
                        href = title_link[0].attrib.get("href", "")
                        job["link"] = f"https://in.indeed.com{href}" if href else ""
                        title_span = title_link[0].css("span[title]")
                        job["title"] = extract_text(title_span[0]) if title_span else extract_text(title_link[0])

                    company_elem = card.css('.company_location [data-testid="company-name"]')
                    if company_elem:
                        job["company"] = extract_text(company_elem[0])

                    location_elem = card.css('.company_location [data-testid="text-location"]')
                    if location_elem:
                        job["location"] = extract_text(location_elem[0])

                    date_elems = card.css('[data-testid="myJobsStateDate"]')
                    if date_elems:
                        job["posted_date"] = extract_text(date_elems[0])
                    else:
                        for sp in card.css("span"):
                            t = extract_text(sp)
                            if "Posted" in t or "posted" in t or "Active" in t:
                                job["posted_date"] = t
                                break

                    metadata_elems = card.css(".metadataContainer li")
                    metadata = [extract_text(el) for el in metadata_elems if extract_text(el)]
                    pay_info = [m for m in metadata if any(c.isdigit() for c in m) and ("a year" in m or "a month" in m or "₹" in m)]
                    if pay_info:
                        raw_pay = pay_info[0]
                        job["pay"] = raw_pay
                        metadata.remove(raw_pay)
                    job["metadata"] = metadata

                    snippet_elem = card.css(".job-snippet li")
                    if snippet_elem:
                        job["snippet"] = [extract_text(el) for el in snippet_elem if extract_text(el)]

                    jobs_on_page.append(job)

                if not jobs_on_page:
                    self._log("No jobs found on page. End of results.", "warn")
                    break

                new_jobs = []
                for j in jobs_on_page:
                    jid = j.get("id")
                    if jid and jid in db_seen_ids:
                        continue  # Skip already scraped jobs
                    if jid and jid not in seen_ids:
                        seen_ids.add(jid)
                        new_jobs.append(j)

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

                start_offset += 10
                delay = random.uniform(3, 7)
                self._log(f"Sleeping {delay:.1f}s...")
                time.sleep(delay)

            # Trim
            if len(all_jobs) > target_count:
                all_jobs = all_jobs[:target_count]

            self._log(f"Phase 1 complete. {len(all_jobs)} basic records.", "success")
            self.status.total_jobs = len(all_jobs)

            # Initialize session details for all basic jobs
            for j in all_jobs:
                j["scrape_session"] = session_id
                j["status"] = "basic"

            if self._stop_event.is_set():
                self.status.state = "stopped"
                self._log("Scrape stopped by user.", "warn")
                return

            # ── PHASE 2: Deep fetch ───────────────────────────────────────────
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

                job_id = job.get("id")
                if not job_id:
                    dropped += 1
                    continue

                self._log(f"[{idx}/{len(all_jobs)}] Deep-fetching: {job_id}")
                self.status.progress = f"{idx}/{len(all_jobs)} deep fetches"
                time.sleep(random.uniform(4.0, 8.0))

                deep_url = f"https://in.indeed.com/viewjob?jk={job_id}"
                details = None
                for attempt in range(1, 4):
                    try:
                        dp = session.fetch(deep_url, network_idle=False, timeout=45_000, google_search=False)
                        if dp.status == 403:
                            self._log(f"HTTP 403 on attempt {attempt} — bot challenge", "warn")
                            if attempt < 3:
                                time.sleep(random.uniform(8, 15))
                            continue
                        if dp.status != 200:
                            self._log(f"HTTP {dp.status} on attempt {attempt}", "warn")
                            if attempt < 3:
                                time.sleep(random.uniform(3, 6))
                            continue

                        dp_html = dp.html_content
                        dp_sel = Selector(dp_html)
                        details = {}
                        desc_elem = dp_sel.css("#jobDescriptionText")
                        if desc_elem:
                            details["description"] = extract_text(desc_elem[0])
                        
                        if is_single_job_direct:
                            details["title"] = extract_text(dp_sel.css('h1'))
                            details["company"] = extract_text(dp_sel.css('[data-testid="inlineHeader-companyName"]'))
                            details["location"] = extract_text(dp_sel.css('[data-testid="inlineHeader-companyLocation"]'))
                            
                            pay_elem = dp_sel.css('#salaryInfoAndJobType')
                            if pay_elem:
                                details["pay"] = extract_text(pay_elem[0])
                        
                        pattern = re.compile(r'"__typename":"JobAttribute","key":"[^"]+","label":"([^"]+)"')
                        matches = pattern.findall(dp_html)
                        if matches:
                            details["raw_attributes"] = list(set(matches))
                        break
                    except Exception as e:
                        self._log(f"Deep fetch attempt {attempt}/3 failed: {e}", "error")
                        if attempt < 3:
                            time.sleep(random.uniform(4, 8) * attempt)

                if details is None:
                    self._log(f"Dropping job {job_id} (deep fetch failed).", "warn")
                    dropped += 1
                    continue

                job.update(details)
                job["status"] = "enriched"
                enriched_jobs.append(job)
                
                # Incrementally save to DB so UI updates during the long Phase 2
                self._backend.upsert_scraped_job(job)

            all_jobs = enriched_jobs
            self.status.enriched_jobs = len(all_jobs)
            self._log(f"Phase 2 complete. {len(all_jobs)} enriched, {dropped} dropped.", "success")

        # Session closed — browser no longer needed

        if self._stop_event.is_set():
            self.status.state = "stopped"
            self._log("Scrape stopped by user.", "warn")
            return

        # ── PHASE 3: NLP enrichment ───────────────────────────────────────────
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

            self._log(f"[{idx}/{len(all_jobs)}] NLP: {job.get('title', '?')} @ {job.get('company', '?')}")
            self.status.progress = f"{idx}/{len(all_jobs)} NLP processed"

            # Salary
            if job.get("pay"):
                safe_pay = job["pay"].encode("ascii", "ignore").decode("ascii")
                self._log(f"  Normalizing salary: {safe_pay}")
                normalized = normalize_salary(job["pay"])
                if normalized:
                    job["min_salary_inr"] = normalized.get("min_salary_inr_per_year")
                    job["max_salary_inr"] = normalized.get("max_salary_inr_per_year")

            # Skills
            raw_attrs = job.pop("raw_attributes", None)
            if raw_attrs:
                self._log(f"  Filtering {len(raw_attrs)} attributes via Mistral...")
                job["technical_skills"] = filter_technical_skills(raw_attrs)

            job["status"] = "nlp_done"
            
            # Save immediately so UI updates incrementally
            self._backend.upsert_scraped_job(job)

        self._log("Phase 3 complete. NLP enrichment done.", "success")

        self.status.state = "completed"
        self.status.phase = "Completed"
        self.status.progress = f"{len(all_jobs)} jobs fully processed"
        self._log(f"Scrape finished. {len(all_jobs)} jobs saved.", "success")
