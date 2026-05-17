"""
main.py — Entry point for the CrewAI Resume Generator.

Usage:
    uv run python src/resumer/main.py

Optional flags:
    --jd    <path>  Job description file     (default: input/job_description.txt)
    --data  <path>  Master profile JSON       (default: input/truth.json)
    --max-iterations <n>                      (default: 5, hard cap: 5)
    --job-label <name>                        (optional, skips prompt)
    --model <provider/model-id>               (optional runtime model override)
    --api-key-env <ENV_VAR>                   (optional API key env override)
    --agent-instructions "<text>"             (optional extra model guidance)
    --no-objective    Omit the objective section
    --no-education    Omit the education section
    --no-skills       Omit the skills section
    --no-projects     Omit the projects section
    --no-experience   Omit the experience section
    --no-activities   Omit the activities section
    --no-applying-for Omit the applying-for subtitle
    --no-photo        Omit the profile photo

Auth:
    Set the provider API key env var matching the selected model.
    Examples: MISTRAL_API_KEY, GEMINI_KEY, OPENROUTER_API_KEY.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any, TypeVar
from urllib.parse import urlparse

# Ensure project root is on sys.path for imports
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from dotenv import load_dotenv

# Load env files (.env.local takes precedence)
load_dotenv()
load_dotenv(".env.local", override=True)

# Force UTF-8 output on Windows
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

import os  # noqa: E402

from pypdf import PdfReader, PdfWriter  # noqa: E402

from pydantic import BaseModel  # noqa: E402

from schemas.resume_schema import (  # noqa: E402
    ActivityGroup,
    JobAnalysis,
    ResumeSectionsDraft,
    SkillCategory,
    SummarySkillsDraft,
    TailoredExperience,
    TailoredProject,
    TailoredResume,
)
from src.resumer.tools.pdf_tools import set_shared_state  # noqa: E402

# ──────────────────────────────────────────────────────────────────────────────
# Terminal colour helpers
# ──────────────────────────────────────────────────────────────────────────────

_CYAN = "\033[96m"
_GREEN = "\033[92m"
_YELLOW = "\033[93m"
_RED = "\033[91m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_RESET = "\033[0m"


def _info(msg: str) -> None:
    print(f"{_CYAN}  ›  {msg}{_RESET}")


def _ok(msg: str) -> None:
    print(f"{_GREEN}  ✅ {msg}{_RESET}")


def _warn(msg: str) -> None:
    print(f"{_YELLOW}  ⚠  {msg}{_RESET}")


def _err(msg: str) -> None:
    print(f"{_RED}  ✗  {msg}{_RESET}")


def _step(n: int, msg: str) -> None:
    print(f"\n{_BOLD}[Step {n}] {msg}{_RESET}")


def _banner(msg: str) -> None:
    bar = "═" * 62
    print(f"\n{_BOLD}{_CYAN}{bar}\n  {msg}\n{bar}{_RESET}\n")


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # project root
MAX_SHORTENING_ITERATIONS = 5
TARGET_INDIVIDUAL_SKILLS = 15
TModel = TypeVar("TModel", bound=BaseModel)


def _sanitize_folder_name(name: str) -> str:
    """Turn 'Google – Software Engineer' into 'google_software_engineer'."""
    name = name.lower().strip()
    name = re.sub(r"[^a-z0-9]+", "_", name)
    return name.strip("_")


def _sanitize_max_iterations(value: int) -> int:
    return max(1, min(MAX_SHORTENING_ITERATIONS, value))


def _write_single_page_pdf(source_pdf: Path, output_pdf: Path) -> None:
    reader = PdfReader(str(source_pdf))
    if not reader.pages:
        raise ValueError(f"Source PDF has no pages: {source_pdf}")
    writer = PdfWriter()
    writer.add_page(reader.pages[0])
    with output_pdf.open("wb") as fh:
        writer.write(fh)


def _extract_json_object(raw_text: str) -> str:
    """Extract the first JSON object from model output text."""
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_text, re.DOTALL)
    if fenced:
        return fenced.group(1).strip()

    first = raw_text.find("{")
    last = raw_text.rfind("}")
    if first != -1 and last != -1 and first < last:
        return raw_text[first : last + 1].strip()

    return raw_text.strip()


def _result_to_raw_text(result: Any) -> str:
    task_output = (
        result.tasks_output[-1]
        if hasattr(result, "tasks_output") and result.tasks_output
        else None
    )
    if task_output and hasattr(task_output, "pydantic") and task_output.pydantic:
        return task_output.pydantic.model_dump_json()
    if task_output:
        raw = (getattr(task_output, "raw", "") or "").strip()
        if raw:
            return raw
    raw = (getattr(result, "raw", "") or "").strip()
    return raw or str(result).strip()


def _parse_model_json(raw_text: str, model_type: type[TModel]) -> TModel:
    json_text = _extract_json_object(raw_text)
    parsed = json.loads(json_text)
    if not isinstance(parsed, dict):
        raise ValueError(f"{model_type.__name__} output must be a JSON object")
    return model_type.model_validate(parsed)


def _dedupe_preserve_order(values: list[Any], limit: int | None = None) -> list[str]:
    seen: set[str] = set()
    cleaned: list[str] = []
    for value in values:
        if value is None:
            continue
        item = re.sub(r"\s+", " ", str(value)).strip(" ,;")
        if not item:
            continue
        key = item.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(item)
        if limit is not None and len(cleaned) >= limit:
            break
    return cleaned


def _normalize_skill_item(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value)).strip(" ,;")


def _count_individual_skill_items(skills_value: Any) -> int:
    if not isinstance(skills_value, list):
        return 0
    seen: set[str] = set()
    for group in skills_value:
        if isinstance(group, SkillCategory):
            items = group.items
        elif isinstance(group, dict):
            items = group.get("items")
        else:
            continue
        if not isinstance(items, list):
            continue
        for item in items:
            cleaned = _normalize_skill_item(item)
            if not cleaned:
                continue
            seen.add(cleaned.casefold())
    return len(seen)


def _ensure_minimum_skill_groups(
    skills_value: Any,
    *,
    skill_pool: list[str],
    min_count: int,
    max_count: int | None = None,
) -> list[dict[str, Any]]:
    normalized_groups: list[dict[str, Any]] = []
    seen: set[str] = set()

    if isinstance(skills_value, list):
        for group in skills_value:
            if isinstance(group, SkillCategory):
                category = group.category.strip() or "Additional Skills"
                raw_items: Any = group.items
            elif isinstance(group, dict):
                category = str(group.get("category", "")).strip() or "Additional Skills"
                raw_items = group.get("items")
            else:
                continue

            if isinstance(raw_items, str):
                raw_items = [raw_items]
            if not isinstance(raw_items, list):
                continue

            cleaned_items: list[str] = []
            for item in raw_items:
                cleaned = _normalize_skill_item(item)
                if not cleaned:
                    continue
                key = cleaned.casefold()
                if key in seen:
                    continue
                seen.add(key)
                cleaned_items.append(cleaned)
            if cleaned_items:
                normalized_groups.append({"category": category, "items": cleaned_items})

    if not normalized_groups:
        normalized_groups.append({"category": "Additional Skills", "items": []})

    target_index = next(
        (
            i
            for i, group in enumerate(normalized_groups)
            if str(group.get("category", "")).strip().casefold()
            not in {"soft skills", "soft skill"}
        ),
        0,
    )

    for candidate in skill_pool:
        if len(seen) >= min_count:
            break
        cleaned = _normalize_skill_item(candidate)
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized_groups[target_index]["items"].append(cleaned)

    if max_count is not None and max_count > 0:
        priority_index = {
            _normalize_skill_item(item).casefold(): idx
            for idx, item in enumerate(skill_pool)
            if _normalize_skill_item(item)
        }
        flattened: list[tuple[int, int, int, str]] = []
        for group_idx, group in enumerate(normalized_groups):
            items = group.get("items")
            if not isinstance(items, list):
                continue
            for item_idx, item in enumerate(items):
                key = _normalize_skill_item(item).casefold()
                if not key:
                    continue
                fallback_rank = len(priority_index) + (group_idx * 1000) + item_idx
                flattened.append((priority_index.get(key, fallback_rank), group_idx, item_idx, key))

        if len(flattened) > max_count:
            flattened.sort(key=lambda value: (value[0], value[1], value[2]))
            selected = {key for _, _, _, key in flattened[:max_count]}
            trimmed_groups: list[dict[str, Any]] = []
            for group in normalized_groups:
                items = group.get("items")
                if not isinstance(items, list):
                    continue
                kept = [item for item in items if _normalize_skill_item(item).casefold() in selected]
                if kept:
                    trimmed_groups.append({"category": group.get("category", "Additional Skills"), "items": kept})
            normalized_groups = trimmed_groups

    return [group for group in normalized_groups if group.get("items")]


def _collect_profile_skill_terms(profile: dict[str, Any]) -> list[str]:
    terms: list[str] = []

    skills = profile.get("skills")
    if isinstance(skills, dict):
        for value in skills.values():
            if isinstance(value, list):
                terms.extend(value)
            elif isinstance(value, str):
                terms.extend([part.strip() for part in value.split(",") if part.strip()])
    elif isinstance(skills, list):
        terms.extend(skills)

    for section_key in ("projects", "experience"):
        section = profile.get(section_key)
        if not isinstance(section, list):
            continue
        for item in section:
            if not isinstance(item, dict):
                continue
            for field in ("technologies", "skills", "tools", "stack"):
                value = item.get(field)
                if isinstance(value, list):
                    terms.extend(value)
                elif isinstance(value, str):
                    terms.extend(
                        [part.strip() for part in value.split(",") if part.strip()]
                    )

    return _dedupe_preserve_order(terms)


def _build_skill_pool(profile: dict[str, Any], job_analysis: JobAnalysis) -> list[str]:
    return _dedupe_preserve_order(
        list(job_analysis.required_skills)
        + list(job_analysis.preferred_skills)
        + list(job_analysis.keywords)
        + _collect_profile_skill_terms(profile)
    )


def _sanitize_em_dashes(value: Any) -> Any:
    if isinstance(value, str):
        return value.replace("—", ",")
    if isinstance(value, list):
        return [_sanitize_em_dashes(item) for item in value]
    if isinstance(value, dict):
        return {key: _sanitize_em_dashes(item) for key, item in value.items()}
    return value


def _normalize_github_path(link: str | None) -> str | None:
    if not link:
        return None
    stripped = link.strip()
    if not stripped:
        return None
    match = re.search(r"github\.com/([^/\s]+/[^/\s#?]+)", stripped, re.IGNORECASE)
    if match:
        return match.group(1).strip("/")
    if re.match(r"^[\w.-]+/[\w.-]+$", stripped):
        return stripped
    return None


def _ensure_url(link: str | None) -> str | None:
    if not link:
        return None
    link = link.strip()
    if not link:
        return None
    if link.casefold() in {"n/a", "na", "none", "null", "no link", "not available", "-"}:
        return None
    if link.startswith(("http://", "https://")):
        return link
    return f"https://{link}"


def _canonical_project_link(link: str | None) -> str | None:
    resolved = _ensure_url(link)
    if not resolved:
        return None
    parsed = urlparse(resolved)
    host = parsed.netloc.strip().casefold()
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return None
    path = re.sub(r"/+", "/", parsed.path).strip().rstrip("/")
    return f"{host}{path}".casefold()


def _collect_profile_project_links(profile: dict[str, Any]) -> set[str]:
    known_links: set[str] = set()
    projects = profile.get("projects")
    if not isinstance(projects, list):
        return known_links
    for project in projects:
        if not isinstance(project, dict):
            continue
        for key in ("link", "url", "github"):
            value = project.get(key)
            if isinstance(value, str):
                canonical = _canonical_project_link(value)
                if canonical:
                    known_links.add(canonical)
    return known_links


def _link_allowed_for_profile(link: str | None, known_links: set[str]) -> str | None:
    resolved = _ensure_url(link)
    if not resolved:
        return None
    canonical = _canonical_project_link(resolved)
    if not canonical:
        return None
    if canonical not in known_links:
        return None
    return resolved


def _haystack_contains_term(haystack: str, term: str) -> bool:
    cleaned = re.sub(r"\s+", " ", term).strip()
    if not cleaned:
        return True
    return cleaned.casefold() in haystack.casefold()


def _missing_required_terms(summary_skills: SummarySkillsDraft, required: list[str]) -> list[str]:
    skill_text = " ".join(
        [summary_skills.professional_summary]
        + [
            f"{group.category} {' '.join(group.items)}"
            for group in summary_skills.skills
        ]
    )
    return [term for term in required if not _haystack_contains_term(skill_text, term)]


def _profile_skills_json(profile: dict[str, Any]) -> str:
    return json.dumps(profile.get("skills", {}), ensure_ascii=False, indent=2)


def _merge_mandatory_words(job_analysis: JobAnalysis, mandatory_words: list[str]) -> JobAnalysis:
    data = job_analysis.model_dump()
    data["required_skills"] = _dedupe_preserve_order(data.get("required_skills", []), limit=10)
    overflow_required = [
        skill
        for skill in job_analysis.required_skills
        if skill not in data["required_skills"]
    ]
    data["preferred_skills"] = _dedupe_preserve_order(
        list(data.get("preferred_skills", [])) + overflow_required + mandatory_words
    )
    data["key_responsibilities"] = _dedupe_preserve_order(
        data.get("key_responsibilities", [])
    )
    data["keywords"] = _dedupe_preserve_order(data.get("keywords", []))
    return JobAnalysis.model_validate(data)


def _ensure_minimum_summary_skills(
    summary_skills: SummarySkillsDraft,
    *,
    skill_pool: list[str],
    min_count: int,
    max_count: int | None = None,
) -> SummarySkillsDraft:
    data = summary_skills.model_dump()
    data["skills"] = _ensure_minimum_skill_groups(
        data.get("skills", []),
        skill_pool=skill_pool,
        min_count=min_count,
        max_count=max_count,
    )
    return SummarySkillsDraft.model_validate(data)


def _assemble_tailored_resume(
    *,
    job_analysis: JobAnalysis,
    summary_skills: SummarySkillsDraft,
    sections: ResumeSectionsDraft,
    profile_project_links: set[str],
) -> str:
    projects: list[TailoredProject] = []
    for key, project in sections.projects.items():
        name = project.name.strip() or key.replace("_", " ").title()
        url = _link_allowed_for_profile(project.link, profile_project_links)
        projects.append(
            TailoredProject(
                name=name,
                link=url,
                github_path=_normalize_github_path(url),
                description=_strip_markdown_artifacts(project.description),
            )
        )

    raw_experience = list(sections.work_experience.values())
    normal_experience = [
        item for item in raw_experience if not _is_independent_projects_experience(item)
    ]
    fallback_experience = [
        item for item in raw_experience if _is_independent_projects_experience(item)
    ]
    selected_experience = normal_experience[:2]
    if len(selected_experience) < 2:
        selected_experience.extend(fallback_experience[: 2 - len(selected_experience)])

    experience: list[TailoredExperience] = []
    for item in selected_experience:
        bullets = [_strip_markdown_artifacts(point) for point in item.points if point.strip()]
        if not bullets:
            continue
        experience.append(
            TailoredExperience(
                role=item.role,
                organization=item.company_name,
                location=item.location,
                duration=item.time_period,
                bullets=bullets[:3],
            )
        )

    activities = []
    activity_bullets = [
        _strip_markdown_artifacts(item)
        for item in sections.extra_curricular
        if str(item).strip()
    ]
    if activity_bullets:
        activities.append(
            ActivityGroup(topic="Achievements", bullets=activity_bullets[:4])
        )

    resume = TailoredResume(
        applying_for=job_analysis.applying_for,
        objective=summary_skills.professional_summary,
        skills=summary_skills.skills,
        projects=projects or None,
        experience=experience or None,
        activities=activities or None,
    )
    sanitized = _sanitize_em_dashes(resume.model_dump())
    return TailoredResume.model_validate(sanitized).model_dump_json()


def _is_independent_projects_experience(item: SectionExperience) -> bool:
    marker = f"{item.role} {item.company_name}".casefold()
    independent_markers = (
        "independent projects",
        "independent project",
        "personal projects",
        "self-directed",
        "self directed",
    )
    return any(value in marker for value in independent_markers)


def _normalize_professional_summary_wording(summary: str) -> str:
    normalized = re.sub(
        r"\binternships?\b",
        "developer role",
        summary,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(
        r"\binterns?\b",
        "developer",
        normalized,
        flags=re.IGNORECASE,
    )
    return re.sub(r"\s+", " ", normalized).strip()


def _apply_omission_flags_to_json(
    current_json: str,
    *,
    args: argparse.Namespace,
    jd: str,
) -> str:
    data = json.loads(current_json)
    if not args.no_applying_for and not data.get("applying_for"):
        inferred_role = _infer_applying_for_from_jd(jd)
        if inferred_role:
            data["applying_for"] = inferred_role
    if args.no_objective:
        data["objective"] = None
    if args.no_skills:
        data["skills"] = None
    if args.no_projects:
        data["projects"] = None
    if args.no_experience:
        data["experience"] = None
    if args.no_activities:
        data["activities"] = None
    if args.no_applying_for:
        data["applying_for"] = None
    if isinstance(data.get("objective"), str):
        data["objective"] = _normalize_professional_summary_wording(
            data["objective"]
        )
    return json.dumps(_sanitize_em_dashes(data), ensure_ascii=False, indent=2)


def _kickoff_with_retries(
    *,
    crew_method_name: str,
    inputs: dict[str, Any],
    label: str,
    attempts: int = 3,
    delay_seconds: float = 5.0,
) -> Any:
    from src.resumer.crew import ResumerCrew  # noqa: E402

    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            _info(f"{label}: starting attempt {attempt}/{attempts}")
            crew_instance = ResumerCrew()
            crew_method = getattr(crew_instance, crew_method_name)
            return crew_method().kickoff(inputs=inputs)
        except Exception as exc:
            last_error = exc
            _warn(f"{label}: attempt {attempt}/{attempts} failed: {exc}")
            if attempt < attempts:
                time.sleep(delay_seconds)
    if last_error:
        raise last_error
    raise RuntimeError(f"{label} failed without an exception")


async def _run_summary_and_sections(
    *,
    job_analysis_json: str,
    truth_skills_json: str,
    profile_json: str,
    mandatory_words_text: str,
    agent_instructions_text: str,
    attempt_feedback: str,
) -> tuple[Any, Any]:
    summary_inputs = {
        "job_analysis_json": job_analysis_json,
        "truth_skills_json": truth_skills_json,
        "mandatory_words": mandatory_words_text,
        "agent_instructions": agent_instructions_text,
        "attempt_feedback": attempt_feedback,
    }
    section_inputs = {
        "job_analysis_json": job_analysis_json,
        "profile_json": profile_json,
        "agent_instructions": agent_instructions_text,
        "attempt_feedback": attempt_feedback,
    }

    summary_task = asyncio.to_thread(
        _kickoff_with_retries,
        crew_method_name="summary_skills_crew",
        inputs=summary_inputs,
        label="Summary and skills agent",
    )

    async def delayed_sections() -> Any:
        await asyncio.sleep(5)
        return await asyncio.to_thread(
            _kickoff_with_retries,
            crew_method_name="resume_sections_crew",
            inputs=section_inputs,
            label="Projects and experience agent",
        )

    return await asyncio.gather(summary_task, delayed_sections())


def _infer_applying_for_from_jd(job_description: str) -> str | None:
    """Infer a role title from the job description when the model omits it."""
    role_keywords = (
        "engineer",
        "developer",
        "scientist",
        "manager",
        "analyst",
        "architect",
        "specialist",
        "consultant",
        "administrator",
        "intern",
        "designer",
        "lead",
    )
    qualifier_words = {
        "an",
        "a",
        "the",
        "experienced",
        "expert",
        "skilled",
        "talented",
        "motivated",
        "passionate",
        "dynamic",
        "dedicated",
        "results-driven",
    }
    trailing_splitters = (
        " to ",
        " with ",
        " who ",
        " responsible for ",
        " for ",
        " in ",
        " at ",
    )

    def _cleanup_candidate(candidate: str) -> str | None:
        candidate = re.sub(r"\s+", " ", candidate).strip(" :;,.()-")
        if not candidate:
            return None

        lowered = f" {candidate.lower()} "
        for splitter in trailing_splitters:
            if splitter in lowered:
                cut_idx = lowered.index(splitter)
                candidate = candidate[:cut_idx].strip(" :;,.()-")
                break

        tokens = candidate.split()
        while tokens and tokens[0].lower() in qualifier_words:
            tokens.pop(0)
        if not tokens:
            return None

        candidate = " ".join(tokens)
        lowered_words = [re.sub(r"[^a-z]", "", word.lower()) for word in tokens]
        if not any(word in role_keywords for word in lowered_words):
            return None

        candidate = re.sub(r"\bback[\s-]*end\b", "Backend", candidate, flags=re.IGNORECASE)
        candidate = re.sub(
            r"\bfront[\s-]*end\b", "Frontend", candidate, flags=re.IGNORECASE
        )
        candidate = re.sub(
            r"\bfull[\s-]*stack\b", "Full Stack", candidate, flags=re.IGNORECASE
        )
        candidate = re.sub(r"\bdevops\b", "DevOps", candidate, flags=re.IGNORECASE)
        candidate = candidate.title()
        candidate = re.sub(r"\bDevops\b", "DevOps", candidate)
        candidate = re.sub(r"\bApi\b", "API", candidate)
        candidate = re.sub(r"\bAi\b", "AI", candidate)
        candidate = re.sub(r"\bMl\b", "ML", candidate)
        candidate = re.sub(r"\bQa\b", "QA", candidate)
        candidate = re.sub(r"\bUi\b", "UI", candidate)
        candidate = re.sub(r"\bUx\b", "UX", candidate)
        candidate = re.sub(r"\bSql\b", "SQL", candidate)
        return candidate.strip()

    lines = [line.strip() for line in job_description.splitlines() if line.strip()]
    if not lines:
        return None

    candidates: list[str] = []
    for line in lines:
        if len(line.split()) <= 10 and "." not in line:
            candidates.append(line)

    extraction_patterns = (
        r"\b(?:looking|searching|seeking)\s+for\s+(?:an?\s+)?([^\n\.,:;]+)",
        r"\bjoin\s+our\s+\w+\s+as\s+(?:an?\s+)?([^\n\.,:;]+)",
        r"\b(?:position|role)\s*(?:is|:)\s*(?:an?\s+)?([^\n\.,:;]+)",
        r"\b(?:hiring|hire)\s+(?:an?\s+)?([^\n\.,:;]+)",
    )
    for pattern in extraction_patterns:
        for match in re.finditer(pattern, job_description, flags=re.IGNORECASE):
            candidates.append(match.group(1))

    cleaned_candidates = [c for c in (_cleanup_candidate(c) for c in candidates) if c]
    if not cleaned_candidates:
        return None

    return sorted(cleaned_candidates, key=lambda role: (len(role.split()), len(role)))[0]


def _strip_markdown_artifacts(text: str) -> str:
    """
    Convert markdown-ish inline formatting to plain text for fields that should
    render as normal prose (e.g., project descriptions).
    """
    # Links: [text](url) -> text
    cleaned = re.sub(r"\[([^\]]+)\]\((?:[^)]+)\)", r"\1", text)
    # Inline code: `text` -> text
    cleaned = re.sub(r"`([^`]*)`", r"\1", cleaned)
    # Bold/italic markers
    cleaned = cleaned.replace("**", "").replace("__", "")
    cleaned = cleaned.replace("*", "").replace("_", "")
    # Flatten accidental list markers into plain prose
    cleaned = re.sub(r"(?m)^\s*[-•]\s+", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _coerce_tailored_resume_payload(
    payload: dict[str, Any],
    *,
    profile_project_links: set[str] | None = None,
) -> dict[str, Any]:
    """Map common model-output variants into the TailoredResume schema shape."""
    # Some models wrap the object under a top-level key.
    if "TailoredResume" in payload and isinstance(payload["TailoredResume"], dict):
        payload = payload["TailoredResume"]

    # Map alternate naming for applying-for subtitle.
    if not payload.get("applying_for"):
        for key in (
            "applyingFor",
            "applying_for_role",
            "applying for",
            "job_title",
            "target_role",
            "position",
            "role",
        ):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                payload["applying_for"] = value.strip()
                break

    # Map alternate naming for objective.
    if not payload.get("objective"):
        for key in ("professional_summary", "summary", "objective_summary"):
            if payload.get(key):
                payload["objective"] = payload[key]
                break

    # Normalize skills from dict[str, list[str]] into list[{category, items}].
    skills_value = payload.get("skills")
    if isinstance(skills_value, dict):
        normalized_skills: list[dict[str, Any]] = []
        for category, items in skills_value.items():
            if isinstance(items, list):
                item_list = [str(i).strip() for i in items if str(i).strip()]
            elif isinstance(items, str):
                item_list = [s.strip() for s in items.split(",") if s.strip()]
            else:
                continue
            if item_list:
                normalized_skills.append(
                    {"category": str(category), "items": item_list}
                )
        payload["skills"] = normalized_skills or None

    # Normalize project link variants and ensure dict items.
    projects_value = payload.get("projects")
    if isinstance(projects_value, list):
        normalized_projects: list[dict[str, Any]] = []
        for project in projects_value:
            if not isinstance(project, dict):
                continue
            p = dict(project)
            if not p.get("link") and isinstance(p.get("github"), str):
                p["link"] = p["github"]
            if not p.get("link") and isinstance(p.get("url"), str):
                p["link"] = p["url"]
            if isinstance(p.get("link"), str):
                p["link"] = _ensure_url(p.get("link")) or ""
            if profile_project_links is not None:
                p["link"] = _link_allowed_for_profile(
                    p.get("link"),
                    profile_project_links,
                ) or ""
            description = p.get("description")
            if isinstance(description, str) and description.strip():
                p["description"] = _strip_markdown_artifacts(description)
            normalized_projects.append(p)
        payload["projects"] = normalized_projects or None

    # Normalize experience bullet variants.
    experience_value = payload.get("experience")
    if isinstance(experience_value, list):
        normalized_experience: list[dict[str, Any]] = []
        for exp in experience_value:
            if not isinstance(exp, dict):
                continue
            e = dict(exp)
            bullets = e.get("bullets")
            if not isinstance(bullets, list) or not bullets:
                alt = e.get("responsibilities")
                if isinstance(alt, list):
                    bullets = [str(b).strip() for b in alt if str(b).strip()]
                elif isinstance(alt, str) and alt.strip():
                    bullets = [alt.strip()]
                else:
                    bullets = []

            numerical = e.get("numerical data") or e.get("numerical_data")
            if isinstance(numerical, str) and numerical.strip():
                bullets.append(numerical.strip())
            elif isinstance(numerical, list):
                bullets.extend(str(n).strip() for n in numerical if str(n).strip())

            e["bullets"] = bullets
            normalized_experience.append(e)
        payload["experience"] = normalized_experience or None

    # Normalize activities from grouped dicts.
    activities_value = payload.get("activities")
    if not activities_value:
        for alt_key in (
            "extra_curricular_activities_and_achievements",
            "extra_curricular_activities_achievements",
            "extra_curricular",
        ):
            if payload.get(alt_key):
                activities_value = payload[alt_key]
                break

    if isinstance(activities_value, dict):
        normalized_activities: list[dict[str, Any]] = []
        for topic, bullets in activities_value.items():
            if isinstance(bullets, list):
                bullet_list = [str(b).strip() for b in bullets if str(b).strip()]
            elif isinstance(bullets, str):
                bullet_list = [bullets.strip()] if bullets.strip() else []
            else:
                bullet_list = []
            if bullet_list:
                normalized_activities.append(
                    {"topic": str(topic), "bullets": bullet_list}
                )
        payload["activities"] = normalized_activities or None

    return payload


def _normalize_tailored_resume_json(
    raw_text: str,
    *,
    profile_project_links: set[str] | None = None,
) -> str:
    """Normalize and validate model output as TailoredResume JSON."""
    json_text = _extract_json_object(raw_text)
    parsed = json.loads(json_text)
    if not isinstance(parsed, dict):
        raise ValueError("Model output must be a JSON object")
    parsed = _coerce_tailored_resume_payload(
        parsed,
        profile_project_links=profile_project_links,
    )
    validated = TailoredResume.model_validate(parsed)

    # Reject effectively-empty outputs so we never render near-blank pages.
    if not any(
        [
            validated.objective,
            validated.skills,
            validated.projects,
            validated.experience,
            validated.activities,
        ]
    ):
        raise ValueError("Tailored resume payload is empty after normalization")

    return validated.model_dump_json()


def _ensure_minimum_skills_in_resume_json(
    current_json: str,
    *,
    skill_pool: list[str],
    min_count: int,
    max_count: int | None = None,
    profile_project_links: set[str] | None = None,
) -> str:
    parsed = json.loads(current_json)
    if not isinstance(parsed, dict):
        raise ValueError("Resume JSON must be an object")
    parsed = _coerce_tailored_resume_payload(
        parsed,
        profile_project_links=profile_project_links,
    )
    if parsed.get("skills") is None:
        return TailoredResume.model_validate(parsed).model_dump_json()
    parsed["skills"] = (
        _ensure_minimum_skill_groups(
            parsed.get("skills"),
            skill_pool=skill_pool,
            min_count=min_count,
            max_count=max_count,
        )
        or None
    )
    return TailoredResume.model_validate(parsed).model_dump_json()


def _remove_experience_third_bullet(
    resume_data: dict[str, Any],
    *,
    experience_index: int,
) -> dict[str, Any] | None:
    experiences = resume_data.get("experience")
    if not isinstance(experiences, list) or len(experiences) <= experience_index:
        return None
    experience = experiences[experience_index]
    if not isinstance(experience, dict):
        return None

    bullets = experience.get("bullets")
    if not isinstance(bullets, list) or len(bullets) < 3:
        return None
    removed = bullets.pop(2)
    role = str(experience.get("role") or f"experience {experience_index + 1}")
    organization = str(experience.get("organization") or "").strip()
    label_target = f"{role} @ {organization}" if organization else role
    return {
        "kind": "experience_bullet",
        "label": f"Removed third bullet from {label_target}",
        "experience_index": experience_index,
        "item_index": 2,
        "value": removed,
    }


def _remove_third_project(resume_data: dict[str, Any]) -> dict[str, Any] | None:
    projects = resume_data.get("projects")
    if not isinstance(projects, list) or len(projects) < 3:
        return None
    removed = projects.pop(2)
    removed_name = removed.get("name") if isinstance(removed, dict) else "third project"
    return {
        "kind": "project_entry",
        "label": f"Removed third project: {removed_name}",
        "project_index": 2,
        "value": removed,
    }


def _restore_local_shortening_edit(
    resume_data: dict[str, Any],
    edit: dict[str, Any],
) -> bool:
    kind = edit.get("kind")
    if kind == "experience_bullet":
        experiences = resume_data.get("experience")
        if not isinstance(experiences, list):
            return False
        experience_index = int(edit.get("experience_index", -1))
        if experience_index < 0 or len(experiences) <= experience_index:
            return False
        experience = experiences[experience_index]
        if not isinstance(experience, dict):
            return False
        bullets = experience.get("bullets")
        if not isinstance(bullets, list):
            return False
        item_index = int(edit.get("item_index", len(bullets)))
        bullets.insert(min(item_index, len(bullets)), edit.get("value"))
        return True

    projects = resume_data.get("projects")
    if not isinstance(projects, list):
        return False

    project_index = int(edit.get("project_index", -1))
    if kind == "project_entry":
        if project_index < 0 or project_index > len(projects):
            return False
        projects.insert(project_index, edit.get("value"))
        return True

    return False


def _prepare_resume_json_for_render(
    current_json: str,
    *,
    args: argparse.Namespace,
    jd: str,
    skill_pool: list[str],
    profile_project_links: set[str] | None,
) -> str:
    current_json = _apply_omission_flags_to_json(current_json, args=args, jd=jd)
    if not args.no_skills:
            current_json = _ensure_minimum_skills_in_resume_json(
                current_json,
                skill_pool=skill_pool,
                min_count=TARGET_INDIVIDUAL_SKILLS,
                max_count=TARGET_INDIVIDUAL_SKILLS,
                profile_project_links=profile_project_links,
            )
    return current_json


def _compile_resume_candidate(
    *,
    resume_json: str,
    iteration: int,
    compile_pdf: Any,
    output_dir: Path,
    get_page_count: Any,
    get_overflow_lines: Any,
    shared_state: dict[str, Any],
) -> tuple[Path, int, int, int]:
    compile_pdf.func(resume_json, str(iteration))
    pdf_path = output_dir / f"draft_v{iteration}.pdf"
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF missing: {pdf_path}")
    pages = get_page_count(pdf_path)
    overflow_lines = get_overflow_lines(pdf_path)
    content_height = int(shared_state.get("last_content_height", 0) or 0)
    return pdf_path, pages, overflow_lines, content_height


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="CrewAI agent: generate a 1-page tailored resume."
    )
    parser.add_argument(
        "--jd",
        default="input/job_description.txt",
        help="Path to job description text file",
    )
    parser.add_argument(
        "--data",
        default="input/truth.json",
        help="Path to master profile JSON",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=MAX_SHORTENING_ITERATIONS,
        help=f"Max feedback-loop iterations (hard cap: {MAX_SHORTENING_ITERATIONS})",
    )
    parser.add_argument(
        "--job-label",
        default="",
        help="Optional non-interactive output folder label (skips terminal prompt)",
    )
    parser.add_argument(
        "--model",
        default="",
        help="LLM model id, e.g. mistral/mistral-large-latest or gemini/gemini-2.0-flash",
    )
    parser.add_argument(
        "--api-key-env",
        default="",
        help="Environment variable name that stores the API key for the selected model",
    )
    parser.add_argument(
        "--no-objective", action="store_true", help="Omit the objective section"
    )
    parser.add_argument(
        "--no-education", action="store_true", help="Omit the education section"
    )
    parser.add_argument(
        "--no-skills", action="store_true", help="Omit the skills section"
    )
    parser.add_argument(
        "--no-projects", action="store_true", help="Omit the projects section"
    )
    parser.add_argument(
        "--no-experience", action="store_true", help="Omit the experience section"
    )
    parser.add_argument(
        "--no-activities", action="store_true", help="Omit the activities section"
    )
    parser.add_argument(
        "--no-applying-for",
        action="store_true",
        help="Omit the applying for subtitle",
    )
    parser.add_argument(
        "--no-photo", action="store_true", help="Omit the profile photo"
    )
    parser.add_argument(
        "--mandatory-words",
        nargs="*",
        default=[],
        help="List of words that MUST be included word-for-word",
    )
    parser.add_argument(
        "--agent-instructions",
        default="",
        help="Extra instructions to pass directly to the model agents",
    )
    args = parser.parse_args()
    requested_max_iterations = args.max_iterations
    args.max_iterations = _sanitize_max_iterations(args.max_iterations)
    if requested_max_iterations != args.max_iterations:
        _warn(
            f"Requested max iterations ({requested_max_iterations}) exceeded the cap. Using {args.max_iterations}."
        )

    if args.model.strip():
        os.environ["RESUMER_MODEL"] = args.model.strip()
    if args.api_key_env.strip():
        os.environ["RESUMER_API_KEY_ENV"] = args.api_key_env.strip()

    # Import crew after model env is configured so runtime model selection takes effect.
    from src.resumer.crew import resolve_llm_runtime  # noqa: E402

    selected_model, selected_key_env, api_key = resolve_llm_runtime()

    jd_path = BASE_DIR / args.jd
    data_path = BASE_DIR / args.data
    template_css = BASE_DIR / "template" / "template.css"

    _banner("🤖  Resume Agent v3 — CrewAI")

    # ── Validate inputs ──────────────────────────────────────────────────
    for p in [jd_path, data_path, template_css]:
        if not p.exists():
            _err(f"File not found: {p}")
            sys.exit(1)

    if not api_key:
        _err(
            f"{selected_key_env} not set for model '{selected_model}'. Add it to .env.local or export it."
        )
        sys.exit(1)
    _info(f"Model: {selected_model}")

    # ── Load data ────────────────────────────────────────────────────────
    _step(1, "Loading inputs…")
    profile = json.loads(data_path.read_text(encoding="utf-8"))
    profile_project_links = _collect_profile_project_links(profile)
    jd = jd_path.read_text(encoding="utf-8").strip()
    _info(f"Profile: {profile.get('personal_information', {}).get('name', '—')}")
    _info(f"Job description: {len(jd):,} chars")

    # ── Apply omission flags to profile ──────────────────────────────────
    if args.no_education:
        profile["education"] = []
    if args.no_photo:
        profile.pop("photo", None)

    # ── Ask for job name & create output folder ──────────────────────────
    _step(2, "Setting up output folder…")
    if args.job_label.strip():
        job_label = args.job_label.strip()
        _info(f"Job/Company name for this run: {job_label}")
    else:
        job_label = input(
            f"{_CYAN}  ?  Job/Company name for this run: {_RESET}"
        ).strip()
    if not job_label:
        job_label = "untitled_run"
    folder_name = _sanitize_folder_name(job_label)
    outputs_base = BASE_DIR / "outputs"
    output_dir = outputs_base / folder_name

    try:
        outputs_base.mkdir(exist_ok=True)
        output_dir.mkdir(exist_ok=True)
    except PermissionError as e:
        _err(f"Cannot create output folder: {e}")
        _err("Try running the terminal as Administrator or check folder permissions.")
        sys.exit(1)

    _info(f"Output folder: {output_dir}")

    # ── Inject shared state for tools ────────────────────────────────────
    set_shared_state(profile=profile, output_dir=str(output_dir))

    # ── Kickoff CrewAI — staged generation loop ─────────────────────────
    _step(3, "Launching staged CrewAI resume pipeline…")

    from src.resumer.tools.pdf_tools import (
        compile_pdf,
        _get_page_count,
        _get_overflow_lines,
    )

    from src.resumer.tools.pdf_tools import _shared_state

    MAX_RUN_ATTEMPTS = 3
    final_success = False
    overflow_limit_reached = False
    attempt_feedback = "None"

    for run_attempt in range(1, MAX_RUN_ATTEMPTS + 1):
        if run_attempt > 1:
            _info(
                f"Restarting generation from scratch (Attempt {run_attempt}/{MAX_RUN_ATTEMPTS})..."
            )

        current_json = ""
        overflow_lines = 0
        skill_pool: list[str] = []

        try:
            analysis_result = _kickoff_with_retries(
                crew_method_name="job_analysis_crew",
                inputs={
                    "job_description": jd,
                    "agent_instructions": args.agent_instructions.strip() or "None",
                },
                label="Job analysis agent",
            )
            job_analysis = _parse_model_json(
                _result_to_raw_text(analysis_result), JobAnalysis
            )
            job_analysis = _merge_mandatory_words(job_analysis, args.mandatory_words)
            if not job_analysis.applying_for:
                job_analysis.applying_for = _infer_applying_for_from_jd(jd)
            skill_pool = _build_skill_pool(profile, job_analysis)

            job_analysis_json = job_analysis.model_dump_json(indent=2)
            (output_dir / "job_analysis.json").write_text(
                job_analysis_json, encoding="utf-8"
            )
            mandatory_words_text = (
                ", ".join(args.mandatory_words) if args.mandatory_words else "None"
            )
            agent_instructions_text = args.agent_instructions.strip() or "None"
            profile_json = json.dumps(profile, ensure_ascii=False, indent=2)

            summary_result, sections_result = asyncio.run(
                _run_summary_and_sections(
                    job_analysis_json=job_analysis_json,
                    truth_skills_json=_profile_skills_json(profile),
                    profile_json=profile_json,
                    mandatory_words_text=mandatory_words_text,
                    agent_instructions_text=agent_instructions_text,
                    attempt_feedback=attempt_feedback,
                )
            )
            summary_skills = _parse_model_json(
                _result_to_raw_text(summary_result), SummarySkillsDraft
            )

            for repair_attempt in range(1, 3):
                missing_required = _missing_required_terms(
                    summary_skills, job_analysis.required_skills
                )
                if not missing_required:
                    break
                repair_feedback = (
                    "Repair required. Add these required skills exactly in the "
                    f"professional summary or skills section: {', '.join(missing_required)}"
                )
                _warn(repair_feedback)
                repair_result = _kickoff_with_retries(
                    crew_method_name="summary_skills_crew",
                    inputs={
                        "job_analysis_json": job_analysis_json,
                        "truth_skills_json": _profile_skills_json(profile),
                        "mandatory_words": mandatory_words_text,
                        "agent_instructions": agent_instructions_text,
                        "attempt_feedback": repair_feedback,
                    },
                    label=f"Summary and skills repair {repair_attempt}",
                )
                summary_skills = _parse_model_json(
                    _result_to_raw_text(repair_result), SummarySkillsDraft
                )

            missing_required = _missing_required_terms(
                summary_skills, job_analysis.required_skills
            )
            if missing_required:
                raise ValueError(
                    "Summary/skills still missing required skills: "
                    + ", ".join(missing_required)
                )
            summary_skills = _ensure_minimum_summary_skills(
                summary_skills,
                skill_pool=skill_pool,
                min_count=TARGET_INDIVIDUAL_SKILLS,
                max_count=TARGET_INDIVIDUAL_SKILLS,
            )
            if _count_individual_skill_items(summary_skills.skills) != TARGET_INDIVIDUAL_SKILLS:
                raise ValueError(
                    f"Summary/skills must contain exactly {TARGET_INDIVIDUAL_SKILLS} unique skills."
                )

            sections = _parse_model_json(
                _result_to_raw_text(sections_result), ResumeSectionsDraft
            )
            current_json = _assemble_tailored_resume(
                job_analysis=job_analysis,
                summary_skills=summary_skills,
                sections=sections,
                profile_project_links=profile_project_links,
            )
        except Exception as exc:
            _err(f"Staged generation failed on attempt {run_attempt}: {exc}")
            attempt_feedback = (
                "Previous attempt failed during staged generation. Produce stricter "
                "valid JSON and keep all required skills visible."
            )
            continue

        draft_iteration = 1
        try:
            current_json = _prepare_resume_json_for_render(
                current_json,
                args=args,
                jd=jd,
                skill_pool=skill_pool,
                profile_project_links=profile_project_links,
            )
            _, pages, overflow_lines, content_height = _compile_resume_candidate(
                resume_json=current_json,
                iteration=draft_iteration,
                compile_pdf=compile_pdf,
                output_dir=output_dir,
                get_page_count=_get_page_count,
                get_overflow_lines=_get_overflow_lines,
                shared_state=_shared_state,
            )
        except Exception as e:
            _err(f"Could not compile initial resume draft: {e}")
            continue

        if pages == 1:
            if content_height > 0 and content_height < 900:
                _warn(
                    f"Draft {draft_iteration}: UNDERFLOW (Content height: {content_height}px / ~1122px). Too much empty space."
                )
                attempt_feedback = (
                    "Previous attempt underfilled the page. Add richer, "
                    "job-relevant detail across project descriptions, work "
                    "experience bullets, and the summary while keeping one-page fit."
                )
                _warn("Discarding this run and restarting with enrichment feedback...")
                continue
            final_success = True
            _ok(
                f"Draft {draft_iteration}: Resume fits on 1 page. Content height: {content_height}px"
            )
            break

        _warn(
            f"Draft {draft_iteration}: OVERFLOW ({overflow_lines} rendered lines). Content height: {content_height or '?'}px"
        )
        _info("Running local shortening pass without model/API calls.")

        working_data = json.loads(current_json)
        removed_edits: list[dict[str, Any]] = []
        fit_found = False

        shortening_steps: list[Any] = []
        experiences = working_data.get("experience")
        if isinstance(experiences, list):
            for experience_index in range(len(experiences)):
                shortening_steps.append(
                    lambda data, idx=experience_index: _remove_experience_third_bullet(
                        data,
                        experience_index=idx,
                    )
                )
        shortening_steps.append(_remove_third_project)

        for step in shortening_steps:
            edit = step(working_data)
            if not edit:
                _info("Local shortening step skipped; target content was not present.")
                continue
            removed_edits.append(edit)
            _info(str(edit["label"]))

            try:
                candidate_json = TailoredResume.model_validate(
                    _sanitize_em_dashes(working_data)
                ).model_dump_json()
                candidate_json = _prepare_resume_json_for_render(
                    candidate_json,
                    args=args,
                    jd=jd,
                    skill_pool=skill_pool,
                    profile_project_links=profile_project_links,
                )
                draft_iteration += 1
                _, pages, overflow_lines, content_height = _compile_resume_candidate(
                    resume_json=candidate_json,
                    iteration=draft_iteration,
                    compile_pdf=compile_pdf,
                    output_dir=output_dir,
                    get_page_count=_get_page_count,
                    get_overflow_lines=_get_overflow_lines,
                    shared_state=_shared_state,
                )
            except Exception as e:
                _err(f"Could not compile local shortening draft: {e}")
                break

            current_json = candidate_json
            working_data = json.loads(candidate_json)
            if pages == 1:
                fit_found = True
                _ok(f"Draft {draft_iteration}: local shortening fits on 1 page.")
                break
            _warn(
                f"Draft {draft_iteration}: still overflowing ({overflow_lines} rendered lines)."
            )

        if fit_found:
            for edit in reversed(removed_edits):
                restored_data = copy.deepcopy(working_data)
                if not _restore_local_shortening_edit(restored_data, edit):
                    continue
                try:
                    restored_json = TailoredResume.model_validate(
                        _sanitize_em_dashes(restored_data)
                    ).model_dump_json()
                    restored_json = _prepare_resume_json_for_render(
                        restored_json,
                        args=args,
                        jd=jd,
                        skill_pool=skill_pool,
                        profile_project_links=profile_project_links,
                    )
                    draft_iteration += 1
                    _, pages, overflow_lines, content_height = _compile_resume_candidate(
                        resume_json=restored_json,
                        iteration=draft_iteration,
                        compile_pdf=compile_pdf,
                        output_dir=output_dir,
                        get_page_count=_get_page_count,
                        get_overflow_lines=_get_overflow_lines,
                        shared_state=_shared_state,
                    )
                except Exception as e:
                    _warn(f"Could not test restoring removed content: {e}")
                    continue

                if pages == 1:
                    working_data = json.loads(restored_json)
                    current_json = restored_json
                    _ok(f"Restored content and still fits: {edit['label']}")
                else:
                    _info(f"Kept removal because restore overflowed: {edit['label']}")

            try:
                draft_iteration += 1
                _, pages, overflow_lines, content_height = _compile_resume_candidate(
                    resume_json=current_json,
                    iteration=draft_iteration,
                    compile_pdf=compile_pdf,
                    output_dir=output_dir,
                    get_page_count=_get_page_count,
                    get_overflow_lines=_get_overflow_lines,
                    shared_state=_shared_state,
                )
            except Exception as e:
                _err(f"Could not compile final local-shortened draft: {e}")
                continue
            if pages != 1:
                _warn(
                    f"Final local-shortened draft still overflowed ({overflow_lines} rendered lines)."
                )
                overflow_limit_reached = True
                break

            if content_height > 0 and content_height < 900:
                _warn(
                    f"Draft {draft_iteration}: UNDERFLOW after local shortening (Content height: {content_height}px / ~1122px)."
                )
                attempt_feedback = (
                    "Previous attempt underfilled after local shortening. Add richer, "
                    "job-relevant detail while keeping one-page fit."
                )
                continue
            final_success = True
            break

        _warn(
            "Local shortening could not fit the resume. Final output will keep only the first PDF page."
        )
        overflow_limit_reached = True

        if final_success:
            break
        if overflow_limit_reached:
            break

    # ── Post-process result ──────────────────────────────────────────────
    _step(4, "Wrapping up…")
    pdf_candidates = sorted(output_dir.glob("draft_v*.pdf"))
    produced_final = False

    # ── Find and copy final PDF ──────────────────────────────────────────
    if final_success:
        if pdf_candidates:
            best_pdf = pdf_candidates[-1]
            page_count = len(PdfReader(str(best_pdf)).pages)

            if page_count == 1:
                _ok("Final resume is exactly 1 page! 🎉")
            else:
                _warn(f"Best draft is {page_count} page(s).")

            final = output_dir / "final_resume.pdf"
            shutil.copy2(best_pdf, final)
            produced_final = True
            _ok(f"Final resume → {final.resolve()}")

            best_md = best_pdf.with_suffix(".md")
            if best_md.exists():
                shutil.copy2(best_md, output_dir / "final_resume.md")
        else:
            _warn("No PDF drafts found in output folder.")
            _warn("The crew may not have used the compile_pdf tool.")
    elif overflow_limit_reached and pdf_candidates:
        best_pdf = pdf_candidates[-1]
        page_count = len(PdfReader(str(best_pdf)).pages)
        final = output_dir / "final_resume.pdf"

        if page_count > 1:
            _warn(
                f"Still {page_count} pages after {args.max_iterations} iterations. Keeping only page 1 in final output."
            )
            _write_single_page_pdf(best_pdf, final)
            produced_final = True
            _ok(f"Final resume (first page only) → {final.resolve()}")
        else:
            shutil.copy2(best_pdf, final)
            produced_final = True
            _ok(f"Final resume → {final.resolve()}")

        best_md = best_pdf.with_suffix(".md")
        if best_md.exists():
            shutil.copy2(best_md, output_dir / "final_resume.md")
    elif not final_success:
        _err(
            f"All {MAX_RUN_ATTEMPTS} attempts produced underflow or failed to fit on 1 page."
        )
        _err(
            "No final resume was produced. Try adjusting the job description or profile data."
        )

    print()
    if produced_final:
        _ok("Done!")
    else:
        _err("Done without a final resume.")
        sys.exit(1)


if __name__ == "__main__":
    main()
