"""
crawl_linkedin.py
=================
Three-phase LinkedIn scraper CLI mirroring the Indeed pipeline:

  Phase 1 - Search crawl: collect lightweight job cards.
  Phase 2 - Deep fetch: load each job page and extract full description + attributes.
  Phase 3 - NLP enrichment: extract salary text and filter technical skills via Mistral.

Usage:
    uv run python src\\linkedin_scraping\\crawl_linkedin.py
    uv run python src\\linkedin_scraping\\crawl_linkedin.py --target-count 30 --headless
    uv run python src\\linkedin_scraping\\crawl_linkedin.py --keywords "Backend Engineer" --location "India" --experience-levels 1,2 --work-types 2,3
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
import urllib.parse
from pathlib import Path

from dotenv import load_dotenv
from litellm import completion
from pydantic import BaseModel
from scrapling.fetchers import StealthySession
from scrapling.parser import Selector

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = Path(__file__).parent / "output"
DEFAULT_OUTPUT_JSON = OUTPUT_DIR / "linkedin_jobs.json"
CHROME_PROFILE_DIR = PROJECT_ROOT / "src" / "scraping" / "output" / "chrome_profile"
DEFAULT_SEARCH_BASE_URL = "https://www.linkedin.com/jobs/search/"

POSTED_WITHIN_MAP = {
    "24h": "r86400",
    "3d": "r259200",
    "7d": "r604800",
    "14d": "r1209600",
    "30d": "r2592000",
}


load_dotenv(PROJECT_ROOT / ".env")
load_dotenv(PROJECT_ROOT / ".env.local", override=True)
if os.getenv("MISTRAL_API_KEY"):
    os.environ["MISTRAL_API_KEY"] = os.getenv("MISTRAL_API_KEY")


class SalaryFromDescriptionExtraction(BaseModel):
    pay_text: str | None


class SkillFilter(BaseModel):
    technical_skills: list[str]


def extract_salary_from_description(description: str) -> dict:
    """Extract salary text directly from description."""
    if not os.environ.get("MISTRAL_API_KEY"):
        return {"pay_text": None}

    desc = " ".join(str(description).split()).strip()
    if not desc:
        return {"pay_text": None}

    # Keep prompts bounded while preserving relevant salary sections.
    desc_for_model = desc[:8000]
    try:
        response = completion(
            model="mistral/ministral-3b-2512",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You extract compensation from job descriptions. Return pay_text "
                        "only when explicit compensation is present. If no explicit salary "
                        "or pay range is found, return null for pay_text."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Extract compensation details from this job description. "
                        f"Description: {desc_for_model}"
                    ),
                },
            ],
            response_format=SalaryFromDescriptionExtraction,
        )
        payload = json.loads(response.choices[0].message.content)
        return {"pay_text": payload.get("pay_text")}
    except Exception as exc:
        print(f"[!] Salary-from-description NLP failed: {exc}", file=sys.stderr)
        return {"pay_text": None}


def filter_technical_skills(attributes: list[str]) -> list[str]:
    """Keep only hard technical skills using Mistral."""
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
                    "content": (
                        "You are a helpful assistant that filters a list of job attributes "
                        "and returns ONLY hard technical skills (languages, frameworks, "
                        "tools, databases, platforms). Exclude soft skills and noise."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Filter these attributes to only technical skills: "
                        f"{json.dumps(attributes)}"
                    ),
                },
            ],
            response_format=SkillFilter,
        )
        payload = json.loads(response.choices[0].message.content)
        return payload.get("technical_skills", [])
    except Exception as exc:
        print(f"[!] Skill filter NLP failed: {exc}", file=sys.stderr)
        return attributes


def extract_text(element) -> str:
    """Recursively extract and normalize text from a Selector element."""
    if not element:
        return ""

    node = element[0] if isinstance(element, list) else element
    texts = node.xpath(".//text()").getall()
    return " ".join("".join(texts).split())


def first_text(container, selectors: list[str]) -> str:
    """Try selectors in order and return first non-empty extracted text."""
    for selector in selectors:
        matches = container.css(selector)
        if matches:
            text = extract_text(matches[0])
            if text:
                return text
    return ""


def unique_clean(values: list[str]) -> list[str]:
    """Normalize and deduplicate text values while preserving order."""
    seen: set[str] = set()
    cleaned: list[str] = []
    for raw in values:
        value = " ".join(str(raw).split()).strip()
        if not value:
            continue
        if value in seen:
            continue
        seen.add(value)
        cleaned.append(value)
    return cleaned


def split_csv(value: str) -> list[str]:
    """Split comma-separated values and remove empties."""
    return [part.strip() for part in str(value).split(",") if part.strip()]


def parse_extra_params(pairs: list[str]) -> list[tuple[str, str]]:
    """Parse repeated key=value extra params from CLI."""
    parsed: list[tuple[str, str]] = []
    for pair in pairs:
        if "=" not in pair:
            raise ValueError(f"Invalid --extra-param '{pair}'. Use key=value format.")
        key, value = pair.split("=", maxsplit=1)
        key = key.strip()
        value = value.strip()
        if not key:
            raise ValueError(f"Invalid --extra-param '{pair}'. Key cannot be empty.")
        parsed.append((key, value))
    return parsed


def build_linkedin_search_url(
    *,
    base_url: str = DEFAULT_SEARCH_BASE_URL,
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
    origin: str = "JOB_SEARCH_PAGE_JOB_FILTER",
    alert_action: str = "viewjobs",
    current_job_id: str = "",
    spell_correction_enabled: bool = True,
    extra_params: list[tuple[str, str]] | None = None,
) -> str:
    """Build a LinkedIn jobs search URL from filter values."""
    params: list[tuple[str, str]] = []

    if alert_action.strip():
        params.append(("alertAction", alert_action.strip()))
    if current_job_id.strip():
        params.append(("currentJobId", current_job_id.strip()))
    if distance.strip():
        params.append(("distance", distance.strip()))
    if geo_id.strip():
        params.append(("geoId", geo_id.strip()))
    if keywords.strip():
        params.append(("keywords", keywords.strip()))
    if location.strip():
        params.append(("location", location.strip()))
    if origin.strip():
        params.append(("origin", origin.strip()))
    if sort_by.strip():
        params.append(("sortBy", sort_by.strip()))
    params.append(("spellCorrectionEnabled", "true" if spell_correction_enabled else "false"))

    exp_values = split_csv(experience_levels)
    if exp_values:
        params.append(("f_E", ",".join(exp_values)))

    wt_values = split_csv(work_types)
    if wt_values:
        params.append(("f_WT", ",".join(wt_values)))

    jt_values = split_csv(job_types)
    if jt_values:
        params.append(("f_JT", ",".join(jt_values)))

    posted_value = posted_within.strip().lower()
    if posted_value:
        params.append(("f_TPR", POSTED_WITHIN_MAP.get(posted_value, posted_within.strip())))

    if salary_tag.strip():
        params.append(("f_SB2", salary_tag.strip()))

    if easy_apply:
        params.append(("f_AL", "true"))

    if extra_params:
        params.extend(extra_params)

    parsed = urllib.parse.urlparse(base_url.strip() or DEFAULT_SEARCH_BASE_URL)
    existing = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    merged = existing + params
    merged = [(k, v) for (k, v) in merged if k and str(v) != ""]
    query = urllib.parse.urlencode(merged)
    return urllib.parse.urlunparse(
        parsed._replace(path=parsed.path or "/jobs/search/", query=query)
    )


def salary_confidence_score(text: str) -> int:
    """Score how likely a text blob is actual compensation info."""
    if not text:
        return -999

    candidate = " ".join(text.split()).strip()
    lower = candidate.lower()
    if not lower:
        return -999

    score = 0
    has_currency = bool(re.search(r"[\u20b9$€£]|\b(inr|usd|eur|gbp)\b", lower))
    has_salary_word = bool(
        re.search(
            r"\b(salary|compensation|pay range|pay|ctc|stipend|remuneration)\b",
            lower,
        )
    )
    has_value_marker = bool(
        re.search(r"\d", lower)
        or re.search(r"\b(lpa|lakh|lakhs|crore|cr|k|m)\b", lower)
    )
    has_period = bool(
        re.search(
            r"\b(per|a)\s+(year|annum|month|hour|day)\b|/(year|annum|month|hour|day)\b",
            lower,
        )
    )

    if has_currency:
        score += 5
    if has_salary_word:
        score += 4
    if has_period:
        score += 2
    if has_value_marker:
        score += 1

    if re.search(
        r"\b(ago|applicant|applicants|hiring|early applicant|reposted|views?)\b",
        lower,
    ):
        score -= 6

    # Penalize location-like strings that contain no clear compensation cues.
    if not has_currency and not has_salary_word and re.search(
        r"\b(india|district|karnataka|maharashtra|haryana|tamil nadu|delhi|bengaluru|mumbai|pune|hyderabad|chennai|gurgaon|gurugram)\b",
        lower,
    ):
        score -= 4

    return score


def extract_salary_snippets(text: str) -> list[str]:
    """Extract explicit salary-like fragments from free text."""
    if not text:
        return []

    snippets: list[str] = []
    patterns = (
        r"(?:[\u20b9$€£]|INR|USD|EUR|GBP)\s?\d[\d,]*(?:\.\d+)?(?:\s*(?:-|to)\s*(?:[\u20b9$€£]|INR|USD|EUR|GBP)?\s?\d[\d,]*(?:\.\d+)?)?(?:\s*(?:/|per|a)\s*(?:year|annum|month|hour|day))?",
        r"\b\d+(?:\.\d+)?\s*(?:lpa|lakhs?|lakh|crore|cr)\b(?:\s*(?:-|to)\s*\d+(?:\.\d+)?\s*(?:lpa|lakhs?|lakh|crore|cr))?",
    )
    for pattern in patterns:
        snippets.extend(re.findall(pattern, text, flags=re.I))
    return unique_clean(snippets)


def pick_best_salary(candidates: list[str]) -> str:
    """Pick the most salary-like candidate and reject noisy strings."""
    ranked: list[tuple[int, str]] = []

    for candidate in unique_clean(candidates):
        score = salary_confidence_score(candidate)
        if score >= 5:
            ranked.append((score, candidate))

        for snippet in extract_salary_snippets(candidate):
            snippet_score = salary_confidence_score(snippet)
            if snippet_score >= 5:
                ranked.append((snippet_score, snippet))

    if not ranked:
        return ""

    ranked.sort(key=lambda item: (-item[0], len(item[1])))
    return ranked[0][1]


def extract_job_id(raw: str) -> str:
    """Extract LinkedIn numeric job ID from URL or URN-like strings."""
    if not raw:
        return ""

    for pattern in (
        r"/jobs/view/(\d+)",
        r"jobPosting:(\d+)",
        r"currentJobId=(\d+)",
        r"trkJobId=(\d+)",
    ):
        match = re.search(pattern, raw)
        if match:
            return match.group(1)
    return ""


def with_start_param(url: str, start: int) -> str:
    """Set/replace LinkedIn search pagination param 'start'."""
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    filtered = [(k, v) for k, v in query if k != "start"]
    if start > 0:
        filtered.append(("start", str(start)))
    rebuilt_query = urllib.parse.urlencode(filtered)
    return urllib.parse.urlunparse(parsed._replace(query=rebuilt_query))


def normalize_link(href: str) -> str:
    """Normalize LinkedIn links to absolute URLs."""
    if not href:
        return ""
    absolute = urllib.parse.urljoin("https://www.linkedin.com", href)
    return absolute.split("#", maxsplit=1)[0]


def parse_basic_jobs_from_html(html_content: str) -> list[dict]:
    """Parse lightweight job card records from LinkedIn search HTML."""
    page = Selector(html_content)
    cards = page.css(
        ".base-card, .job-search-card, .job-card-container, "
        "li.jobs-search-results__list-item, li.scaffold-layout__list-item"
    )

    parsed_jobs: list[dict] = []
    for card in cards:
        job: dict = {}

        title_link = (
            card.css("a.base-card__full-link")
            or card.css("a.job-card-list__title")
            or card.css("a.job-search-card__title-link")
            or card.css("a[href*='/jobs/view/']")
        )
        if title_link:
            href = title_link[0].attrib.get("href", "")
            job["link"] = normalize_link(href)
            job["title"] = extract_text(title_link[0])
            job["id"] = extract_job_id(href)

        if not job.get("id"):
            urn = card.attrib.get("data-entity-urn", "") or card.attrib.get("id", "")
            job["id"] = extract_job_id(urn)

        if not job.get("title"):
            job["title"] = first_text(
                card,
                [
                    ".base-search-card__title",
                    ".job-search-card__title",
                    ".job-card-list__title",
                    "h3",
                ],
            )

        job["company"] = first_text(
            card,
            [
                ".base-search-card__subtitle",
                ".job-search-card__subtitle",
                ".job-card-container__company-name",
                ".artdeco-entity-lockup__subtitle",
                "h4",
            ],
        )
        job["location"] = first_text(
            card,
            [
                ".job-search-card__location",
                ".base-search-card__metadata",
                ".job-card-container__metadata-item",
            ],
        )
        job["posted_date"] = first_text(
            card,
            [
                "time",
                ".job-search-card__listdate--new",
                ".job-search-card__listdate",
                ".job-card-container__footer-item",
            ],
        )

        metadata_candidates: list[str] = []
        for selector in (
            ".job-search-card__job-insight",
            ".job-card-container__metadata-item",
            ".job-card-container__metadata-wrapper li",
            ".base-search-card__metadata",
        ):
            for elem in card.css(selector):
                metadata_candidates.append(extract_text(elem))

        metadata = unique_clean(metadata_candidates)
        pay_match = pick_best_salary(metadata)
        if pay_match:
            job["pay"] = pay_match
            metadata = [item for item in metadata if item != pay_match]
        job["metadata"] = metadata

        snippet = first_text(card, [".job-search-card__snippet", ".job-card-container__description"])
        if snippet:
            job["snippet"] = [snippet]

        if not job.get("link") and job.get("id"):
            job["link"] = f"https://www.linkedin.com/jobs/view/{job['id']}/"

        if job.get("id"):
            parsed_jobs.append(job)

    return parsed_jobs


def deep_attribute_candidates(page_sel: Selector, html_content: str) -> list[str]:
    """Extract rich attribute candidates from deep job page."""
    attributes: list[str] = []

    for selector in (
        ".description__job-criteria-list li",
        ".description__job-criteria-text",
        ".job-details-jobs-unified-top-card__job-insight span",
        ".job-details-preferences-and-skills__pill-text",
        ".job-details-preferences-and-skills__pill",
        ".jobs-unified-top-card__job-insight",
    ):
        for elem in page_sel.css(selector):
            attributes.append(extract_text(elem))

    regex_candidates = re.findall(
        r'"(?:skill|name|title|label|seniorityLevel|employmentType)":"([^"]+)"',
        html_content,
    )
    attributes.extend(regex_candidates)

    return unique_clean([a for a in attributes if 1 < len(a) <= 120])


def fetch_deep_job_details(session, job_id: str, max_retries: int = 3) -> dict | None:
    """Fetch detailed job info from LinkedIn job page."""
    url = f"https://www.linkedin.com/jobs/view/{job_id}/"
    print(f"      [*] Deep Fetch: {url}")

    for attempt in range(1, max_retries + 1):
        try:
            page = session.fetch(
                url,
                network_idle=False,
                timeout=45_000,
                google_search=False,
            )
            if page.status in (429, 999):
                print(f"      [!] HTTP {page.status} on attempt {attempt} - throttled.")
                if attempt < max_retries:
                    time.sleep(random.uniform(8, 15))
                continue
            if page.status != 200:
                print(f"      [!] HTTP {page.status} on attempt {attempt}.")
                if attempt < max_retries:
                    time.sleep(random.uniform(3, 6))
                continue

            html = page.html_content
            page_sel = Selector(html)
            details: dict = {}

            details["title"] = first_text(
                page_sel,
                [
                    "h1.top-card-layout__title",
                    "h1.t-24",
                    ".jobs-unified-top-card__job-title h1",
                    "h1",
                ],
            )
            details["company"] = first_text(
                page_sel,
                [
                    ".topcard__org-name-link",
                    ".topcard__flavor a",
                    ".job-details-jobs-unified-top-card__company-name a",
                    ".jobs-unified-top-card__company-name a",
                ],
            )
            details["location"] = first_text(
                page_sel,
                [
                    ".topcard__flavor--bullet",
                    ".job-details-jobs-unified-top-card__bullet",
                    ".jobs-unified-top-card__bullet",
                ],
            )

            details["description"] = first_text(
                page_sel,
                [
                    ".show-more-less-html__markup",
                    ".jobs-description__content",
                    ".jobs-box__html-content",
                    "#job-details",
                ],
            )

            attrs = deep_attribute_candidates(page_sel, html)
            if attrs:
                details["raw_attributes"] = attrs

            pay_candidates: list[str] = []
            for selector in (
                ".compensation__salary",
                ".salary.compensation__salary",
                ".jobs-unified-top-card__job-insight",
                ".job-details-jobs-unified-top-card__job-insight",
                ".description__job-criteria-text",
            ):
                for elem in page_sel.css(selector):
                    pay_candidates.append(extract_text(elem))
            pay_candidates.extend(attrs)
            pay_candidates.extend(extract_salary_snippets(details.get("description", "")))

            pay = pick_best_salary(pay_candidates)
            if pay:
                details["pay"] = pay

            return details
        except Exception as exc:
            print(f"      [!] Deep fetch attempt {attempt}/{max_retries} failed: {exc}")
            if attempt < max_retries:
                backoff = random.uniform(4, 8) * attempt
                print(f"      [*] Retrying in {backoff:.1f}s...")
                time.sleep(backoff)

    print(f"      [!] All {max_retries} attempts failed for job {job_id}. Dropping.")
    return None


def run_nlp_on_job(job: dict) -> dict:
    """Run salary-text extraction + skill filtering over one job record."""
    if (not job.get("pay")) and job.get("description"):
        print("      [NLP] Extracting salary from description via Mistral...")
        from_description = extract_salary_from_description(str(job["description"]))
        extracted_pay_text = from_description.get("pay_text")
        if extracted_pay_text and not job.get("pay"):
            job["pay"] = extracted_pay_text

    raw_attrs = job.pop("raw_attributes", None)
    if raw_attrs:
        print(f"      [NLP] Filtering {len(raw_attrs)} attributes via Mistral...")
        job["technical_skills"] = filter_technical_skills(raw_attrs)

    return job


def save_snapshot(path: Path, jobs: list[dict], note: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(jobs, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[*] {note} saved to {path.resolve()} ({len(jobs)} jobs)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LinkedIn 3-phase scraper CLI")
    parser.add_argument(
        "--target-url",
        default="",
        help="Fully formed LinkedIn jobs/search URL or direct /jobs/view URL",
    )
    parser.add_argument("--keywords", default="Software Engineer", help="Search role/keywords")
    parser.add_argument("--location", default="India", help="Search location text")
    parser.add_argument("--geo-id", default="102713980", help="LinkedIn geoId (e.g. India=102713980)")
    parser.add_argument("--distance", default="25", help="Search radius/distance")
    parser.add_argument(
        "--experience-levels",
        default="1",
        help="Comma list for f_E (1=Internship,2=Entry,3=Associate,4=Mid-Senior,5=Director,6=Executive)",
    )
    parser.add_argument(
        "--work-types",
        default="2,1",
        help="Comma list for f_WT (LinkedIn work type tags, e.g. 2,1)",
    )
    parser.add_argument(
        "--job-types",
        default="",
        help="Comma list for f_JT (F,P,C,T,V,I,O etc.)",
    )
    parser.add_argument(
        "--posted-within",
        default="",
        help="24h|3d|7d|14d|30d or raw f_TPR value",
    )
    parser.add_argument(
        "--salary-tag",
        default="",
        help="LinkedIn salary filter token (f_SB2 value)",
    )
    parser.add_argument("--sort-by", default="R", help="LinkedIn sortBy value (R or DD)")
    parser.add_argument("--easy-apply", action="store_true", help="Filter to Easy Apply jobs (f_AL=true)")
    parser.add_argument(
        "--origin",
        default="JOB_SEARCH_PAGE_JOB_FILTER",
        help="LinkedIn origin param",
    )
    parser.add_argument("--alert-action", default="viewjobs", help="LinkedIn alertAction param")
    parser.add_argument("--current-job-id", default="", help="Optional currentJobId param")
    parser.add_argument(
        "--no-spell-correction",
        action="store_true",
        help="Disable spellCorrectionEnabled URL flag",
    )
    parser.add_argument(
        "--extra-param",
        action="append",
        default=[],
        help="Repeatable custom URL param in key=value format",
    )
    parser.add_argument(
        "--print-url",
        action="store_true",
        help="Print resolved target URL and exit",
    )
    parser.add_argument("--target-count", type=int, default=50, help="Target number of jobs to process")
    parser.add_argument(
        "--output-json",
        default=str(DEFAULT_OUTPUT_JSON),
        help="Output JSON path",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run browser headless (default opens visible browser)",
    )
    parser.add_argument("--max-page-retries", type=int, default=3, help="Retries per listing page")
    parser.add_argument("--max-deep-retries", type=int, default=3, help="Retries per deep job fetch")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    output_path = Path(args.output_json)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    CHROME_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    target_count = max(1, int(args.target_count))
    if str(args.target_url).strip():
        target_url = str(args.target_url).strip()
    else:
        try:
            extra_params = parse_extra_params(list(args.extra_param or []))
        except ValueError as exc:
            print(f"[!] {exc}", file=sys.stderr)
            sys.exit(2)
        target_url = build_linkedin_search_url(
            keywords=args.keywords,
            location=args.location,
            geo_id=args.geo_id,
            distance=args.distance,
            experience_levels=args.experience_levels,
            work_types=args.work_types,
            job_types=args.job_types,
            posted_within=args.posted_within,
            salary_tag=args.salary_tag,
            sort_by=args.sort_by,
            easy_apply=bool(args.easy_apply),
            origin=args.origin,
            alert_action=args.alert_action,
            current_job_id=args.current_job_id,
            spell_correction_enabled=not bool(args.no_spell_correction),
            extra_params=extra_params,
        )

    if args.print_url:
        print(target_url)
        return

    direct_job_id = extract_job_id(target_url) if "/jobs/view/" in target_url else ""
    is_single_job_direct = bool(direct_job_id)

    print(f"\n{'=' * 70}")
    print("  PHASE 1 - Scraping LinkedIn listings")
    print(f"  Target: {target_count} jobs")
    print(f"  URL: {target_url}")
    print(f"  Direct single-job mode: {is_single_job_direct}")
    print(f"{'=' * 70}\n")

    all_jobs: list[dict] = []
    seen_ids: set[str] = set()
    start_offset = 0
    pagination_step = 25

    if is_single_job_direct:
        all_jobs.append(
            {
                "id": direct_job_id,
                "link": f"https://www.linkedin.com/jobs/view/{direct_job_id}/",
                "status": "basic",
            }
        )
        print(f"[*] Direct job provided. Seeded one job: {direct_job_id}")

    with StealthySession(
        headless=bool(args.headless),
        user_data_dir=str(CHROME_PROFILE_DIR),
    ) as session:
        while not is_single_job_direct and len(all_jobs) < target_count:
            page_url = with_start_param(target_url, start_offset)
            print(f"[*] Fetching page (start={start_offset}): {page_url}")

            html = None
            for attempt in range(1, int(args.max_page_retries) + 1):
                try:
                    page = session.fetch(
                        page_url,
                        network_idle=False,
                        timeout=45_000,
                        google_search=False,
                    )
                    if page.status != 200:
                        print(f"[!] HTTP {page.status} on attempt {attempt}.", file=sys.stderr)
                        if attempt < int(args.max_page_retries):
                            time.sleep(random.uniform(5, 10))
                        continue
                    html = page.html_content
                    break
                except Exception as exc:
                    print(
                        f"[!] Page fetch attempt {attempt}/{args.max_page_retries} failed: {exc}",
                        file=sys.stderr,
                    )
                    if attempt < int(args.max_page_retries):
                        backoff = random.uniform(6, 12) * attempt
                        print(f"[*] Retrying in {backoff:.1f}s...")
                        time.sleep(backoff)

            if html is None:
                print("[!] Could not fetch page after retries. Stopping.", file=sys.stderr)
                break

            if "linkedin" not in html.lower():
                print("[!] Page does not look like LinkedIn. Possible challenge/login wall.")
                break

            jobs_on_page = parse_basic_jobs_from_html(html)
            if not jobs_on_page:
                print("[*] No jobs found on page. Reached end or blocked.")
                break

            print(f"[*] Found {len(jobs_on_page)} jobs on page.")
            new_jobs: list[dict] = []
            for job in jobs_on_page:
                job_id = job.get("id", "")
                if job_id and job_id not in seen_ids:
                    seen_ids.add(job_id)
                    new_jobs.append(job)

            if len(new_jobs) < 3:
                print(
                    f"[*] Only {len(new_jobs)} new jobs on page. Stopping as per <3 threshold."
                )
                all_jobs.extend(new_jobs)
                break

            all_jobs.extend(new_jobs)
            print(f"[*] Total unique jobs collected: {len(all_jobs)} / {target_count}")

            if len(all_jobs) >= target_count:
                break

            start_offset += pagination_step
            delay = random.uniform(3, 7)
            print(f"[*] Sleeping {delay:.1f}s to reduce blocks...")
            time.sleep(delay)

        if len(all_jobs) > target_count:
            all_jobs = all_jobs[:target_count]

        print(f"\n[OK] Phase 1 complete. Collected {len(all_jobs)} basic job records.")
        save_snapshot(output_path, all_jobs, "Phase 1 snapshot")

        print(f"\n{'=' * 70}")
        print(f"  PHASE 2 - Deep-fetching {len(all_jobs)} LinkedIn jobs")
        print(f"{'=' * 70}\n")

        enriched_jobs: list[dict] = []
        dropped = 0
        for idx, job in enumerate(all_jobs, start=1):
            job_id = str(job.get("id", "")).strip()
            if not job_id:
                print(f"  [{idx}/{len(all_jobs)}] Skipping job without ID.")
                dropped += 1
                continue

            print(f"  [{idx}/{len(all_jobs)}] Deep-fetching job: {job_id}")
            time.sleep(random.uniform(4.0, 8.0))
            deep_details = fetch_deep_job_details(
                session, job_id, max_retries=int(args.max_deep_retries)
            )
            if deep_details is None:
                print(f"      [-] Dropping job {job_id} (deep fetch failed).")
                dropped += 1
                continue

            job.update(deep_details)
            job["status"] = "enriched"
            enriched_jobs.append(job)

        all_jobs = enriched_jobs
        print(
            f"\n[OK] Phase 2 complete. {len(all_jobs)} jobs enriched, {dropped} dropped."
        )
        save_snapshot(output_path, all_jobs, "Phase 2 snapshot")

    print(f"\n{'=' * 70}")
    print(f"  PHASE 3 - NLP enrichment on {len(all_jobs)} jobs")
    print(f"{'=' * 70}\n")

    for idx, job in enumerate(all_jobs, start=1):
        print(
            f"  [{idx}/{len(all_jobs)}] NLP: {job.get('title', 'Unknown')} @ "
            f"{job.get('company', '?')}"
        )
        run_nlp_on_job(job)
        job["status"] = "nlp_done"

    print("\n[OK] Phase 3 complete. NLP enrichment done.")
    save_snapshot(output_path, all_jobs, "Final output")
    print(f"\n[OK] LinkedIn crawler finished. Saved {len(all_jobs)} jobs.")


if __name__ == "__main__":
    main()
