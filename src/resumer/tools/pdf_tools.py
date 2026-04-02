"""
Custom CrewAI tools for compiling resumes to PDF and checking page counts.

These tools wrap the existing makepdf.py and pypdf logic so that CrewAI agents
can invoke them during task execution.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from crewai.tools import tool
from jinja2 import Environment, FileSystemLoader
from pypdf import PdfReader

# Force UTF-8 on Windows
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent  # project root
TEMPLATE_CSS = BASE_DIR / "template" / "template.css"
JINJA_DIR = BASE_DIR / "template"  # contains base_resume.jinja2 and template.css


def _render_template(profile: dict, resume_data: dict) -> str:
    """Render the Jinja2 template with profile data + structured resume dict."""
    # Convert dict keys to attribute-accessible objects for the template
    from types import SimpleNamespace

    def _to_ns(d):
        if isinstance(d, dict):
            return SimpleNamespace(**{k: _to_ns(v) for k, v in d.items()})
        if isinstance(d, list):
            return [_to_ns(i) for i in d]
        return d

    resume_ns = _to_ns(resume_data)

    env = Environment(
        loader=FileSystemLoader(str(JINJA_DIR)),
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("base_resume.jinja2")
    return template.render(profile=profile, resume=resume_ns)


def _get_page_count(pdf_path: Path) -> int:
    return len(PdfReader(str(pdf_path)).pages)


def _get_overflow_lines(pdf_path: Path) -> int:
    reader = PdfReader(str(pdf_path))
    if len(reader.pages) <= 1:
        return 0
    overflow_lines = 0
    for i in range(1, len(reader.pages)):
        text = reader.pages[i].extract_text()
        if text:
            lines = [line.strip() for line in text.split("\n") if line.strip()]
            overflow_lines += len(lines)
    return overflow_lines


# ---------------------------------------------------------------------------
# Shared state — set by main.py before crew kickoff
# ---------------------------------------------------------------------------
_shared_state: dict = {
    "profile": {},
    "output_dir": "",
}


def set_shared_state(profile: dict, output_dir: str) -> None:
    """Called by main.py to inject runtime data the tools need."""
    _shared_state["profile"] = profile
    _shared_state["output_dir"] = output_dir


# ---------------------------------------------------------------------------
# CrewAI Tools
# ---------------------------------------------------------------------------


@tool("Compile Resume PDF")
def compile_pdf(resume_json: str, iteration: str) -> str:
    """Compile a structured resume JSON into a PDF via Jinja2 + Playwright.

    Args:
        resume_json: A JSON string representing the TailoredResume data.
        iteration: The draft iteration number (e.g. "1", "2", "3").

    Returns:
        A message with the output PDF path and the page count.
    """
    from makepdf import generate_pdf  # lazy import to avoid circular deps

    profile = _shared_state["profile"]
    output_dir = Path(_shared_state["output_dir"])

    # Ensure output dir exists (two-step to avoid Windows PermissionError)
    output_dir.parent.mkdir(exist_ok=True)
    output_dir.mkdir(exist_ok=True)

    try:
        resume_data = json.loads(resume_json)
    except json.JSONDecodeError as e:
        return f"ERROR: Invalid JSON — {e}"

    # Render markdown from Jinja2 template
    md_content = _render_template(profile, resume_data)
    md_path = output_dir / f"draft_v{iteration}.md"
    md_path.write_text(md_content, encoding="utf-8")

    # Compile PDF
    pdf_path = output_dir / f"draft_v{iteration}.pdf"
    _, content_height = generate_pdf(
        md_path=str(md_path),
        css_path=str(TEMPLATE_CSS),
        output_path=str(pdf_path),
    )

    # Store content height so main.py can detect underflow
    _shared_state["last_content_height"] = content_height

    page_count = _get_page_count(pdf_path)
    return f"PDF compiled: {pdf_path.resolve()}\nPage count: {page_count}"



@tool("Check PDF Page Count")
def check_page_count(pdf_path: str) -> str:
    """Check how many pages a PDF has and report overflow lines.

    Args:
        pdf_path: Absolute path to the PDF file, OR a folder path — the tool
                  will automatically find the latest draft_v*.pdf inside it.

    Returns:
        A message with the page count and overflow line count.
    """
    p = Path(pdf_path.strip().strip('"').strip("'"))

    # If the path is a directory (LLM passed the folder instead of a file),
    # find the most recent draft PDF inside it.
    if p.is_dir():
        candidates = sorted(p.glob("draft_v*.pdf"))
        if candidates:
            p = candidates[-1]
        else:
            # Also check the shared output dir as a fallback
            output_dir = Path(_shared_state["output_dir"])
            candidates = sorted(output_dir.glob("draft_v*.pdf"))
            if candidates:
                p = candidates[-1]
            else:
                return (
                    f"ERROR: No draft PDFs found in {pdf_path}. "
                    "The Compile Resume PDF tool must be run first."
                )

    elif not p.is_file():
        # Path does not exist at all — search the shared output dir
        output_dir = Path(_shared_state["output_dir"])
        candidates = sorted(output_dir.glob("draft_v*.pdf"))
        if candidates:
            p = candidates[-1]
        else:
            return (
                f"ERROR: PDF not found at {pdf_path}. "
                "The Compile Resume PDF tool must be run first."
            )

    page_count = _get_page_count(p)
    overflow = _get_overflow_lines(p)

    if page_count == 1:
        return f"APPROVED: Resume is exactly 1 page. Path: {p.resolve()}"

    return (
        f"OVERFLOW: The PDF is {page_count} pages with approximately "
        f"{overflow} lines overflowing onto extra pages. "
        f"Path: {p.resolve()}"
    )
