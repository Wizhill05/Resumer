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

    api_key = os.environ.get("GEMINI_KEY")
    if not api_key:
        _err("GEMINI_KEY not set. Add it to .env.local or export it.")
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

            # Extract Pydantic structured output or fallback to raw JSON
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
            elif task_output:
                current_json = getattr(task_output, "raw", "") or ""
            else:
                _err("Could not extract output from crew agent!")
                break

            # ── Apply CLI omission flags BEFORE PDF compilation ────────────
            try:
                temp_data = json.loads(current_json)
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

            # ── Middle-Man Logic: Objective stripping ──────────────────────
            if overflow_lines > 3:
                _info("⚙️ Middle-man: Overflow > 3 lines. Testing objective removal...")
                try:
                    data = json.loads(current_json)
                    if data.get("objective"):
                        data["objective"] = None
                        current_json = json.dumps(data, indent=2)

                        # Recompile & recheck
                        compile_pdf.func(current_json, f"{iteration}_no_obj")
                        pdf_path = output_dir / f"draft_v{iteration}_no_obj.pdf"

                        pages = _get_page_count(pdf_path)
                        overflow_lines = _get_overflow_lines(pdf_path)

                        if pages == 1:
                            final_success = True
                            _ok(
                                "⚙️ Middle-man fixed the overflow by removing the objective! ✅"
                            )
                            break
                        else:
                            _warn(
                                f"⚙️ Middle-man: Still overflow ({overflow_lines} lines) without objective. Handing to shortener..."
                            )
                    else:
                        _info("⚙️ Middle-man: Objective already removed or empty.")
                except Exception as e:
                    _err(f"⚙️ Middle-man JSON error: {e}")
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
