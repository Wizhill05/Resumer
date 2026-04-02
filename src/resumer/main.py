"""
main.py — Entry point for the CrewAI Resume Generator.

Usage:
    uv run python src/resumer/main.py

Optional flags:
    --jd    <path>  Job description file     (default: input/job_description.txt)
    --data  <path>  Master profile JSON       (default: input/truth.json)
    --max-iterations <n>                      (default: 5)
    --no-objective    Omit the objective section
    --no-education    Omit the education section
    --no-skills       Omit the skills section
    --no-projects     Omit the projects section
    --no-experience   Omit the experience section
    --no-activities   Omit the activities section
    --no-applying-for Omit the applying-for subtitle
    --no-photo        Omit the profile photo

Auth:
    Set NVIDIA_API_KEY in .env.local (or as an env variable).
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

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

from pypdf import PdfReader  # noqa: E402

from schemas.resume_schema import TailoredResume  # noqa: E402
from src.resumer.crew import ResumerCrew  # noqa: E402
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


def _sanitize_folder_name(name: str) -> str:
    """Turn 'Google – Software Engineer' into 'google_software_engineer'."""
    name = name.lower().strip()
    name = re.sub(r"[^a-z0-9]+", "_", name)
    return name.strip("_")


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


def _infer_applying_for_from_jd(job_description: str) -> str | None:
    """Infer a role title from the job description when the model omits it."""
    lines = [line.strip() for line in job_description.splitlines() if line.strip()]
    if not lines:
        return None

    first = lines[0]
    # Prefer a concise title line like "Back End Developer".
    if len(first.split()) <= 10 and "." not in first:
        return first

    lowered = job_description.lower()
    match = re.search(r"looking for (?:an|a)?\s*([^\.,\n]+)", lowered)
    if match:
        role = match.group(1).strip(" :.-")
        if role:
            return " ".join(word.capitalize() for word in role.split())

    return None


def _coerce_tailored_resume_payload(payload: dict[str, Any]) -> dict[str, Any]:
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
            link = p.get("link")
            if (
                isinstance(link, str)
                and link
                and not link.startswith(("http://", "https://"))
            ):
                p["link"] = f"https://{link}"
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


def _normalize_tailored_resume_json(raw_text: str) -> str:
    """Normalize and validate model output as TailoredResume JSON."""
    json_text = _extract_json_object(raw_text)
    parsed = json.loads(json_text)
    if not isinstance(parsed, dict):
        raise ValueError("Model output must be a JSON object")
    parsed = _coerce_tailored_resume_payload(parsed)
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
        default=10,
        help="Max feedback-loop iterations",
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
    args = parser.parse_args()

    jd_path = BASE_DIR / args.jd
    data_path = BASE_DIR / args.data
    template_css = BASE_DIR / "template" / "template.css"

    _banner("🤖  Resume Agent v3 — CrewAI")

    # ── Validate inputs ──────────────────────────────────────────────────
    for p in [jd_path, data_path, template_css]:
        if not p.exists():
            _err(f"File not found: {p}")
            sys.exit(1)

    api_key = os.environ.get("MISTRAL_API_KEY")
    if not api_key:
        _err("MISTRAL_API_KEY not set. Add it to .env.local or export it.")
        sys.exit(1)

    # ── Load data ────────────────────────────────────────────────────────
    _step(1, "Loading inputs…")
    profile = json.loads(data_path.read_text(encoding="utf-8"))
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
    job_label = input(f"{_CYAN}  ?  Job/Company name for this run: {_RESET}").strip()
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

    # ── Kickoff CrewAI — iteration loop ──────────────────────────────────
    _step(3, "Launching CrewAI / Python Middle-Man loop…")

    from src.resumer.tools.pdf_tools import (
        compile_pdf,
        _get_page_count,
        _get_overflow_lines,
    )

    from src.resumer.tools.pdf_tools import _shared_state

    MAX_RUN_ATTEMPTS = 3
    final_success = False

    for run_attempt in range(1, MAX_RUN_ATTEMPTS + 1):
        if run_attempt > 1:
            _info(
                f"Restarting generation from scratch (Attempt {run_attempt}/{MAX_RUN_ATTEMPTS})..."
            )

        crew_instance = ResumerCrew()
        final_result = None
        current_json = ""
        overflow_lines = 0

        for iteration in range(1, args.max_iterations + 1):
            _info(f"Draft iteration {iteration}/{args.max_iterations}…")

            if iteration == 1:
                inputs = {
                    "profile_json": json.dumps(profile, indent=2),
                    "job_description": jd,
                    "output_dir": str(output_dir),
                    "iteration": str(iteration),
                }
                result = crew_instance.writing_crew().kickoff(inputs=inputs)
            else:
                inputs = {
                    "job_description": jd,
                    "output_dir": str(output_dir),
                    "iteration": str(iteration),
                    "overflow_lines": str(overflow_lines),
                    "previous_json": current_json,
                }
                result = crew_instance.shortening_crew().kickoff(inputs=inputs)

            # Extract structured output and validate against the resume schema.
            task_output = (
                result.tasks_output[-1]
                if hasattr(result, "tasks_output") and result.tasks_output
                else None
            )
            if (
                task_output
                and hasattr(task_output, "pydantic")
                and task_output.pydantic
            ):
                current_json = task_output.pydantic.model_dump_json()
            else:
                raw_out = ""
                if task_output:
                    raw_out = (getattr(task_output, "raw", "") or "").strip()
                if not raw_out:
                    raw_out = (getattr(result, "raw", "") or "").strip()
                if not raw_out:
                    raw_out = str(result).strip()

                try:
                    current_json = _normalize_tailored_resume_json(raw_out)
                except Exception as e:
                    _err(f"Could not parse/validate resume JSON from model output: {e}")
                    preview = raw_out[:300].replace("\n", " ")
                    if preview:
                        _warn(f"Model output preview: {preview}")
                    break

            # ── Apply CLI omission flags BEFORE PDF compilation ────────────
            try:
                temp_data = json.loads(current_json)
                if not args.no_applying_for and not temp_data.get("applying_for"):
                    inferred_role = _infer_applying_for_from_jd(jd)
                    if inferred_role:
                        temp_data["applying_for"] = inferred_role
                if args.no_objective:
                    temp_data["objective"] = None
                if args.no_skills:
                    temp_data["skills"] = None
                if args.no_projects:
                    temp_data["projects"] = None
                if args.no_experience:
                    temp_data["experience"] = None
                if args.no_activities:
                    temp_data["activities"] = None
                if args.no_applying_for:
                    temp_data["applying_for"] = None
                current_json = json.dumps(temp_data, indent=2)
            except Exception as e:
                _warn(f"Failed to apply omission flags: {e}")

            # ── Deterministic PDF compilation & check ──────────────────────
            compile_pdf.func(current_json, str(iteration))
            pdf_path = output_dir / f"draft_v{iteration}.pdf"

            if not pdf_path.exists():
                _err(f"PDF missing: {pdf_path}")
                break

            pages = _get_page_count(pdf_path)
            overflow_lines = _get_overflow_lines(pdf_path)

            if pages == 1:
                content_height = _shared_state.get("last_content_height", 0)
                if content_height > 0 and content_height < 900:
                    _warn(
                        f"Iteration {iteration}: UNDERFLOW (Content height: {content_height}px / ~1122px). Too much empty space."
                    )
                    _warn("Discarding this run and restarting completely...")
                    break  # Break out to trigger next run_attempt
                final_success = True
                _ok(
                    f"Iteration {iteration}: Resume fits perfectly on 1 page! ✅ (Content height: {content_height}px)"
                )
                break

            _warn(
                f"Iteration {iteration}: OVERFLOW ({overflow_lines} rendered lines). Content height: {_shared_state.get('last_content_height', '?')}px"
            )

        else:
            _warn(
                f"Reached max iterations ({args.max_iterations}) without fitting on 1 page."
            )

        if final_success:
            break

    # ── Post-process result ──────────────────────────────────────────────
    _step(4, "Wrapping up…")

    # ── Find and copy final PDF ──────────────────────────────────────────
    if not final_success:
        _err(
            f"All {MAX_RUN_ATTEMPTS} attempts produced underflow or failed to fit on 1 page."
        )
        _err(
            "No final resume was produced. Try adjusting the job description or profile data."
        )
    else:
        pdf_candidates = sorted(output_dir.glob("draft_v*.pdf"))
        if pdf_candidates:
            best_pdf = pdf_candidates[-1]
            page_count = len(PdfReader(str(best_pdf)).pages)

            if page_count == 1:
                _ok("Final resume is exactly 1 page! 🎉")
            else:
                _warn(f"Best draft is {page_count} page(s).")

            final = output_dir / "final_resume.pdf"
            shutil.copy2(best_pdf, final)
            _ok(f"Final resume → {final.resolve()}")

            best_md = best_pdf.with_suffix(".md")
            if best_md.exists():
                shutil.copy2(best_md, output_dir / "final_resume.md")
        else:
            _warn("No PDF drafts found in output folder.")
            _warn("The crew may not have used the compile_pdf tool.")

    print()
    _ok("Done!")


if __name__ == "__main__":
    main()
