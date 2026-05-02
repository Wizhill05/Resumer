from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

import chompjs
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager


def extract_js_object(text: str, marker: str) -> str | None:
    start_idx = text.find(marker)
    if start_idx == -1:
        return None

    obj_start = text.find("{", start_idx)
    if obj_start == -1:
        return None

    brace_count = 0
    in_string: str | bool = False
    escape = False

    for i in range(obj_start, len(text)):
        char = text[i]
        if escape:
            escape = False
            continue
        if char == "\\":
            escape = True
            continue
        if char in {"\"", "'"}:
            if not in_string:
                in_string = char
            elif in_string == char:
                in_string = False
            continue

        if not in_string:
            if char == "{":
                brace_count += 1
            elif char == "}":
                brace_count -= 1
                if brace_count == 0:
                    return text[obj_start : i + 1]
    return None


def parse_indeed_html(file_path: str | Path) -> list[dict[str, Any]]:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"{path} not found.")

    content = path.read_text(encoding="utf-8")
    jobs, _stats = _parse_indeed_html_content(content)
    return jobs


def parse_indeed_html_with_stats(
    file_path: str | Path,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"{path} not found.")

    content = path.read_text(encoding="utf-8")
    return _parse_indeed_html_content(content)


def _parse_indeed_html_content(content: str) -> tuple[list[dict[str, Any]], dict[str, int]]:
    jobs: list[dict[str, Any]] = []
    jobs_by_key: dict[str, dict[str, Any]] = {}
    js_count = 0

    def _upsert(job: dict[str, Any]) -> None:
        key = str(job.get("Job Key", "") or "").strip()
        if key and key in jobs_by_key:
            existing = jobs_by_key[key]
            for field in ("Title", "Company", "Location", "Link", "Relative Time", "Salary"):
                current = str(existing.get(field, "") or "").strip()
                incoming = str(job.get(field, "") or "").strip()
                if not current and incoming:
                    existing[field] = incoming
            return
        if key:
            jobs_by_key[key] = job
        jobs.append(job)

    js_text = extract_js_object(
        content, 'window.mosaic.providerData["mosaic-provider-jobcards"]'
    )
    if js_text:
        try:
            data = chompjs.parse_js_object(js_text)
        except Exception as exc:
            raise ValueError(f"Error decoding JavaScript object: {exc}") from exc

        results = data.get("results", [])
        if not results and "metaData" in data:
            model = data["metaData"].get("mosaicProviderJobCardsModel", {})
            results = model.get("results", [])
        js_count = len(results)

        for result in results:
            job_key = str(result.get("jobkey") or "").strip()
            salary_snippet = result.get("salarySnippet", {})
            salary = (
                str(salary_snippet.get("text", "")).strip()
                if isinstance(salary_snippet, dict)
                else ""
            )
            job_type = ""
            job_types = result.get("jobTypes", [])
            if isinstance(job_types, list) and job_types:
                job_type = ", ".join(str(jt) for jt in job_types)
            _upsert(
                {
                    "Title": str(result.get("displayTitle") or result.get("title") or "").strip(),
                    "Company": str(result.get("company") or "").strip(),
                    "Location": str(result.get("formattedLocation") or "").strip(),
                    "Job Key": job_key,
                    "Link": f"https://in.indeed.com/viewjob?jk={job_key}" if job_key else "",
                    "Relative Time": str(result.get("formattedRelativeTime") or "").strip(),
                    "Salary": salary,
                    "Job Type": job_type,
                }
            )

    dom_jobs = _parse_indeed_feed_cards(content)
    for job in dom_jobs:
        _upsert(job)

    if not jobs:
        raise ValueError("Could not find parseable jobs in HTML.")
    stats = {
        "js_results": js_count,
        "dom_results": len(dom_jobs),
        "merged_results": len(jobs),
    }
    return jobs, stats


def _collapse_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _job_key_from_href(href: str) -> str:
    href = (href or "").strip()
    if not href:
        return ""
    query = parse_qs(urlparse(href).query)
    values = query.get("jk")
    if values:
        return str(values[0]).strip()
    return ""


def _extract_salary_from_meta_values(values: list[str]) -> str:
    for value in values:
        lowered = value.lower()
        if any(token in value for token in ("₹", "$", "€", "£")):
            return value
        if "salary" in lowered:
            return value
        if " a month" in lowered or " a year" in lowered or " per " in lowered:
            return value
    return ""


def _extract_job_type_from_meta_values(values: list[str]) -> str:
    types = ("full-time", "full time", "part-time", "part time", "contract", 
             "internship", "fresher", "temporary", "permanent", "regular / permanent", "fresher")
    for value in values:
        lowered = value.lower()
        if any(t in lowered for t in types):
            return value
    return ""


def _parse_indeed_feed_cards(content: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(content, "lxml")
    feed_cards = soup.select(".jobsearch-RecentSearchesMixedJobFeed .job_seen_beacon")
    jobs: list[dict[str, Any]] = []

    for card in feed_cards:
        link = card.select_one("a.jcs-JobTitle[data-jk], a.jcs-JobTitle, a[data-jk]")
        if not link:
            continue

        span = link.select_one("span[title]")
        title = ""
        if span and span.get("title"):
            title = _collapse_whitespace(str(span.get("title")))
        if not title:
            title = _collapse_whitespace(link.get_text(" ", strip=True))

        company_node = card.select_one("[data-testid='company-name']")
        location_node = card.select_one("[data-testid='text-location']")
        date_node = card.select_one(
            "[data-testid='myJobsStateDate'], [data-testid='job-age'], .date"
        )

        meta_values_raw = [
            _collapse_whitespace(node.get_text(" ", strip=True))
            for node in card.select(".jobMetaDataGroup li, .jobMetaDataGroup div")
        ]
        meta_values: list[str] = []
        for value in meta_values_raw:
            if value and value not in meta_values:
                meta_values.append(value)

        job_key = _collapse_whitespace(str(link.get("data-jk") or ""))
        if not job_key:
            job_key = _job_key_from_href(str(link.get("href") or ""))
        if not job_key:
            link_id = _collapse_whitespace(str(link.get("id") or ""))
            if link_id.startswith("job_"):
                job_key = link_id.replace("job_", "", 1)
            elif link_id.startswith("sj_"):
                job_key = link_id.replace("sj_", "", 1)

        relative_time = _collapse_whitespace(date_node.get_text(" ", strip=True)) if date_node else ""
        salary = _extract_salary_from_meta_values(meta_values)
        job_type = _extract_job_type_from_meta_values(meta_values)

        jobs.append(
            {
                "Title": title,
                "Company": _collapse_whitespace(company_node.get_text(" ", strip=True))
                if company_node
                else "",
                "Location": _collapse_whitespace(location_node.get_text(" ", strip=True))
                if location_node
                else "",
                "Job Key": job_key,
                "Link": f"https://in.indeed.com/viewjob?jk={job_key}" if job_key else "",
                "Relative Time": relative_time,
                "Salary": salary,
                "Job Type": job_type,
            }
        )

    return jobs


def _extract_indeed_apply_url(page_html: str) -> str:
    """Extract the direct apply URL from a scraped Indeed job page."""
    soup = BeautifulSoup(page_html, "lxml")
    # Prefer the main apply button
    for selector in (
        "a[data-testid='applyButtonLink']",
        "a#indeedApplyButton",
        "button[data-testid='applyButtonLink']",
        ".jobsearch-IndeedApplyButton-contentWrapper a",
        "a[href*='apply']",
    ):
        node = soup.select_one(selector)
        if node:
            href = str(node.get("href", "")).strip()
            if href and href.startswith("http"):
                return href
    # Fallback: first external apply link
    for a in soup.select("a[href]"):
        href = str(a.get("href", "")).strip()
        text = a.get_text(strip=True).lower()
        if "apply" in text and href.startswith("http") and "indeed.com" not in href:
            return href
    return ""


def _extract_indeed_description(page_html: str) -> str:
    soup = BeautifulSoup(page_html, "lxml")
    selectors = (
        "#jobDescriptionText",
        "[data-testid='jobsearch-JobComponent-description']",
        ".jobsearch-JobComponent-description",
        "[data-testid='jobDescriptionText']",
    )
    for selector in selectors:
        node = soup.select_one(selector)
        if node:
            text = node.get_text("\n", strip=True)
            if text:
                return text
    return ""


def _extract_indeed_attributes(page_html: str) -> list[str]:
    soup = BeautifulSoup(page_html, "lxml")
    attributes = []
    # Try multiple selectors for job details/attributes
    nodes = soup.select("#jobDetailsSection ul li, [data-testid='jobsearch-JobDescriptionSection-jobAttributes'] ul li")
    if not nodes:
        nodes = soup.select(".jobsearch-JobDescriptionSection-sectionItem")
    
    for node in nodes:
        text = _collapse_whitespace(node.get_text(" ", strip=True))
        if text and text not in attributes:
            attributes.append(text)
    return attributes


def _extract_experience_years(text: str) -> tuple[int | None, int | None]:
    import re
    # Match phrases like "2 years", "2-5 years", "minimum 3 years"
    match = re.search(r"(\d+)\s*(?:[-to]\s*\d+\s*)?(?:years?|yrs?)", text, re.IGNORECASE)
    if match:
        val = int(match.group(1))
        return val, 1
    if re.search(r"fresher|no experience", text, re.IGNORECASE):
        return 0, 0
    return None, None


def _is_human_check_page(page_html: str) -> bool:
    lowered = page_html.lower()
    markers = (
        "verify you are a human",
        "complete the security check",
        "captcha",
        "unusual traffic",
        "enable javascript and cookies",
        "cloudflare",
    )
    return any(marker in lowered for marker in markers)


def _is_unavailable_job_page(page_html: str) -> bool:
    lowered = page_html.lower()
    markers = (
        "we can’t find this page",
        "we can't find this page",
        "page doesn't exist",
        "page does not exist",
        "isn’t available right now",
        "isn't available right now",
        "return home",
    )
    return any(marker in lowered for marker in markers)


def _build_chrome_driver() -> webdriver.Chrome:
    options = Options()
    options.add_argument("--start-maximized")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--no-sandbox")
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=options)


def is_human_check_page_source(page_html: str) -> bool:
    return _is_human_check_page(page_html)


class HumanVerificationRequired(RuntimeError):
    """Raised when anti-bot verification appears during scraping."""


def start_indeed_verification_session(
    jobs: list[dict[str, Any]],
    *,
    log: Callable[[str], None] | None = None,
) -> webdriver.Chrome:
    if not jobs:
        raise ValueError("No parsed jobs available. Run Step 1 first.")

    first_url = str(jobs[0].get("Link", "") or "")
    if not first_url:
        raise ValueError("First parsed job has no URL.")

    driver = _build_chrome_driver()
    driver.get(first_url)
    if log:
        log("Browser opened on first job page for human verification.")
        if _is_human_check_page(driver.page_source):
            log("Human verification detected. Complete CAPTCHA in browser, then continue.")
        else:
            log("No CAPTCHA detected on first page. You can continue to scraping.")
    return driver


def scrape_indeed_descriptions(
    jobs: list[dict[str, Any]],
    *,
    wait_seconds: int = 120,
    log: Callable[[str], None] | None = None,
) -> list[dict[str, Any]]:
    if not jobs:
        return jobs

    def _log(message: str) -> None:
        if log:
            log(message)

    driver = _build_chrome_driver()
    try:
        total = len(jobs)
        for idx, job in enumerate(jobs, start=1):
            url = str(job.get("Link", "") or "")
            if not url:
                job["Description"] = "FAILED"
                _log(f"[{idx}/{total}] Missing URL; marked as FAILED.")
                continue

            try:
                driver.get(url)
            except WebDriverException:
                job["Description"] = "FAILED"
                _log(f"[{idx}/{total}] Browser failed to open job page; marked as FAILED.")
                continue

            _log(f"[{idx}/{total}] Opened job page in browser.")

            page_source = driver.page_source
            if _is_human_check_page(page_source):
                _log(
                    "Human verification detected in browser. Complete it there; scraping will continue automatically."
                )
            if _is_unavailable_job_page(page_source):
                job["Description"] = "FAILED"
                _log(f"[{idx}/{total}] Job page is unavailable/closed; marked as FAILED.")
                continue

            try:
                WebDriverWait(driver, wait_seconds).until(
                    lambda d: (
                        not _is_human_check_page(d.page_source)
                        and (
                            bool(_extract_indeed_description(d.page_source))
                            or _is_unavailable_job_page(d.page_source)
                        )
                    )
                )
            except TimeoutException:
                pass

            if _is_unavailable_job_page(driver.page_source):
                job["Description"] = "FAILED"
                _log(f"[{idx}/{total}] Job page is unavailable/closed; marked as FAILED.")
                continue

            description = _extract_indeed_description(driver.page_source)
            if description:
                job["Description"] = description
                _log(f"[{idx}/{total}] Description captured.")
            else:
                job["Description"] = "FAILED"
                _log(f"[{idx}/{total}] Description not found; marked as FAILED.")

        return jobs
    finally:
        driver.quit()


def scrape_indeed_descriptions_with_driver(
    jobs: list[dict[str, Any]],
    *,
    driver: webdriver.Chrome,
    wait_seconds: int = 120,
    log: Callable[[str], None] | None = None,
    skip_completed: bool = True,
) -> list[dict[str, Any]]:
    if not jobs:
        return jobs

    def _log(message: str) -> None:
        if log:
            log(message)

    total = len(jobs)
    for idx, job in enumerate(jobs, start=1):
        if skip_completed:
            existing_description = str(job.get("Description", "") or job.get("description", "") or "").strip()
            if existing_description and existing_description != "FAILED":
                continue

        # Support both raw parsed keys ("Link") and DB keys ("source_url")
        url = str(job.get("Link", "") or job.get("source_url", "") or "").strip()
        if not url:
            job["Description"] = "FAILED"
            _log(f"[{idx}/{total}] Missing URL; marked as FAILED.")
            continue

        try:
            driver.get(url)
        except WebDriverException:
            job["Description"] = "FAILED"
            _log(f"[{idx}/{total}] Browser failed to open job page; marked as FAILED.")
            continue

        _log(f"[{idx}/{total}] Opened job page in browser.")
        page_source = driver.page_source
        if _is_human_check_page(page_source):
            raise HumanVerificationRequired(
                f"Human verification required at job {idx}/{total}. Complete it in browser and run Step 2B again."
            )
        if _is_unavailable_job_page(page_source):
            job["Description"] = "FAILED"
            _log(f"[{idx}/{total}] Job page is unavailable/closed; marked as FAILED.")
            continue

        try:
            WebDriverWait(driver, wait_seconds).until(
                lambda d: (
                    not _is_human_check_page(d.page_source)
                    and (
                        bool(_extract_indeed_description(d.page_source))
                        or _is_unavailable_job_page(d.page_source)
                    )
                )
            )
        except TimeoutException:
            pass

        page_source = driver.page_source
        if _is_human_check_page(page_source):
            raise HumanVerificationRequired(
                f"Human verification required at job {idx}/{total}. Complete it in browser and run Step 2B again."
            )
        if _is_unavailable_job_page(page_source):
            job["Description"] = "FAILED"
            _log(f"[{idx}/{total}] Job page is unavailable/closed; marked as FAILED.")
            continue

        description = _extract_indeed_description(page_source)
        apply_url = _extract_indeed_apply_url(page_source)
        attributes = _extract_indeed_attributes(page_source)
        
        # Determine experience from attributes
        exp_req = None
        req_exp = None
        for attr in attributes:
            e_val, req = _extract_experience_years(attr)
            if e_val is not None:
                exp_req = e_val
                req_exp = req
                break

        if description:
            job["Description"] = description
            _log(f"[{idx}/{total}] Description captured.")
        else:
            job["Description"] = "FAILED"
            _log(f"[{idx}/{total}] Description not found; marked as FAILED.")

        # Store apply URL back so upsert_jobs can pick it up
        if apply_url:
            job["Apply URL"] = apply_url
            _log(f"[{idx}/{total}] Apply URL captured.")
            
        job["Attributes"] = attributes
        if exp_req is not None:
            job["experience_required"] = exp_req
        if req_exp is not None:
            job["requires_experience"] = req_exp

    return jobs


def parse_and_scrape_indeed_html(
    file_path: str | Path,
    *,
    wait_seconds: int = 120,
    log: Callable[[str], None] | None = None,
) -> list[dict[str, Any]]:
    jobs = parse_indeed_html(file_path)
    return scrape_indeed_descriptions(jobs, wait_seconds=wait_seconds, log=log)
