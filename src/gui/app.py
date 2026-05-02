from __future__ import annotations

import difflib
import functools
import html
import json
import re
import shutil
import socket
import sys
import threading
import time
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import quote

import streamlit as st
from dotenv import load_dotenv

try:
    from streamlit_ace import st_ace
except Exception:  # pragma: no cover - graceful fallback
    st_ace = None

APP_DIR = Path(__file__).resolve().parent
SRC_DIR = APP_DIR.parent
WORKSPACE_ROOT = SRC_DIR.parent

for _p in (WORKSPACE_ROOT, SRC_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from gui.services.job_importer import (  # noqa: E402
    HumanVerificationRequired,
    is_human_check_page_source,
    parse_indeed_html_with_stats,
    scrape_indeed_descriptions_with_driver,
    start_indeed_verification_session,
)
from gui.services.local_backend import (  # noqa: E402
    AuthUser,
    LocalBackend,
)
from gui.services.runner import LogEntry, ResumeRunController  # noqa: E402

load_dotenv(WORKSPACE_ROOT / ".env.local", override=False)

MODEL_PRESETS: dict[str, tuple[str, str]] = {
    "Mistral Large (stable)": ("mistral/mistral-large-latest", "MISTRAL_API_KEY"),
    "Mistral Medium": ("mistral/mistral-medium-latest", "MISTRAL_API_KEY"),
    "Gemini 3 Flash": ("gemini/gemini-3-flash-preview", "GEMINI_KEY"),
    "Gemini 3.1 Flash lite": ("gemini/gemini-3.1-flash-lite-preview", "GEMINI_KEY"),
    "Gemma 4 31B": ("gemini/gemma-4-31b-it", "GEMINI_KEY"),
    "OpenRouter Mistral Large": (
        "openrouter/mistralai/mistral-large-latest",
        "OPENROUTER_API_KEY",
    ),
    "Custom": ("", ""),
}

LOG_SECTION_KEYS = (
    "crew completion",
    "task completion",
    "task started",
    "task failed",
    "task failure",
    "crew failure",
    "crew execution started",
    "crew execution completed",
    "agent started",
    "agent final answer",
    "tracing status",
)

BATCH_CONTROLLER_KEY = "mass_apply_controllers"
BATCH_RUN_META_KEY = "active_mass_apply_runs"
BATCH_MAX_PARALLEL_LIMIT = 6


class _QuietSimpleHTTPRequestHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return


def _ensure_local_file_server() -> str | None:
    server_info = st.session_state.get("local_file_server")
    if isinstance(server_info, dict):
        base_url = server_info.get("base_url")
        thread = server_info.get("thread")
        if isinstance(base_url, str) and thread and thread.is_alive():
            return base_url

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]

        handler = functools.partial(
            _QuietSimpleHTTPRequestHandler,
            directory=str(WORKSPACE_ROOT),
        )
        server = ThreadingHTTPServer(("127.0.0.1", port), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        base_url = f"http://127.0.0.1:{port}"
        st.session_state["local_file_server"] = {
            "server": server,
            "thread": thread,
            "base_url": base_url,
        }
        return base_url
    except Exception:
        return None


def _local_file_url(path: Path) -> str | None:
    try:
        rel = path.relative_to(WORKSPACE_ROOT).as_posix()
    except Exception:
        return None

    base_url = _ensure_local_file_server()
    if not base_url:
        return None
    return f"{base_url}/{quote(rel, safe='/-_.')}"


def _ensure_controller() -> ResumeRunController:
    if "runner" not in st.session_state:
        st.session_state.runner = ResumeRunController(WORKSPACE_ROOT)
    return st.session_state.runner


def _ensure_batch_controllers() -> dict[str, ResumeRunController]:
    controllers = st.session_state.get(BATCH_CONTROLLER_KEY)
    if not isinstance(controllers, dict):
        controllers = {}
        st.session_state[BATCH_CONTROLLER_KEY] = controllers
    return controllers


def _ensure_batch_run_meta() -> dict[str, dict[str, object]]:
    meta = st.session_state.get(BATCH_RUN_META_KEY)
    if not isinstance(meta, dict):
        meta = {}
        st.session_state[BATCH_RUN_META_KEY] = meta
    return meta


def _poll_batch_controllers() -> None:
    for controller in list(_ensure_batch_controllers().values()):
        controller.poll()


def _any_batch_controller_running() -> bool:
    return any(controller.is_running() for controller in _ensure_batch_controllers().values())


def _ensure_local_backend() -> tuple[LocalBackend | None, str]:
    cached = st.session_state.get("local_backend")
    if isinstance(cached, LocalBackend):
        return cached, ""

    try:
        backend = LocalBackend()
    except Exception as exc:
        return None, f"Failed to initialize local backend: {exc}"

    st.session_state["local_backend"] = backend
    return backend, ""


def _set_auth_user(user: AuthUser) -> None:
    st.session_state["auth_user"] = {
        "uid": user.uid,
        "email": user.email,
        "id_token": user.id_token,
        "refresh_token": user.refresh_token,
    }


def _clear_auth_user() -> None:
    st.session_state.pop("auth_user", None)


def _get_auth_user() -> dict[str, str] | None:
    raw = st.session_state.get("auth_user")
    if not isinstance(raw, dict):
        return None
    uid = str(raw.get("uid", "")).strip()
    email = str(raw.get("email", "")).strip()
    if not uid or not email:
        return None
    return raw


def _inject_figma_css() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;600;700;800&family=JetBrains+Mono:wght@400;500;700&display=swap');

        :root {
            --bg: #0b0c10;
            --panel: #111317;
            --panel-2: #06080d;
            --line: #2e3138;
            --line-soft: #1e2127;
            --text: #f2f3f5;
            --muted: #a3a8b3;
            --green: #24cc5a;
            --yellow: #f6bd3f;
            --red: #e35a67;
        }

        .stApp {
            font-family: 'Manrope', sans-serif;
            color: var(--text);
            background:
                radial-gradient(900px 620px at 15% -8%, rgba(36, 204, 90, 0.06), transparent 60%),
                radial-gradient(900px 620px at 110% 0%, rgba(255, 255, 255, 0.02), transparent 55%),
                var(--bg);
        }

        [data-testid="stHeader"],
        [data-testid="stToolbar"],
        [data-testid="stSidebar"] {
            display: none !important;
        }

        .block-container {
            padding-top: 0.7rem !important;
            padding-bottom: 0.5rem !important;
            max-width: 1640px !important;
        }

        [data-testid="stHorizontalBlock"] {
            gap: 0.85rem !important;
        }

        [data-testid="stVerticalBlockBorderWrapper"] {
            background: linear-gradient(180deg, rgba(16, 18, 24, 0.98), rgba(10, 12, 16, 0.98)) !important;
            border: 1px solid var(--line) !important;
            border-radius: 14px !important;
            box-shadow:
                inset 0 1px 0 0 rgba(255,255,255,0.03),
                0 2px 12px rgba(0,0,0,0.25) !important;
        }

        [data-testid="stVerticalBlockBorderWrapper"] > div {
            padding: 1.1rem 1.25rem 0.9rem !important;
        }

        .card-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 0.8rem;
            margin-bottom: 0.35rem;
        }

        .card-title {
            font-size: 1.85rem;
            font-weight: 800;
            letter-spacing: -0.02em;
            color: #f1f2f5;
            line-height: 1;
            white-space: nowrap;
        }

        .card-header-right {
            text-align: right;
            font-size: 0.93rem;
            color: #d9dde5;
            font-weight: 700;
            white-space: nowrap;
            display: flex;
            align-items: center;
            gap: 0.6rem;
        }

        .meta-label {
            font-size: 1rem;
            font-weight: 700;
            color: #e0e2e8;
        }

        .mono-note {
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.78rem;
            color: var(--muted);
        }

        .signal {
            display: inline-flex;
            gap: 5px;
            align-items: center;
            margin-left: 0.45rem;
        }

        .signal span {
            display: inline-block;
            width: 30px;
            height: 7px;
            border-radius: 999px;
            background: #3a3d44;
        }

        .signal .on  { background: var(--green); }
        .signal .warn { background: var(--yellow); }
        .signal .bad  { background: var(--red); }

        .preview-shell {
            border: 1px solid var(--line);
            border-radius: 8px;
            overflow: hidden;
            background: #f7f7f8;
            min-height: 780px;
        }

        .preview-caption {
            margin-top: 0.45rem;
            color: var(--muted);
            font-size: 0.78rem;
        }

        .preview-caption a {
            color: var(--green);
            text-decoration: none;
        }
        .preview-caption a:hover {
            text-decoration: underline;
        }

        .stTextInput > label,
        .stSelectbox > label,
        .stSlider > label,
        .stCheckbox > label {
            font-family: 'Manrope', sans-serif !important;
            font-size: 0.88rem !important;
            font-weight: 600 !important;
            color: #c0c5ce !important;
        }

        .stTextInput input {
            background: #13161c !important;
            border-color: #2a2e36 !important;
            color: #f1f2f5 !important;
            border-radius: 8px !important;
        }

        .stSelectbox [data-baseweb="select"] > div {
            background: #13161c !important;
            border-color: #2a2e36 !important;
            color: #f1f2f5 !important;
            border-radius: 8px !important;
        }

        .stButton > button,
        .stDownloadButton > button,
        .stFormSubmitButton > button {
            border-radius: 10px !important;
            border: 1px solid #2f343a !important;
            background: #181c24 !important;
            color: #f2f4f7 !important;
            font-weight: 700 !important;
            height: 2.55rem;
            transition: all 0.2s ease !important;
        }

        .stButton > button:hover,
        .stDownloadButton > button:hover,
        .stFormSubmitButton > button:hover {
            border-color: #4e545d !important;
            background: #232934 !important;
            transform: translateY(-1px);
            box-shadow: 0 4px 12px rgba(0,0,0,0.3) !important;
        }

        iframe {
            border-radius: 8px !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _status_badge(state: str) -> str:
    state = state.lower()
    if state == "running":
        return "RUNNING"
    if state == "starting":
        return "STARTING"
    if state == "completed":
        return "COMPLETED"
    if state == "failed":
        return "FAILED"
    if state == "stopping":
        return "STOPPING"
    if state == "stopped":
        return "STOPPED"
    return "IDLE"


def _signal_markup(state: str) -> str:
    state = state.lower()
    if state in {"running", "starting"}:
        return "<span class='on'></span><span class='on'></span><span></span>"
    if state == "completed":
        return (
            "<span class='on'></span><span class='on'></span><span class='on'></span>"
        )
    if state in {"failed"}:
        return "<span class='bad'></span><span class='bad'></span><span></span>"
    if state in {"stopping", "stopped"}:
        return "<span class='warn'></span><span></span><span></span>"
    return "<span></span><span></span><span></span>"


def _build_logs_html(logs: list[LogEntry]) -> str:
    rows: list[str] = []
    source = logs[-1200:]

    if not source:
        source = [
            LogEntry(
                ts=time.time(), stream="stdout", text="Waiting for run...", level="info"
            )
        ]

    for entry in source:
        ts = datetime.fromtimestamp(entry.ts).strftime("%H:%M:%S")
        msg = html.escape(entry.text).replace("\t", "    ")
        lower_msg = entry.text.lower()
        section_class = (
            " log-section" if any(k in lower_msg for k in LOG_SECTION_KEYS) else ""
        )

        rows.append(
            "".join(
                [
                    f"<div class='log-row log-{html.escape(entry.level)}{section_class}'>",
                    f"<span class='log-time'>{html.escape(ts)}</span>",
                    f"<span class='log-stream'>>>> {html.escape(entry.stream.upper())}</span>",
                    f"<pre class='log-msg'>{msg}</pre>",
                    "</div>",
                ]
            )
        )

    return f"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&display=swap');
    :root {{
      --line-soft: #1a1d23;
      --text: #d8dde6;
      --muted: #6b7280;
      --event: #82b4ff;
      --warn: #f6bd3f;
      --bad: #e35a67;
      --good: #28cc67;
      --prompt-green: #3ddc84;
    }}
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
      margin: 0;
      background: #05070c;
      font-family: 'JetBrains Mono', monospace;
    }}
    .log-shell {{
      background: #05070c;
      padding: 0.55rem 0.65rem;
      height: 100vh;
      overflow-y: auto;
      box-sizing: border-box;
    }}
    .log-shell::-webkit-scrollbar {{
      width: 6px;
    }}
    .log-shell::-webkit-scrollbar-track {{
      background: transparent;
    }}
    .log-shell::-webkit-scrollbar-thumb {{
      background: #2a2d33;
      border-radius: 10px;
    }}
    .log-row {{
      display: grid;
      grid-template-columns: 76px 100px 1fr;
      gap: 8px;
      align-items: start;
      font-size: 0.78rem;
      line-height: 1.35;
      padding: 0.18rem 0.25rem;
      border-radius: 4px;
      margin-bottom: 1px;
      color: var(--text);
    }}
    .log-row:hover {{
      background: rgba(130, 180, 255, 0.05);
    }}
    .log-time {{
      color: var(--muted);
    }}
    .log-stream {{
      color: var(--prompt-green);
      font-weight: 700;
      letter-spacing: 0.02em;
    }}
    .log-msg {{
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      tab-size: 4;
    }}
    .log-section .log-msg {{ font-weight: 700; }}
    .log-info .log-msg {{ color: var(--text); }}
    .log-event .log-msg {{ color: var(--event); }}
    .log-success .log-msg {{ color: var(--good); }}
    .log-warn .log-msg {{ color: var(--warn); }}
    .log-error .log-msg {{ color: var(--bad); }}
  </style>
</head>
<body>
  <div id="log-shell" class="log-shell">{"".join(rows)}</div>
  <script>
    const shell = document.getElementById('log-shell');
    if (shell) shell.scrollTop = shell.scrollHeight;
  </script>
</body>
</html>
"""


def _profile_temp_path(uid: str) -> Path:
    target_dir = WORKSPACE_ROOT / ".resumer_gui" / uid
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir / "truth.runtime.json"


def _resolve_workspace_path(raw_path: str) -> Path:
    p = Path(raw_path).expanduser()
    if not p.is_absolute():
        p = WORKSPACE_ROOT / p
    return p.resolve()


def _json_error_context(raw_text: str, exc: json.JSONDecodeError) -> str:
    lines = raw_text.splitlines()
    line_index = max(exc.lineno - 1, 0)
    line = lines[line_index] if line_index < len(lines) else ""
    caret = " " * max(exc.colno - 1, 0) + "^"
    return f"{line}\n{caret}"


def _truth_structure_warnings(payload: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    required_top = [
        "personal_information",
        "education",
        "skills",
        "projects",
        "experience",
    ]
    for key in required_top:
        if key not in payload:
            warnings.append(f"Missing top-level key: '{key}'.")

    personal = payload.get("personal_information")
    if not isinstance(personal, dict):
        warnings.append("'personal_information' should be an object.")
    else:
        required_personal = ["name", "phone", "email", "linkedin", "github", "location"]
        for key in required_personal:
            value = personal.get(key)
            if not isinstance(value, str) or not value.strip():
                warnings.append(
                    f"'personal_information.{key}' should be a non-empty string."
                )

    photo = payload.get("photo")
    if photo is not None:
        if not isinstance(photo, dict):
            warnings.append("'photo' should be an object with a 'link' field.")
        else:
            link = photo.get("link")
            if link is not None and not isinstance(link, str):
                warnings.append("'photo.link' should be a string.")

    for key in ("education", "projects", "experience"):
        value = payload.get(key)
        if value is not None and not isinstance(value, list):
            warnings.append(f"'{key}' should be an array.")

    skills = payload.get("skills")
    if skills is not None and not isinstance(skills, dict):
        warnings.append("'skills' should be an object of skill categories.")

    return warnings


def _json_path_lookup(payload: Any, raw_path: str) -> Any:
    path = raw_path.strip()
    if not path:
        raise ValueError("Enter a JSON path.")

    tokens: list[str | int] = []
    i = 0
    while i < len(path):
        ch = path[i]
        if ch == ".":
            i += 1
            continue
        if ch == "[":
            close_idx = path.find("]", i + 1)
            if close_idx == -1:
                raise ValueError("Unclosed '[' in JSON path.")
            idx_text = path[i + 1 : close_idx].strip()
            if not idx_text.isdigit():
                raise ValueError("Array index must be a non-negative integer.")
            tokens.append(int(idx_text))
            i = close_idx + 1
            continue

        start = i
        while i < len(path) and path[i] not in ".[":
            i += 1
        key = path[start:i].strip()
        if not key:
            raise ValueError("Invalid JSON path segment.")
        tokens.append(key)

    current = payload
    for token in tokens:
        if isinstance(token, int):
            if not isinstance(current, list):
                raise ValueError(f"Expected array before index [{token}].")
            if token < 0 or token >= len(current):
                raise ValueError(f"Index [{token}] out of range.")
            current = current[token]
        else:
            if not isinstance(current, dict):
                raise ValueError(f"Expected object before key '{token}'.")
            if token not in current:
                raise ValueError(f"Key '{token}' not found.")
            current = current[token]
    return current


def _project_display_label(project: dict[str, object]) -> str:
    name = str(project.get("name", "Untitled"))
    status = str(project.get("status", "unknown")).upper()
    created_at = project.get("created_at")
    created_str = "—"
    if isinstance(created_at, datetime):
        created_str = created_at.strftime("%Y-%m-%d %H:%M")
    return f"{name} [{status}] · {created_str}"


def _artifact_display_name(artifact: dict[str, object]) -> str:
    file_name = str(artifact.get("file_name", "")).strip()
    if file_name:
        return file_name
    storage_path = str(artifact.get("storage_path", "")).strip()
    return Path(storage_path).name or "artifact"


def _default_artifact_name(artifacts: list[dict[str, object]]) -> str:
    preferred = ["final_resume.pdf", "final_resume.md", "draft_v2.md", "draft_v1.md"]
    by_name = {_artifact_display_name(a): a for a in artifacts}
    for name in preferred:
        if name in by_name:
            return name
    return _artifact_display_name(artifacts[0])


def _job_display_label(job: dict[str, object]) -> str:
    title = str(job.get("title", "Untitled")).strip() or "Untitled"
    company = str(job.get("company", "")).strip()
    status = str(job.get("application_status", "new")).upper()
    resume_count = int(job.get("resume_count", 0) or 0)
    prefix = f"{company} - " if company else ""
    suffix = f" [{status}; {resume_count} resume{'s' if resume_count != 1 else ''}]"
    return f"{prefix}{title}{suffix}"


def _job_description_for_pipeline(job: dict[str, object]) -> str:
    parts = [
        f"Title: {job.get('title', '')}",
        f"Company: {job.get('company', '')}",
        f"Location: {job.get('location', '')}",
        f"Salary: {job.get('salary', '')}",
        f"Job URL: {job.get('source_url', '')}",
        f"Apply URL: {job.get('apply_url', '')}",
        "",
        "Job Description:",
        str(job.get("description", "") or ""),
    ]
    return "\n".join(str(part).strip() for part in parts).strip()


@functools.lru_cache(maxsize=4096)
def _analyze_job_text_local(title: str, description: str) -> dict[str, str]:
    combined = f"{title}\n{description}".lower()

    internship_markers = (
        "intern",
        "internship",
        "trainee",
        "apprentice",
        "co-op",
        "co op",
    )
    role_type = (
        "Internship"
        if any(marker in combined for marker in internship_markers)
        else "Job"
    )

    domain_keywords: dict[str, tuple[str, ...]] = {
        "AI/ML": (
            "ai",
            "ml",
            "machine learning",
            "artificial intelligence",
            "llm",
            "nlp",
            "genai",
            "deep learning",
            "computer vision",
        ),
        "VLSI/Hardware": (
            "vlsi",
            "rtl",
            "verilog",
            "systemverilog",
            "fpga",
            "asic",
            "physical design",
            "layout",
            "soc",
            "firmware",
            "embedded",
            "pcb",
        ),
        "UI/UX": (
            "ui",
            "ux",
            "figma",
            "wireframe",
            "interaction design",
            "frontend",
            "front-end",
            "design system",
            "prototyp",
            "usability",
        ),
        "Data/Analytics": (
            "data analyst",
            "analytics",
            "bi",
            "power bi",
            "tableau",
            "sql",
            "data engineer",
            "etl",
            "spark",
            "hadoop",
        ),
        "DevOps/Cloud": (
            "devops",
            "kubernetes",
            "docker",
            "terraform",
            "ci/cd",
            "jenkins",
            "aws",
            "azure",
            "gcp",
            "sre",
        ),
        "QA/Testing": (
            "qa",
            "quality assurance",
            "test automation",
            "selenium",
            "cypress",
            "pytest",
            "manual testing",
            "performance testing",
        ),
        "Software": (
            "software engineer",
            "backend",
            "front end",
            "full stack",
            "api",
            "microservices",
            "python",
            "java",
            "node",
            "react",
        ),
    }

    scores: dict[str, int] = {}
    for domain, keywords in domain_keywords.items():
        score = 0
        for keyword in keywords:
            if keyword in combined:
                score += 1
        if score:
            scores[domain] = score
    domain = max(scores, key=scores.get) if scores else "General"

    exp_text = ""
    patterns = (
        r"(\d+)\s*[-–]\s*(\d+)\s*(?:\+)?\s*(?:years?|yrs?)",
        r"(\d+)\s*\+\s*(?:years?|yrs?)",
        r"(?:minimum|min\.?)\s*(\d+)\s*(?:\+)?\s*(?:years?|yrs?)",
        r"(\d+)\s*(?:years?|yrs?)\s*(?:of)?\s*(?:experience|exp)",
    )
    for pattern in patterns:
        match = re.search(pattern, combined, flags=re.IGNORECASE)
        if not match:
            continue
        numbers = [group for group in match.groups() if group]
        if len(numbers) >= 2:
            exp_text = f"{numbers[0]}-{numbers[1]} years"
        elif numbers:
            token = numbers[0]
            if "+" in match.group(0):
                exp_text = f"{token}+ years"
            else:
                exp_text = f"{token} years"
        if exp_text:
            break

    if not exp_text:
        if re.search(r"\b(fresher|entry[- ]level|no experience)\b", combined):
            exp_text = "0 years / entry level"
        elif role_type == "Internship":
            exp_text = "0-1 years / student level"
        else:
            exp_text = "Not clearly specified"

    return {
        "role_type": role_type,
        "domain": domain,
        "experience": exp_text,
    }


@functools.lru_cache(maxsize=4096)
def _minimum_experience_years_required(title: str, description: str) -> float | None:
    combined = f"{title}\n{description}".lower()
    numeric = r"(\d+(?:\.\d+)?)"
    patterns = (
        rf"{numeric}\s*[-–]\s*{numeric}\s*(?:\+)?\s*(?:years?|yrs?)",
        rf"{numeric}\s*\+\s*(?:years?|yrs?)",
        rf"(?:minimum|min\.?|at least)\s*{numeric}\s*(?:\+)?\s*(?:years?|yrs?)",
        rf"{numeric}\s*(?:years?|yrs?)\s*(?:of)?\s*(?:experience|exp)",
    )
    for pattern in patterns:
        match = re.search(pattern, combined, flags=re.IGNORECASE)
        if not match:
            continue
        for group in match.groups():
            if group:
                try:
                    return float(group)
                except ValueError:
                    continue

    if re.search(r"\b(fresher|entry[- ]level|no experience)\b", combined):
        return 0.0
    return None


def _batch_display_label(batch: dict[str, object]) -> str:
    name = str(batch.get("name", "Batch"))
    status = str(batch.get("status", "draft")).upper()
    item_count = int(batch.get("item_count", 0) or 0)
    completed_count = int(batch.get("completed_count", 0) or 0)
    failed_count = int(batch.get("failed_count", 0) or 0)
    return f"{name} [{status}] · {completed_count}/{item_count} done · {failed_count} failed"


def _model_pool_from_settings(settings: dict[str, object]) -> list[dict[str, str]]:
    raw_pool = settings.get("model_pool")
    pool: list[dict[str, str]] = []
    if isinstance(raw_pool, list):
        for item in raw_pool:
            if not isinstance(item, dict):
                continue
            model = str(item.get("model", "") or "").strip()
            api_key_env = str(item.get("api_key_env", "") or "").strip()
            label = str(item.get("label", "") or model).strip() or model
            if model and api_key_env:
                pool.append(
                    {"label": label, "model": model, "api_key_env": api_key_env}
                )

    if not pool:
        model = str(settings.get("model", "") or "").strip()
        api_key_env = str(settings.get("api_key_env", "") or "").strip()
        if model and api_key_env:
            pool.append({"label": model, "model": model, "api_key_env": api_key_env})
    return pool


def _model_pool_labels(settings: dict[str, object]) -> str:
    pool = _model_pool_from_settings(settings)
    if not pool:
        return "-"
    return ", ".join(item["label"] for item in pool)


def _model_pool_text(settings: dict[str, object]) -> str:
    lines: list[str] = []
    for item in _model_pool_from_settings(settings):
        lines.append(f"{item['model']} | {item['api_key_env']}")
    return "\n".join(lines)


def _parse_model_pool_text(raw_text: str) -> list[dict[str, str]]:
    pool: list[dict[str, str]] = []
    for line in raw_text.splitlines():
        raw = line.strip()
        if not raw:
            continue
        if "|" in raw:
            model, key_env = [part.strip() for part in raw.split("|", 1)]
        else:
            model, key_env = raw, ""
        if model and key_env:
            pool.append({"label": model, "model": model, "api_key_env": key_env})
    return pool


def _omissions_editor(
    prefix: str, defaults: dict[str, object] | None = None
) -> dict[str, bool]:
    defaults = defaults or {}
    c1, c2 = st.columns(2)
    with c1:
        no_objective = st.checkbox(
            "Hide objective",
            value=bool(defaults.get("no_objective", False)),
            key=f"{prefix}_no_objective",
        )
        no_skills = st.checkbox(
            "Hide skills",
            value=bool(defaults.get("no_skills", False)),
            key=f"{prefix}_no_skills",
        )
        no_experience = st.checkbox(
            "Hide experience",
            value=bool(defaults.get("no_experience", False)),
            key=f"{prefix}_no_experience",
        )
        no_applying_for = st.checkbox(
            "Hide applying-for subtitle",
            value=bool(defaults.get("no_applying_for", False)),
            key=f"{prefix}_no_applying_for",
        )
    with c2:
        no_education = st.checkbox(
            "Hide education",
            value=bool(defaults.get("no_education", False)),
            key=f"{prefix}_no_education",
        )
        no_projects = st.checkbox(
            "Hide projects",
            value=bool(defaults.get("no_projects", False)),
            key=f"{prefix}_no_projects",
        )
        no_activities = st.checkbox(
            "Hide activities",
            value=bool(defaults.get("no_activities", False)),
            key=f"{prefix}_no_activities",
        )
        no_photo = st.checkbox(
            "Hide photo",
            value=bool(defaults.get("no_photo", False)),
            key=f"{prefix}_no_photo",
        )
    return {
        "no_objective": no_objective,
        "no_education": no_education,
        "no_skills": no_skills,
        "no_projects": no_projects,
        "no_experience": no_experience,
        "no_activities": no_activities,
        "no_applying_for": no_applying_for,
        "no_photo": no_photo,
    }


def _settings_from_model_form(prefix: str) -> dict[str, object]:
    preset_names = list(MODEL_PRESETS.keys())
    preset = st.selectbox(
        "Model Selection", options=preset_names, index=0, key=f"{prefix}_preset"
    )
    preset_model, preset_key_env = MODEL_PRESETS[preset]
    custom_model = ""
    custom_key_env = ""
    if preset == "Custom":
        custom_model = st.text_input(
            "Custom Model ID",
            value="mistral/mistral-large-latest",
            key=f"{prefix}_custom_model",
        )
        custom_key_env = st.text_input(
            "API Key Env Variable",
            value="MISTRAL_API_KEY",
            key=f"{prefix}_custom_key_env",
        )

    max_iterations = st.slider(
        "No of Iterations",
        min_value=1,
        max_value=20,
        value=10,
        key=f"{prefix}_max_iterations",
    )
    name_pattern = st.text_input(
        "Run Name Pattern",
        value="{company}_{title}",
        key=f"{prefix}_name_pattern",
    )
    skip_existing = st.checkbox(
        "Skip jobs that already have a completed resume",
        value=True,
        key=f"{prefix}_skip_existing",
    )
    parallel_runs = st.slider(
        "Parallel Batch Runs",
        min_value=1,
        max_value=BATCH_MAX_PARALLEL_LIMIT,
        value=2,
        key=f"{prefix}_parallel_runs",
    )

    model_pool: list[dict[str, str]] = []
    with st.expander("Parallel Model Pool", expanded=False):
        st.caption(
            "Selected models are rotated across queued jobs. Use this to run Mistral, Gemini/Gemma, OpenRouter, etc. at the same time."
        )
        preset_pool_options = [name for name in preset_names if name != "Custom"]
        selected_pool = st.multiselect(
            "Preset models",
            options=preset_pool_options,
            default=[preset] if preset != "Custom" else [],
            key=f"{prefix}_model_pool_presets",
        )
        for name in selected_pool:
            model, key_env = MODEL_PRESETS[name]
            if model and key_env:
                model_pool.append(
                    {"label": name, "model": model, "api_key_env": key_env}
                )
        custom_pool_text = st.text_area(
            "Custom models (one per line: model_id | API_KEY_ENV)",
            value="",
            key=f"{prefix}_custom_model_pool",
            height=90,
        )
        for line in custom_pool_text.splitlines():
            raw = line.strip()
            if not raw:
                continue
            if "|" in raw:
                model, key_env = [part.strip() for part in raw.split("|", 1)]
            else:
                model, key_env = raw, custom_key_env.strip() or preset_key_env
            if model and key_env:
                model_pool.append(
                    {"label": model, "model": model, "api_key_env": key_env}
                )

    if not model_pool and (custom_model.strip() if preset == "Custom" else preset_model):
        model_pool.append(
            {
                "label": preset if preset != "Custom" else custom_model.strip(),
                "model": custom_model.strip() if preset == "Custom" else preset_model,
                "api_key_env": custom_key_env.strip()
                if preset == "Custom"
                else preset_key_env,
            }
        )

    with st.expander("Optional Section Visibility", expanded=False):
        omissions = _omissions_editor(prefix)

    return {
        "model": custom_model.strip() if preset == "Custom" else preset_model,
        "api_key_env": custom_key_env.strip() if preset == "Custom" else preset_key_env,
        "model_pool": model_pool,
        "parallel_runs": parallel_runs,
        "max_iterations": max_iterations,
        "name_pattern": name_pattern,
        "skip_existing": skip_existing,
        "omissions": omissions,
    }


def _render_jobs_table(jobs: list[dict[str, object]]) -> None:
    rows = []
    for job in jobs:
        rows.append(
            {
                "Company": job.get("company", ""),
                "Title": job.get("title", ""),
                "Location": job.get("location", ""),
                "Description": job.get("description_status", ""),
                "Status": job.get("application_status", ""),
                "Resumes": job.get("resume_count", 0),
                "Salary": job.get("salary", ""),
            }
        )
    st.dataframe(rows, use_container_width=True, hide_index=True)


def _safe_run_name(pattern: str, job: dict[str, object]) -> str:
    values = {
        "company": str(job.get("company", "") or "company"),
        "title": str(job.get("title", "") or "job"),
        "job_id": str(job.get("job_id", job.get("id", "")))[:8],
    }
    try:
        raw = pattern.format(**values)
    except Exception:
        raw = f"{values['company']}_{values['title']}"
    raw = raw.strip() or "mass_apply_job"
    return raw[:120]


def _project_id_for_job(
    job: dict[str, object], projects_by_job: dict[str, list[dict[str, object]]]
) -> str:
    latest = str(job.get("latest_project_id", "") or "").strip()
    if latest:
        return latest
    project_candidates = projects_by_job.get(str(job.get("id", "")), [])
    if not project_candidates:
        return ""
    completed = [
        project
        for project in project_candidates
        if str(project.get("status", "")) == "completed"
    ]
    selected = completed[0] if completed else project_candidates[0]
    return str(selected.get("id", "") or "")


def _download_artifact_for_job(
    backend: LocalBackend, *, uid: str, project_id: str
) -> dict[str, object] | None:
    if not project_id:
        return None
    artifacts = backend.list_artifacts(uid=uid, project_id=project_id)
    if not artifacts:
        return None
    preferred_name = _default_artifact_name(artifacts)
    for artifact in artifacts:
        if _artifact_display_name(artifact) == preferred_name:
            return artifact
    return artifacts[0]


def _sync_finished_run_artifacts(
    controller: ResumeRunController,
    backend: LocalBackend,
    uid: str,
    batch_run: dict[str, object] | None = None,
) -> bool:
    status = controller.status
    project_id = status.project_id.strip()
    if not project_id or project_id == "-":
        return False
    if status.state not in {"completed", "failed", "stopped"}:
        return False

    sync_state = st.session_state.setdefault("synced_run_states", {})
    sync_key = f"{status.state}|{status.output_dir}|{status.exit_code}"
    if sync_state.get(project_id) == sync_key:
        return True

    output_dir_text = status.output_dir.strip()
    output_dir: Path | None = None
    if output_dir_text and output_dir_text != "-":
        output_dir = Path(output_dir_text)

    try:
        if output_dir and output_dir.exists():
            backend.replace_project_artifacts_from_local(
                uid=uid, project_id=project_id, output_dir=output_dir
            )
            shutil.rmtree(output_dir, ignore_errors=True)
        if status.state == "completed":
            backend.update_project_status(
                uid=uid, project_id=project_id, status="completed"
            )
            backend.update_job_generation_status_for_project(
                uid=uid, project_id=project_id, status="completed"
            )
        else:
            backend.update_project_status(
                uid=uid,
                project_id=project_id,
                status="failed",
                error_message=f"Run ended with status '{status.state}' (exit code: {status.exit_code}).",
            )
            backend.update_job_generation_status_for_project(
                uid=uid, project_id=project_id, status="failed"
            )
        active_batch_run = batch_run or st.session_state.get("active_mass_apply_run")
        if (
            isinstance(active_batch_run, dict)
            and active_batch_run.get("project_id") == project_id
        ):
            item_status = "completed" if status.state == "completed" else "failed"
            backend.update_batch_item_status(
                uid=uid,
                item_id=str(active_batch_run.get("item_id", "")),
                status=item_status,
                project_id=project_id,
                error_message=""
                if item_status == "completed"
                else f"Run ended with status '{status.state}' (exit code: {status.exit_code}).",
            )
            st.session_state.pop("active_mass_apply_run", None)
        sync_state[project_id] = sync_key
        return True
    except Exception as exc:
        st.session_state["last_sync_error"] = str(exc)
        return False


def _sync_finished_batch_runs(backend: LocalBackend, uid: str) -> None:
    controllers = _ensure_batch_controllers()
    meta = _ensure_batch_run_meta()
    for run_id, controller in list(controllers.items()):
        controller.poll()
        run_meta = meta.get(run_id, {})
        if _sync_finished_run_artifacts(
            controller, backend, uid, batch_run=run_meta
        ):
            if not controller.is_running():
                controllers.pop(run_id, None)
                meta.pop(run_id, None)


def _apply_omissions_to_payload(
    *,
    profile: dict[str, Any],
    resume_data: dict[str, Any],
    omissions: dict[str, object],
) -> tuple[dict[str, Any], dict[str, Any]]:
    rendered_profile = json.loads(json.dumps(profile))
    rendered_resume = json.loads(json.dumps(resume_data))

    if omissions.get("no_education"):
        rendered_profile["education"] = []
    if omissions.get("no_photo"):
        rendered_profile.pop("photo", None)
    if omissions.get("no_objective"):
        rendered_resume["objective"] = None
    if omissions.get("no_skills"):
        rendered_resume["skills"] = None
    if omissions.get("no_projects"):
        rendered_resume["projects"] = None
    if omissions.get("no_experience"):
        rendered_resume["experience"] = None
    if omissions.get("no_activities"):
        rendered_resume["activities"] = None
    if omissions.get("no_applying_for"):
        rendered_resume["applying_for"] = None
    return rendered_profile, rendered_resume


def _artifact_by_names(
    artifacts: list[dict[str, object]], names: tuple[str, ...]
) -> dict[str, object] | None:
    by_name = {_artifact_display_name(artifact): artifact for artifact in artifacts}
    for name in names:
        artifact = by_name.get(name)
        if artifact:
            return artifact
    return None


def _rerender_project_with_omissions(
    *,
    backend: LocalBackend,
    uid: str,
    project_id: str,
    omissions: dict[str, object],
) -> None:
    artifacts = backend.list_artifacts(uid=uid, project_id=project_id)
    source_json = _artifact_by_names(
        artifacts, ("final_resume.source.json", "final_resume.json")
    )
    if source_json is None:
        json_artifacts = [
            artifact
            for artifact in artifacts
            if str(artifact.get("file_name", "")).lower().endswith(".json")
        ]
        json_artifacts.sort(
            key=lambda artifact: int(artifact.get("iteration") or -1),
            reverse=True,
        )
        source_json = json_artifacts[0] if json_artifacts else None
    if source_json is None:
        raise ValueError(
            "This project has no saved resume JSON. Re-run generation once to enable fast visibility edits."
        )

    source_path = Path(str(source_json.get("storage_path", "")))
    resume_data = json.loads(source_path.read_text(encoding="utf-8"))
    if not isinstance(resume_data, dict):
        raise ValueError("Saved resume JSON is not an object.")

    work_dir = WORKSPACE_ROOT / ".resumer_gui" / uid / "rerender" / project_id
    if work_dir.exists():
        shutil.rmtree(work_dir, ignore_errors=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    for artifact in artifacts:
        storage_path = Path(str(artifact.get("storage_path", "")))
        file_name = _artifact_display_name(artifact)
        if storage_path.exists() and file_name:
            shutil.copy2(storage_path, work_dir / file_name)

    profile, rendered_resume = _apply_omissions_to_payload(
        profile=backend.get_truth_json(uid),
        resume_data=resume_data,
        omissions=omissions,
    )

    from src.resumer.tools.pdf_tools import render_resume_artifacts

    render_resume_artifacts(
        profile=profile,
        resume_data=rendered_resume,
        output_dir=work_dir,
        stem="final_resume",
    )
    backend.replace_project_artifacts_from_local(
        uid=uid, project_id=project_id, output_dir=work_dir
    )
    shutil.rmtree(work_dir, ignore_errors=True)


def _render_auth_panel(backend: LocalBackend) -> None:
    user = _get_auth_user()
    with st.container(border=True):
        if user:
            left, right = st.columns([4, 1])
            with left:
                st.markdown(
                    (
                        "<div class='card-header'>"
                        "<div class='card-title'>Resumer</div>"
                        f"<div class='card-header-right'>Active Profile: {html.escape(user['email'])}</div>"
                        "</div>"
                    ),
                    unsafe_allow_html=True,
                )
            with right:
                if st.button("Switch", use_container_width=True):
                    _clear_auth_user()
                    st.rerun()
            return

        st.markdown(
            "<div class='card-title' style='margin-bottom:0.75rem;'>Choose Local Profile</div>",
            unsafe_allow_html=True,
        )

        users = backend.list_users()
        if users:
            user_ids = [str(item["id"]) for item in users]
            selected_user_id = st.selectbox(
                "Existing Profiles",
                options=user_ids,
                format_func=lambda user_id: next(
                    (
                        str(item.get("display_name", "Profile"))
                        for item in users
                        if str(item.get("id", "")) == user_id
                    ),
                    user_id,
                ),
                key="local_profile_selector",
            )
            if st.button("Use Selected Profile", use_container_width=True):
                try:
                    user_obj = backend.use_user(selected_user_id)
                    _set_auth_user(user_obj)
                    backend.get_truth_json(user_obj.uid)
                    st.rerun()
                except Exception as exc:
                    st.error(f"Could not switch profile: {exc}")

        st.markdown("---")
        new_profile_name = st.text_input(
            "Create new profile",
            value="",
            placeholder="e.g. John Local",
            key="create_local_profile_name",
        )
        if st.button("Create Profile", use_container_width=True):
            try:
                fallback_name = f"Profile {len(users) + 1}"
                profile_name = new_profile_name.strip() or fallback_name
                user_obj = backend.create_user(profile_name)
                _set_auth_user(user_obj)
                backend.get_truth_json(user_obj.uid)
                st.rerun()
            except Exception as exc:
                st.error(f"Could not create profile: {exc}")


def _render_resume_panel(
    controller: ResumeRunController, backend: LocalBackend, uid: str
) -> None:
    projects = backend.list_projects(uid)
    with st.container(border=True):
        st.markdown("<div class='card-title'>Projects</div>", unsafe_allow_html=True)
        if not projects:
            st.info(
                "No projects yet. Run the pipeline to create your first local project."
            )
            return

        project_ids = [str(p.get("id", "")) for p in projects]
        project_map = {str(p.get("id", "")): p for p in projects}
        selected_project_id = st.session_state.get("selected_project_id")
        if selected_project_id not in project_map:
            selected_project_id = project_ids[0]
        selected_project_id = st.selectbox(
            "Project",
            options=project_ids,
            index=project_ids.index(selected_project_id),
            format_func=lambda pid: _project_display_label(project_map[pid]),
            key="project_selector",
        )
        st.session_state["selected_project_id"] = selected_project_id
        selected_project = project_map[selected_project_id]
        st.caption(f"Status: {selected_project.get('status', 'unknown')}")

        artifacts = backend.list_artifacts(uid=uid, project_id=selected_project_id)
        if not artifacts:
            st.warning("No artifacts uploaded yet for this project.")
        else:
            artifact_names = [_artifact_display_name(a) for a in artifacts]
            default_name = _default_artifact_name(artifacts)
            artifact_map = {name: a for name, a in zip(artifact_names, artifacts)}
            selected_artifact_name = st.selectbox(
                "Resume File",
                options=artifact_names,
                index=artifact_names.index(default_name)
                if default_name in artifact_names
                else 0,
                key=f"artifact_selector_{selected_project_id}",
            )
            selected_artifact = artifact_map[selected_artifact_name]
            storage_path = str(selected_artifact.get("storage_path", "")).strip()
            mime_type = str(selected_artifact.get("mime_type", "")).strip().lower()
            payload = backend.download_bytes(storage_path)

            if mime_type == "application/pdf":
                signed_url = backend.signed_url(storage_path, ttl_minutes=60)
                preview_url = signed_url
                if not signed_url.startswith(("http://", "https://", "file://")):
                    local_url = _local_file_url(Path(signed_url))
                    if local_url:
                        preview_url = local_url
                    else:
                        preview_url = Path(signed_url).as_uri()
                safe_url = html.escape(preview_url)
                st.markdown(
                    f"""
                    <div class='preview-shell'>
                        <object data='{safe_url}' type='application/pdf' width='100%' height='800'>
                            <embed src='{safe_url}' type='application/pdf' width='100%' height='800' />
                            <iframe src='{safe_url}' width='100%' height='800' style='border:none;'></iframe>
                        </object>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f"<div class='preview-caption'>Open directly: <a href='{safe_url}' target='_blank'>new tab ↗</a></div>",
                    unsafe_allow_html=True,
                )
            else:
                text = payload.decode("utf-8", errors="replace")
                st.code(text, language="markdown")

            st.download_button(
                "⬇  Download",
                data=payload,
                file_name=selected_artifact_name,
                mime=mime_type or "application/octet-stream",
                use_container_width=True,
                key=f"download_{selected_project_id}_{selected_artifact_name}",
            )

            with st.expander("Render Section Visibility", expanded=False):
                st.caption(
                    "Rebuilds the selected project's final PDF/markdown from saved resume JSON without another LLM call."
                )
                project_omissions = _omissions_editor(
                    f"project_visibility_{selected_project_id}"
                )
                if st.button(
                    "Apply Visibility to This Project",
                    use_container_width=True,
                    key=f"rerender_project_{selected_project_id}",
                ):
                    try:
                        _rerender_project_with_omissions(
                            backend=backend,
                            uid=uid,
                            project_id=selected_project_id,
                            omissions=project_omissions,
                        )
                        st.success("Project re-rendered.")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Re-render failed: {exc}")

        st.markdown("---")
        delete_disabled = (
            controller.is_running()
            and controller.status.project_id == selected_project_id
        )
        confirm = st.checkbox(
            "Confirm delete selected project",
            key=f"confirm_delete_{selected_project_id}",
        )
        if st.button(
            "🗑 Delete Project",
            use_container_width=True,
            disabled=delete_disabled,
            key=f"delete_project_{selected_project_id}",
        ):
            if not confirm:
                st.warning("Enable confirmation checkbox to delete this project.")
            else:
                try:
                    backend.delete_project(uid=uid, project_id=selected_project_id)
                    synced = st.session_state.setdefault("synced_run_states", {})
                    if isinstance(synced, dict):
                        synced.pop(selected_project_id, None)
                    st.session_state.pop("selected_project_id", None)
                    st.rerun()
                except Exception as exc:
                    st.error(f"Delete failed: {exc}")


def _render_logs_panel(controller: ResumeRunController) -> None:
    status = controller.status
    agent = status.active_agent if status.active_agent not in {"", "-"} else "Idle"
    signal = _signal_markup(status.state)

    with st.container(border=True):
        st.markdown(
            (
                "<div class='card-header'>"
                "<div class='card-title'>Logs</div>"
                f"<div class='card-header-right'>Current Agent - {html.escape(agent)}"
                f" <span class='signal'>{signal}</span></div>"
                "</div>"
            ),
            unsafe_allow_html=True,
        )

        gui_tmp_dir = WORKSPACE_ROOT / ".resumer_gui"
        gui_tmp_dir.mkdir(parents=True, exist_ok=True)
        log_view_path = gui_tmp_dir / "log_console.html"
        log_view_path.write_text(_build_logs_html(controller.logs), encoding="utf-8")

        log_url = _local_file_url(log_view_path)
        if log_url:
            st.iframe(f"{log_url}?t={int(time.time() * 1000)}", height=480)
        else:
            st.warning("Could not render logs panel. Local preview server unavailable.")


def _find_jobs_logs_key(uid: str) -> str:
    return f"find_jobs_logs_{uid}"


def _find_jobs_state_key(uid: str, name: str) -> str:
    return f"find_jobs_{name}_{uid}"


def _get_find_jobs_logs(uid: str) -> list[LogEntry]:
    key = _find_jobs_logs_key(uid)
    logs = st.session_state.get(key)
    if not isinstance(logs, list):
        logs = []
        st.session_state[key] = logs
    return logs


def _append_find_jobs_log(
    uid: str,
    text: str,
    *,
    level: str = "info",
    stream: str = "find-jobs",
) -> None:
    logs = _get_find_jobs_logs(uid)
    logs.append(LogEntry(ts=time.time(), stream=stream, text=text, level=level))
    if len(logs) > 1200:
        st.session_state[_find_jobs_logs_key(uid)] = logs[-1200:]


def _clear_find_jobs_logs(uid: str) -> None:
    st.session_state[_find_jobs_logs_key(uid)] = []


def _close_find_jobs_driver(uid: str) -> None:
    key = _find_jobs_state_key(uid, "driver")
    driver = st.session_state.pop(key, None)
    if driver is None:
        return
    try:
        driver.quit()
    except Exception:
        return


def _render_find_jobs_logs_panel(uid: str) -> None:
    with st.container(border=True):
        st.markdown(
            "<div class='card-title'>Find Jobs Logs</div>",
            unsafe_allow_html=True,
        )
        logs = _get_find_jobs_logs(uid)
        gui_tmp_dir = WORKSPACE_ROOT / ".resumer_gui"
        gui_tmp_dir.mkdir(parents=True, exist_ok=True)
        log_view_path = gui_tmp_dir / f"find_jobs_log_console_{uid}.html"
        log_view_path.write_text(_build_logs_html(logs), encoding="utf-8")

        log_url = _local_file_url(log_view_path)
        if log_url:
            st.iframe(f"{log_url}?t={int(time.time() * 1000)}", height=340)
        else:
            st.warning("Could not render logs panel. Local preview server unavailable.")


def _render_controls_panel(
    controller: ResumeRunController, backend: LocalBackend, uid: str
) -> None:
    if "run_name_input" not in st.session_state:
        st.session_state.run_name_input = (
            f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        )

    preset_names = list(MODEL_PRESETS.keys())

    with st.container(border=True):
        st.markdown(
            "<div class='card-title' style='margin-bottom:0.75rem;'>Run Controls</div>",
            unsafe_allow_html=True,
        )

        with st.form("pipeline_controls_form"):
            left, right = st.columns([1.55, 1])

            with left:
                st.text_input("Run Name", key="run_name_input")
                jd_path = st.text_input(
                    "Job Description File Path", value="input/job_description.txt"
                )
                preset = st.selectbox("Model Selection", options=preset_names, index=0)

            with right:
                max_iterations = st.slider(
                    "No of Iterations", min_value=1, max_value=20, value=10
                )
                st.markdown(
                    f"<div class='mono-note' style='margin-top:0.35rem; margin-bottom:0.9rem;'>"
                    f"Status: {_status_badge(controller.status.state)}</div>",
                    unsafe_allow_html=True,
                )
                start_run = st.form_submit_button(
                    "▶  Run Pipeline",
                    disabled=controller.is_running(),
                    use_container_width=True,
                )
                stop_run = st.form_submit_button(
                    "⏹  Stop",
                    disabled=not controller.is_running(),
                    use_container_width=True,
                )

            preset_model, preset_key_env = MODEL_PRESETS[preset]
            custom_model = ""
            custom_key_env = ""
            if preset == "Custom":
                custom_model = st.text_input(
                    "Custom Model ID", value="mistral/mistral-large-latest"
                )
                custom_key_env = st.text_input(
                    "API Key Env Variable", value="MISTRAL_API_KEY"
                )

            final_model = custom_model.strip() if preset == "Custom" else preset_model
            final_key_env = (
                custom_key_env.strip() if preset == "Custom" else preset_key_env
            )

            with st.expander("Optional Section Visibility", expanded=False):
                c1, c2 = st.columns(2)
                with c1:
                    no_objective = st.checkbox("Hide objective")
                    no_skills = st.checkbox("Hide skills")
                    no_experience = st.checkbox("Hide experience")
                    no_applying_for = st.checkbox("Hide applying-for subtitle")
                with c2:
                    no_education = st.checkbox("Hide education")
                    no_projects = st.checkbox("Hide projects")
                    no_activities = st.checkbox("Hide activities")
                    no_photo = st.checkbox("Hide photo")

        if stop_run:
            controller.stop_run()
            st.rerun()

        if start_run:
            omissions = {
                "no_objective": no_objective,
                "no_education": no_education,
                "no_skills": no_skills,
                "no_projects": no_projects,
                "no_experience": no_experience,
                "no_activities": no_activities,
                "no_applying_for": no_applying_for,
                "no_photo": no_photo,
            }
            try:
                resolved_jd = _resolve_workspace_path(jd_path.strip())
                if not resolved_jd.exists():
                    raise FileNotFoundError(f"JD file not found: {resolved_jd}")
                jd_text = resolved_jd.read_text(encoding="utf-8").strip()
                truth_json = backend.get_truth_json(uid)
                profile_path = _profile_temp_path(uid)
                profile_path.write_text(
                    json.dumps(truth_json, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )

                run_name = st.session_state.run_name_input.strip() or "run_manual"
                project_id = backend.create_project(
                    uid=uid,
                    name=run_name,
                    job_description=jd_text,
                )
                local_run_label = f"{run_name}_{project_id[:8]}"
                try:
                    controller.start_run(
                        jd_path=str(resolved_jd),
                        data_path=str(profile_path),
                        max_iterations=max_iterations,
                        job_label=local_run_label,
                        model=final_model,
                        api_key_env=final_key_env,
                        omissions=omissions,
                        project_id=project_id,
                        project_name=run_name,
                    )
                except Exception as exc:
                    backend.update_project_status(
                        uid=uid,
                        project_id=project_id,
                        status="failed",
                        error_message=str(exc),
                    )
                    raise
                st.session_state["selected_project_id"] = project_id
                st.rerun()
            except Exception as exc:
                st.error(f"Could not start run: {exc}")


def _render_find_jobs_tab(backend: LocalBackend, uid: str) -> None:
    parsed_jobs_key = _find_jobs_state_key(uid, "parsed_jobs")
    driver_key = _find_jobs_state_key(uid, "driver")
    awaiting_verification_key = _find_jobs_state_key(uid, "awaiting_verification")
    source_html_key = _find_jobs_state_key(uid, "source_html")

    parsed_jobs = st.session_state.get(parsed_jobs_key, [])
    if not isinstance(parsed_jobs, list):
        parsed_jobs = []
        st.session_state[parsed_jobs_key] = parsed_jobs

    with st.container(border=True):
        st.markdown("<div class='card-title'>Find Jobs</div>", unsafe_allow_html=True)
        st.caption(
            "Step 1 parses all jobs from saved Indeed HTML. Step 2 waits for your manual verification, then scrapes and saves all descriptions."
        )
        controls_left, controls_right = st.columns(2, gap="medium")

        with controls_left:
            st.markdown("#### Step 1: Parse job list from HTML")
            source_mode = st.radio(
                "HTML source",
                options=["Path", "Uploaded file"],
                horizontal=True,
                key="find_jobs_html_source_mode",
            )
            html_path = st.text_input(
                "Saved Indeed search HTML",
                value="src/job_organizer/sample.html",
                key="find_jobs_html_path",
            )
            uploaded_html = st.file_uploader(
                "Or upload HTML", type=["html", "htm"], key="find_jobs_html_upload"
            )
            parse_col, clear_col = st.columns(2)
            with parse_col:
                if st.button("Parse Jobs (Step 1)", use_container_width=True):
                    try:
                        if source_mode == "Uploaded file":
                            if uploaded_html is None:
                                raise ValueError(
                                    "No uploaded HTML selected. Choose a file or switch source to Path."
                                )
                            import_dir = (
                                WORKSPACE_ROOT / ".resumer_gui" / uid / "imports"
                            )
                            import_dir.mkdir(parents=True, exist_ok=True)
                            target = import_dir / uploaded_html.name
                            target.write_bytes(uploaded_html.getvalue())
                        else:
                            target = _resolve_workspace_path(html_path)

                        _close_find_jobs_driver(uid)
                        jobs, stats = parse_indeed_html_with_stats(str(target))
                        st.session_state[parsed_jobs_key] = jobs
                        st.session_state[source_html_key] = str(target)
                        st.session_state[awaiting_verification_key] = False
                        _append_find_jobs_log(
                            uid,
                            (
                                f"[STEP 1] Source={source_mode}; file={target}; "
                                f"JS={stats['js_results']}, DOM={stats['dom_results']}, "
                                f"merged={stats['merged_results']}."
                            ),
                            level="event",
                        )
                        parsed_jobs = jobs
                        st.success(
                            (
                                f"Step 1 complete: parsed {len(jobs)} jobs "
                                f"(JS {stats['js_results']} + DOM {stats['dom_results']} -> {stats['merged_results']})."
                            )
                        )
                    except Exception as exc:
                        _append_find_jobs_log(
                            uid, f"[STEP 1] Parse failed: {exc}", level="error"
                        )
                        st.error(f"Step 1 parse failed: {exc}")
            with clear_col:
                if st.button("Clear Parsed Jobs", use_container_width=True):
                    _close_find_jobs_driver(uid)
                    st.session_state.pop(parsed_jobs_key, None)
                    st.session_state.pop(source_html_key, None)
                    st.session_state.pop(awaiting_verification_key, None)
                    _append_find_jobs_log(
                        uid,
                        "Cleared parsed jobs and verification session.",
                        level="warn",
                    )
                    st.rerun()

            parsed_count = len(parsed_jobs)
            st.caption(f"Parsed jobs in memory: {parsed_count}")
            if parsed_jobs:
                preview_rows = [
                    {
                        "Title": str(job.get("Title", "")),
                        "Company": str(job.get("Company", "")),
                        "Location": str(job.get("Location", "")),
                        "Relative Time": str(job.get("Relative Time", "")),
                        "Salary": str(job.get("Salary", "")),
                    }
                    for job in parsed_jobs
                ]
                st.dataframe(preview_rows, use_container_width=True, hide_index=True)

        with controls_right:
            st.markdown("#### Step 2: Verify and scrape descriptions")
            wait_seconds = st.slider(
                "Max wait per job (seconds)",
                min_value=20,
                max_value=300,
                value=120,
                key="find_jobs_wait_seconds",
            )

            if st.button(
                "Open Verification Browser (Step 2A)", use_container_width=True
            ):
                if not parsed_jobs:
                    st.error("Run Step 1 first to parse jobs.")
                else:
                    try:
                        _close_find_jobs_driver(uid)

                        def _log_open(message: str) -> None:
                            _append_find_jobs_log(
                                uid, f"[STEP 2A] {message}", level="event"
                            )

                        driver = start_indeed_verification_session(
                            parsed_jobs,
                            log=_log_open,
                        )
                        st.session_state[driver_key] = driver
                        st.session_state[awaiting_verification_key] = True
                        _append_find_jobs_log(
                            uid,
                            "[STEP 2A] Browser launched. Waiting for manual verification.",
                            level="event",
                        )
                        st.success(
                            "Browser opened. Complete the CAPTCHA/human check there, then click Step 2B."
                        )
                    except Exception as exc:
                        _append_find_jobs_log(
                            uid,
                            f"[STEP 2A] Failed to open verification browser: {exc}",
                            level="error",
                        )
                        st.error(f"Could not open verification browser: {exc}")

            driver = st.session_state.get(driver_key)
            if driver is not None:
                st.info(
                    "Complete human verification in the browser first. Then click Step 2B to begin scraping."
                )

            if st.button(
                "I Completed Verification — Scrape + Save (Step 2B)",
                use_container_width=True,
            ):
                if not parsed_jobs:
                    st.error("Run Step 1 first to parse jobs.")
                elif driver is None:
                    st.error("Run Step 2A first to open the verification browser.")
                else:
                    try:
                        if is_human_check_page_source(driver.page_source):
                            _append_find_jobs_log(
                                uid,
                                "[STEP 2B] Verification still detected. Waiting for user to finish CAPTCHA.",
                                level="warn",
                            )
                            st.warning(
                                "Verification page is still active in the browser. Complete it fully, then click Step 2B again."
                            )
                        else:
                            _append_find_jobs_log(
                                uid,
                                f"[STEP 2B] Starting scrape for {len(parsed_jobs)} jobs.",
                                level="event",
                            )

                            def _log_scrape(message: str) -> None:
                                level = "warn" if "FAILED" in message else "info"
                                _append_find_jobs_log(
                                    uid, f"[STEP 2B] {message}", level=level
                                )

                            jobs = scrape_indeed_descriptions_with_driver(
                                parsed_jobs,
                                driver=driver,
                                wait_seconds=wait_seconds,
                                log=_log_scrape,
                            )
                            result = backend.upsert_jobs(
                                uid=uid, jobs=jobs, source="indeed"
                            )
                            failed = sum(
                                1
                                for job in jobs
                                if str(job.get("Description", "")).strip() == "FAILED"
                            )
                            st.session_state[parsed_jobs_key] = jobs
                            _append_find_jobs_log(
                                uid,
                                (
                                    "[STEP 2B] Saved jobs to library: "
                                    f"{result['inserted']} inserted, {result['updated']} updated, "
                                    f"{result['skipped']} skipped, {failed} description failures."
                                ),
                                level="success",
                            )
                            _close_find_jobs_driver(uid)
                            st.session_state[awaiting_verification_key] = False
                            st.success(
                                f"Step 2 complete. Saved {result['inserted']} new jobs, updated {result['updated']}, skipped {result['skipped']}. Description scrape failures: {failed}."
                            )
                            st.rerun()
                    except HumanVerificationRequired as exc:
                        st.session_state[parsed_jobs_key] = parsed_jobs
                        partial = backend.upsert_jobs(
                            uid=uid, jobs=parsed_jobs, source="indeed"
                        )
                        _append_find_jobs_log(
                            uid,
                            (
                                "[STEP 2B] Verification interrupted scraping. "
                                f"Progress saved ({partial['inserted']} inserted, {partial['updated']} updated, {partial['skipped']} skipped). "
                                "Complete verification in the same browser and press Step 2B again to resume."
                            ),
                            level="warn",
                        )
                        st.session_state[awaiting_verification_key] = True
                        st.warning(str(exc))
                    except Exception as exc:
                        _append_find_jobs_log(
                            uid, f"[STEP 2B] Scrape failed: {exc}", level="error"
                        )
                        st.error(f"Step 2 scrape failed: {exc}")

            if st.button("Close Verification Browser", use_container_width=True):
                _close_find_jobs_driver(uid)
                st.session_state[awaiting_verification_key] = False
                _append_find_jobs_log(uid, "Closed verification browser.", level="warn")
                st.rerun()

            if st.button("Clear Find Jobs Logs", use_container_width=True):
                _clear_find_jobs_logs(uid)
                st.rerun()

    _render_find_jobs_logs_panel(uid)

    jobs = backend.list_jobs(uid)
    ready_count = sum(1 for job in jobs if job.get("description_status") == "ready")
    generated_count = sum(1 for job in jobs if int(job.get("resume_count", 0) or 0) > 0)
    applied_count = sum(1 for job in jobs if job.get("application_status") == "applied")

    with st.container(border=True):
        st.markdown("<div class='card-title'>Job Library</div>", unsafe_allow_html=True)
        m1, m2, m3, m4 = st.columns(4)
        with m1:
            st.metric("Jobs", len(jobs))
        with m2:
            st.metric("Ready", ready_count)
        with m3:
            st.metric("Generated", generated_count)
        with m4:
            st.metric("Applied", applied_count)

        filters = st.columns([1, 1, 2])
        with filters[0]:
            desc_filter = st.selectbox(
                "Description",
                options=["all", "ready", "missing", "failed"],
                key="find_jobs_desc_filter",
            )
        with filters[1]:
            app_filter = st.selectbox(
                "Application Status",
                options=[
                    "all",
                    "new",
                    "saved",
                    "queued",
                    "generating",
                    "generated",
                    "applied",
                    "skipped",
                    "failed",
                ],
                key="find_jobs_app_filter",
            )
        with filters[2]:
            search = st.text_input("Search", key="find_jobs_search").strip().lower()

        filtered = []
        for job in jobs:
            haystack = " ".join(
                str(job.get(key, ""))
                for key in ("title", "company", "location", "description", "salary")
            ).lower()
            if desc_filter != "all" and job.get("description_status") != desc_filter:
                continue
            if app_filter != "all" and job.get("application_status") != app_filter:
                continue
            if search and search not in haystack:
                continue
            filtered.append(job)

        if not filtered:
            st.info("No jobs match the current filters.")
            return

        _render_jobs_table(filtered)

        job_ids = [str(job["id"]) for job in filtered]
        job_map = {str(job["id"]): job for job in filtered}
        selected_job_id = st.selectbox(
            "Inspect Job",
            options=job_ids,
            format_func=lambda job_id: _job_display_label(job_map[job_id]),
            key="find_jobs_selected_job",
        )
        selected_job = job_map[selected_job_id]

        detail_left, detail_right = st.columns([2, 1])
        with detail_left:
            st.markdown("#### Description")
            description = str(selected_job.get("description", "") or "")
            if description:
                st.text_area(
                    "Description",
                    value=description,
                    height=320,
                    label_visibility="collapsed",
                    disabled=True,
                )
            else:
                st.warning(
                    "No full job description stored yet. Run the HTML scrape workflow above to capture it."
                )
        with detail_right:
            st.markdown("#### Actions")
            if selected_job.get("source_url"):
                st.link_button(
                    "Open Job",
                    str(selected_job["source_url"]),
                    use_container_width=True,
                )
            if selected_job.get("apply_url"):
                st.link_button(
                    "Open Apply",
                    str(selected_job["apply_url"]),
                    use_container_width=True,
                )
            action_cols = st.columns(2)
            with action_cols[0]:
                if st.button(
                    "Save", use_container_width=True, key=f"save_job_{selected_job_id}"
                ):
                    backend.update_job_state(
                        uid=uid, job_id=selected_job_id, status="saved"
                    )
                    st.rerun()
                if st.button(
                    "Applied",
                    use_container_width=True,
                    key=f"applied_job_{selected_job_id}",
                ):
                    backend.update_job_state(
                        uid=uid, job_id=selected_job_id, status="applied"
                    )
                    st.rerun()
            with action_cols[1]:
                if st.button(
                    "Skip", use_container_width=True, key=f"skip_job_{selected_job_id}"
                ):
                    backend.update_job_state(
                        uid=uid, job_id=selected_job_id, status="skipped"
                    )
                    st.rerun()
                if st.button(
                    "Reset",
                    use_container_width=True,
                    key=f"reset_job_{selected_job_id}",
                ):
                    backend.update_job_state(
                        uid=uid, job_id=selected_job_id, status="new"
                    )
                    st.rerun()

            st.markdown("---")
            delete_confirm = st.checkbox(
                "Confirm delete this job from the database",
                key=f"delete_job_confirm_{selected_job_id}",
            )
            if st.button(
                "Delete Job",
                use_container_width=True,
                key=f"delete_job_{selected_job_id}",
            ):
                if not delete_confirm:
                    st.warning("Enable the confirmation checkbox to delete this job.")
                else:
                    backend.delete_job(uid=uid, job_id=selected_job_id)
                    st.session_state.pop("find_jobs_selected_job", None)
                    st.rerun()

            notes = st.text_area(
                "Notes",
                value=str(selected_job.get("notes", "") or ""),
                height=140,
                key=f"notes_{selected_job_id}",
            )
            if st.button(
                "Save Notes",
                use_container_width=True,
                key=f"notes_save_{selected_job_id}",
            ):
                backend.update_job_state(
                    uid=uid,
                    job_id=selected_job_id,
                    status=str(selected_job.get("application_status", "new")),
                    notes=notes,
                )
                st.rerun()


def _start_mass_apply_item(
    *,
    controller: ResumeRunController,
    backend: LocalBackend,
    uid: str,
    batch: dict[str, object],
    item: dict[str, object],
    model_slot: int = 0,
) -> dict[str, object]:
    settings = dict(batch.get("global_settings", {}) or {})
    overrides = dict(item.get("settings_override", {}) or {})
    omissions = dict(settings.get("omissions", {}) or {})
    omissions.update(overrides.get("omissions", {}) or {})

    if overrides.get("max_iterations"):
        settings["max_iterations"] = int(overrides["max_iterations"])
    if overrides.get("model"):
        settings["model"] = str(overrides["model"])
    if overrides.get("api_key_env"):
        settings["api_key_env"] = str(overrides["api_key_env"])
    if not overrides.get("model"):
        model_pool = _model_pool_from_settings(settings)
        if model_pool:
            selected_model = model_pool[model_slot % len(model_pool)]
            settings["model"] = selected_model["model"]
            settings["api_key_env"] = selected_model["api_key_env"]

    job_id = str(item["job_id"])
    run_name = str(overrides.get("run_name") or "").strip()
    if not run_name:
        run_name = _safe_run_name(
            str(settings.get("name_pattern", "{company}_{title}")), item
        )

    job_text = _job_description_for_pipeline(item)
    if not job_text:
        raise ValueError("Selected job does not have usable job description text.")

    work_dir = WORKSPACE_ROOT / ".resumer_gui" / uid / "mass_apply" / str(batch["id"])
    work_dir.mkdir(parents=True, exist_ok=True)
    jd_path = work_dir / f"{str(item['id'])}.job.txt"
    jd_path.write_text(job_text, encoding="utf-8")

    profile_path = _profile_temp_path(uid)
    profile_path.write_text(
        json.dumps(backend.get_truth_json(uid), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    project_id = backend.create_project(
        uid=uid,
        job_id=job_id,
        name=run_name,
        job_description=job_text,
    )
    backend.update_batch_item_status(
        uid=uid, item_id=str(item["id"]), status="running", project_id=project_id
    )
    backend.update_batch_status(uid=uid, batch_id=str(batch["id"]), status="running")
    local_run_label = f"{run_name}_{project_id[:8]}"
    controller.start_run(
        jd_path=str(jd_path),
        data_path=str(profile_path),
        max_iterations=int(settings.get("max_iterations", 10)),
        job_label=local_run_label,
        model=str(settings.get("model", "")),
        api_key_env=str(settings.get("api_key_env", "")),
        omissions=omissions,
        project_id=project_id,
        project_name=run_name,
    )
    run_meta = {
        "batch_id": str(batch["id"]),
        "item_id": str(item["id"]),
        "project_id": project_id,
        "model": str(settings.get("model", "")),
    }
    st.session_state["selected_project_id"] = project_id
    return run_meta


def _render_mass_apply_tab(
    controller: ResumeRunController, backend: LocalBackend, uid: str
) -> None:
    jobs = backend.list_jobs(uid)
    ready_jobs = [
        job
        for job in jobs
        if job.get("description_status") == "ready"
        and job.get("application_status") not in {"queued", "applied", "skipped"}
    ]

    st.markdown(
        "<div class='card-title'>Batch Processing</div>", unsafe_allow_html=True
    )
    st.caption(
        "Create batches of job-specific resume generations. Queue execution can run multiple subprocesses at once and rotate across selected models."
    )

    builder_tab, queue_tab = st.tabs(["Batch Builder", "Batch Queue Executor"])

    with builder_tab:
        with st.container(border=True):
            st.markdown(
                "<div class='card-title' style='margin-bottom:0.75rem;'>Batch Builder</div>",
                unsafe_allow_html=True,
            )

            with st.expander("Job Selection", expanded=True):
                batch_name = st.text_input(
                    "Batch Name",
                    value=f"mass_apply_{datetime.now().strftime('%Y%m%d_%H%M')}",
                )
                include_existing = st.checkbox(
                    "Show jobs that already have resumes",
                    value=False,
                    key="mass_apply_include_existing",
                )
                selectable_jobs = [
                    job
                    for job in ready_jobs
                    if include_existing or int(job.get("resume_count", 0) or 0) == 0
                ]
                selectable_map = {str(job["id"]): job for job in selectable_jobs}
                shortlist_key = "mass_apply_shortlist_ids"
                index_key = "mass_apply_review_index"
                signature_key = "mass_apply_review_signature"
                preferred_index_key = "mass_apply_review_preferred_index"

                current_signature = (
                    "|".join(str(job["id"]) for job in selectable_jobs)
                    + f":{int(include_existing)}"
                )
                if st.session_state.get(signature_key) != current_signature:
                    previous_index = int(st.session_state.get(index_key, 0) or 0)
                    preferred_index = st.session_state.pop(preferred_index_key, None)
                    st.session_state[signature_key] = current_signature
                    chosen_index = (
                        int(preferred_index)
                        if isinstance(preferred_index, int)
                        else previous_index
                    )
                    if selectable_jobs:
                        st.session_state[index_key] = max(
                            0, min(chosen_index, len(selectable_jobs) - 1)
                        )
                    else:
                        st.session_state[index_key] = 0

                shortlisted_ids = st.session_state.get(shortlist_key, [])
                if not isinstance(shortlisted_ids, list):
                    shortlisted_ids = []
                valid_ids = {str(job["id"]) for job in selectable_jobs}
                shortlisted_ids = [
                    job_id for job_id in shortlisted_ids if job_id in valid_ids
                ]
                st.session_state[shortlist_key] = shortlisted_ids

                auto_cols = st.columns([1.6, 1])
                with auto_cols[0]:
                    if st.button(
                        "Auto-mark >0 years experience as Not Interested",
                        use_container_width=True,
                        key="mass_apply_auto_not_interested_experience",
                    ):
                        marked_job_ids: set[str] = set()
                        for job in selectable_jobs:
                            job_id = str(job.get("id", ""))
                            min_years = _minimum_experience_years_required(
                                str(job.get("title", "") or ""),
                                str(job.get("description", "") or ""),
                            )
                            if min_years is not None and min_years > 0:
                                backend.update_job_state(
                                    uid=uid,
                                    job_id=job_id,
                                    status="skipped",
                                    notes="Not interested (auto: >0 years experience required)",
                                )
                                marked_job_ids.add(job_id)

                        if marked_job_ids:
                            shortlisted_ids = [
                                job_id
                                for job_id in shortlisted_ids
                                if job_id not in marked_job_ids
                            ]
                            st.session_state[shortlist_key] = shortlisted_ids
                            st.session_state[preferred_index_key] = int(
                                st.session_state.get(index_key, 0) or 0
                            )
                            st.success(
                                f"Marked {len(marked_job_ids)} jobs as Not Interested (>0 years experience)."
                            )
                        else:
                            st.info(
                                "No jobs in this review set explicitly require more than 0 years."
                            )
                        st.rerun()
                with auto_cols[1]:
                    if st.button(
                        "Clear Shortlist",
                        use_container_width=True,
                        key="mass_apply_clear_shortlist",
                    ):
                        st.session_state[shortlist_key] = []
                        st.rerun()

                if not selectable_jobs:
                    st.info(
                        "No jobs available for review. Import more jobs or enable 'Show jobs that already have resumes'."
                    )
                    selected_job_ids: list[str] = shortlisted_ids
                else:
                    idx = int(st.session_state.get(index_key, 0) or 0)
                    idx = max(0, min(idx, len(selectable_jobs) - 1))
                    st.session_state[index_key] = idx

                    current_job = selectable_jobs[idx]
                    current_job_id = str(current_job["id"])
                    is_shortlisted = current_job_id in shortlisted_ids
                    is_not_interested = (
                        str(current_job.get("application_status", "")) == "skipped"
                    )

                    st.caption(f"Review {idx + 1}/{len(selectable_jobs)}")
                    st.markdown(f"**{html.escape(_job_display_label(current_job))}**")
                    st.caption(
                        " · ".join(
                            part
                            for part in (
                                str(current_job.get("location", "") or ""),
                                str(current_job.get("salary", "") or ""),
                            )
                            if part
                        )
                        or "No location/salary metadata"
                    )

                    link_cols = st.columns(2)
                    with link_cols[0]:
                        if current_job.get("source_url"):
                            st.link_button(
                                "Open Job",
                                str(current_job["source_url"]),
                                use_container_width=True,
                            )
                    with link_cols[1]:
                        if current_job.get("apply_url"):
                            st.link_button(
                                "Open Apply",
                                str(current_job["apply_url"]),
                                use_container_width=True,
                            )

                    description = str(current_job.get("description", "") or "")
                    analysis = _analyze_job_text_local(
                        str(current_job.get("title", "") or ""),
                        description,
                    )
                    st.markdown(
                        "\n".join(
                            [
                                f"**Type:** {analysis['role_type']}",
                                f"**Domain:** {analysis['domain']}",
                                f"**Experience Asked:** {analysis['experience']}",
                            ]
                        )
                    )
                    if description:
                        st.text_area(
                            "Final Job Description",
                            value=description,
                            height=260,
                            disabled=True,
                            key=f"mass_apply_review_description_{current_job_id}_{idx}",
                        )
                    else:
                        st.warning("This job has no description text.")

                    nav1, nav2, nav3, nav4 = st.columns(4)
                    with nav1:
                        if st.button(
                            "⬅ Previous",
                            use_container_width=True,
                            disabled=idx == 0,
                            key=f"mass_apply_prev_{current_job_id}_{idx}",
                        ):
                            st.session_state[preferred_index_key] = max(0, idx - 1)
                            st.session_state[index_key] = max(0, idx - 1)
                            st.rerun()
                    with nav2:
                        if st.button(
                            "Next ➡",
                            use_container_width=True,
                            disabled=idx >= len(selectable_jobs) - 1,
                            key=f"mass_apply_next_{current_job_id}_{idx}",
                        ):
                            st.session_state[preferred_index_key] = min(
                                len(selectable_jobs) - 1, idx + 1
                            )
                            st.session_state[index_key] = min(
                                len(selectable_jobs) - 1, idx + 1
                            )
                            st.rerun()
                    with nav3:
                        interest_label = (
                            "Remove from Batch" if is_shortlisted else "Interested"
                        )
                        if st.button(
                            interest_label,
                            use_container_width=True,
                            key=f"mass_apply_interest_{current_job_id}_{idx}",
                        ):
                            if is_shortlisted:
                                shortlisted_ids = [
                                    job_id
                                    for job_id in shortlisted_ids
                                    if job_id != current_job_id
                                ]
                            else:
                                if is_not_interested:
                                    backend.update_job_state(
                                        uid=uid, job_id=current_job_id, status="new"
                                    )
                                shortlisted_ids.append(current_job_id)
                                st.session_state[preferred_index_key] = min(
                                    len(selectable_jobs) - 1, idx + 1
                                )
                                st.session_state[index_key] = min(
                                    len(selectable_jobs) - 1, idx + 1
                                )
                            st.session_state[shortlist_key] = shortlisted_ids
                            st.rerun()
                    with nav4:
                        not_interest_label = (
                            "Undo Not Interested"
                            if is_not_interested
                            else "Not Interested"
                        )
                        if st.button(
                            not_interest_label,
                            use_container_width=True,
                            key=f"mass_apply_not_interested_{current_job_id}_{idx}",
                        ):
                            if is_not_interested:
                                backend.update_job_state(
                                    uid=uid,
                                    job_id=current_job_id,
                                    status="new",
                                    notes="",
                                )
                            else:
                                backend.update_job_state(
                                    uid=uid,
                                    job_id=current_job_id,
                                    status="skipped",
                                    notes="Not interested",
                                )
                                st.session_state[preferred_index_key] = idx
                                shortlisted_ids = [
                                    job_id
                                    for job_id in shortlisted_ids
                                    if job_id != current_job_id
                                ]
                                st.session_state[index_key] = min(
                                    len(selectable_jobs) - 1, idx + 1
                                )
                                st.session_state[shortlist_key] = shortlisted_ids
                            st.rerun()

                    st.markdown("---")
                    selected_job_ids = shortlisted_ids
                    selected_map = {str(job["id"]): job for job in selectable_jobs}
                    selected_jobs = [
                        selected_map[job_id]
                        for job_id in selected_job_ids
                        if job_id in selected_map
                    ]
                    st.caption(f"Shortlisted for batch: {len(selected_jobs)}")
                    if selected_jobs:
                        st.dataframe(
                            [
                                {
                                    "Company": job.get("company", ""),
                                    "Title": job.get("title", ""),
                                    "Location": job.get("location", ""),
                                    "Salary": job.get("salary", ""),
                                    "Status": job.get("application_status", ""),
                                    "Resumes": job.get("resume_count", 0),
                                }
                                for job in selected_jobs
                            ],
                            use_container_width=True,
                            hide_index=True,
                        )

            with st.expander("Global Generation Settings", expanded=True):
                settings = _settings_from_model_form("mass_apply_global")

            overrides_by_job: dict[str, dict[str, object]] = {}
            with st.expander("Per Job Overrides", expanded=bool(selected_job_ids)):
                if not selected_job_ids:
                    st.info("Select jobs to configure per-job overrides.")
                for job_id in selected_job_ids[:20]:
                    job = selectable_map[job_id]
                    st.markdown(f"**{html.escape(_job_display_label(job))}**")
                    c1, c2 = st.columns([2, 1])
                    with c1:
                        run_name = st.text_input(
                            "Run name override",
                            value="",
                            key=f"override_name_{job_id}",
                        )
                    with c2:
                        iterations = st.number_input(
                            "Iterations override",
                            min_value=0,
                            max_value=20,
                            value=0,
                            key=f"override_iters_{job_id}",
                        )
                    override: dict[str, object] = {}
                    if run_name.strip():
                        override["run_name"] = run_name.strip()
                    if iterations:
                        override["max_iterations"] = int(iterations)
                    if override:
                        overrides_by_job[job_id] = override
                if len(selected_job_ids) > 20:
                    st.warning("Showing overrides for the first 20 selected jobs only.")

            create_batch = st.button("Create Batch", use_container_width=True)

            if create_batch:
                try:
                    if not selected_job_ids:
                        raise ValueError(
                            "Select at least one job before creating a batch."
                        )
                    batch_id = backend.create_batch(
                        uid=uid,
                        name=batch_name,
                        job_ids=selected_job_ids,
                        global_settings=settings,
                        overrides_by_job=overrides_by_job,
                    )
                    st.session_state["selected_batch_id"] = batch_id
                    st.success("Batch created.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Could not create batch: {exc}")

    with queue_tab:
        batches = backend.list_batches(uid)
        with st.container(border=True):
            st.markdown(
                "<div class='card-title'>Batch Queue</div>", unsafe_allow_html=True
            )
            if not batches:
                st.info("No batches yet.")
                return

            batch_ids = [str(batch["id"]) for batch in batches]
            batch_map = {str(batch["id"]): batch for batch in batches}
            selected_batch_id = st.session_state.get("selected_batch_id")
            if selected_batch_id not in batch_map:
                selected_batch_id = batch_ids[0]
            selected_batch_id = st.selectbox(
                "Batch",
                options=batch_ids,
                index=batch_ids.index(selected_batch_id),
                format_func=lambda batch_id: _batch_display_label(batch_map[batch_id]),
                key="batch_selector",
            )
            st.session_state["selected_batch_id"] = selected_batch_id
            batch = backend.get_batch(uid=uid, batch_id=selected_batch_id)
            if batch is None:
                st.warning("Selected batch no longer exists.")
                return

            items = backend.list_batch_items(uid=uid, batch_id=selected_batch_id)
            batch_settings = dict(batch.get("global_settings", {}) or {})
            batch_parallel_runs = max(
                1,
                min(
                    BATCH_MAX_PARALLEL_LIMIT,
                    int(batch_settings.get("parallel_runs", 1) or 1),
                ),
            )
            active_meta = _ensure_batch_run_meta()
            selected_batch_active_run_ids = [
                run_id
                for run_id, run_meta in active_meta.items()
                if isinstance(run_meta, dict)
                and run_meta.get("batch_id") == selected_batch_id
            ]
            selected_batch_running = sum(
                1
                for run_id in selected_batch_active_run_ids
                if _ensure_batch_controllers().get(run_id)
                and _ensure_batch_controllers()[run_id].is_running()
            )

            with st.expander("Batch Controls", expanded=True):
                st.caption(
                    f"Parallel limit: {batch_parallel_runs} · Active runs: {selected_batch_running} · Model pool: {_model_pool_labels(batch_settings)}"
                )
                c1, c2 = st.columns(2)
                with c1:
                    if st.button(
                        "Start / Resume",
                        use_container_width=True,
                    ):
                        backend.update_batch_status(
                            uid=uid, batch_id=selected_batch_id, status="running"
                        )
                        st.rerun()
                    if st.button("Pause After Current", use_container_width=True):
                        backend.update_batch_status(
                            uid=uid, batch_id=selected_batch_id, status="paused"
                        )
                        st.rerun()
                with c2:
                    if st.button(
                        "Stop Active Runs",
                        use_container_width=True,
                        disabled=selected_batch_running == 0,
                    ):
                        controllers = _ensure_batch_controllers()
                        for run_id in selected_batch_active_run_ids:
                            active_controller = controllers.get(run_id)
                            if active_controller and active_controller.is_running():
                                active_controller.stop_run()
                        st.rerun()
                    if st.button("Retry Failed", use_container_width=True):
                        for item in items:
                            if item.get("status") == "failed":
                                backend.update_batch_item_status(
                                    uid=uid,
                                    item_id=str(item["id"]),
                                    status="queued",
                                    error_message="",
                                )
                        backend.update_batch_status(
                            uid=uid, batch_id=selected_batch_id, status="draft"
                        )
                        st.rerun()

            with st.expander("Editable Batch Defaults", expanded=False):
                st.caption(
                    "Changes apply to queued/retried jobs. Completed projects can be re-rendered below without another model call."
                )
                edit_cols = st.columns(2)
                with edit_cols[0]:
                    updated_parallel = st.slider(
                        "Parallel Batch Runs",
                        min_value=1,
                        max_value=BATCH_MAX_PARALLEL_LIMIT,
                        value=batch_parallel_runs,
                        key=f"edit_parallel_{selected_batch_id}",
                    )
                    updated_max_iterations = st.slider(
                        "No of Iterations",
                        min_value=1,
                        max_value=20,
                        value=int(batch_settings.get("max_iterations", 10) or 10),
                        key=f"edit_iters_{selected_batch_id}",
                    )
                with edit_cols[1]:
                    updated_skip_existing = st.checkbox(
                        "Skip jobs that already have a completed resume",
                        value=bool(batch_settings.get("skip_existing", True)),
                        key=f"edit_skip_existing_{selected_batch_id}",
                    )
                    updated_name_pattern = st.text_input(
                        "Run Name Pattern",
                        value=str(
                            batch_settings.get("name_pattern", "{company}_{title}")
                            or "{company}_{title}"
                        ),
                        key=f"edit_name_pattern_{selected_batch_id}",
                    )
                updated_model_pool_text = st.text_area(
                    "Model Pool (one per line: model_id | API_KEY_ENV)",
                    value=_model_pool_text(batch_settings),
                    key=f"edit_model_pool_{selected_batch_id}",
                    height=100,
                )
                updated_omissions = _omissions_editor(
                    f"edit_omissions_{selected_batch_id}",
                    dict(batch_settings.get("omissions", {}) or {}),
                )
                if st.button(
                    "Save Batch Defaults",
                    use_container_width=True,
                    key=f"save_batch_defaults_{selected_batch_id}",
                ):
                    updated_settings = dict(batch_settings)
                    updated_settings.update(
                        {
                            "parallel_runs": updated_parallel,
                            "max_iterations": updated_max_iterations,
                            "skip_existing": updated_skip_existing,
                            "name_pattern": updated_name_pattern,
                            "model_pool": _parse_model_pool_text(
                                updated_model_pool_text
                            ),
                            "omissions": updated_omissions,
                        }
                    )
                    backend.update_batch_settings(
                        uid=uid,
                        batch_id=selected_batch_id,
                        global_settings=updated_settings,
                    )
                    st.success("Batch defaults updated.")
                    st.rerun()

            with st.expander("Re-render Completed Projects", expanded=False):
                st.caption(
                    "Applies section visibility to completed jobs using saved resume JSON. This updates final PDF/markdown artifacts without running the LLM again."
                )
                render_omissions = _omissions_editor(
                    f"rerender_batch_{selected_batch_id}",
                    dict(batch_settings.get("omissions", {}) or {}),
                )
                completed_project_ids = [
                    str(item.get("project_id", ""))
                    for item in items
                    if item.get("status") == "completed"
                    and str(item.get("project_id", "")).strip()
                ]
                if st.button(
                    f"Apply Visibility to {len(completed_project_ids)} Completed",
                    use_container_width=True,
                    disabled=not completed_project_ids,
                    key=f"rerender_completed_{selected_batch_id}",
                ):
                    ok_count = 0
                    errors: list[str] = []
                    for project_id in completed_project_ids:
                        try:
                            _rerender_project_with_omissions(
                                backend=backend,
                                uid=uid,
                                project_id=project_id,
                                omissions=render_omissions,
                            )
                            ok_count += 1
                        except Exception as exc:
                            errors.append(f"{project_id[:8]}: {exc}")
                    if ok_count:
                        st.success(f"Re-rendered {ok_count} project(s).")
                    if errors:
                        st.warning("Some projects could not be re-rendered.")
                        st.code("\n".join(errors), language="text")
                    st.rerun()

            with st.expander("Batch Jobs", expanded=True):
                item_rows = [
                    {
                        "Company": item.get("company", ""),
                        "Title": item.get("title", ""),
                        "Status": item.get("status", ""),
                        "Project": item.get("project_id", ""),
                        "Error": item.get("error_message", ""),
                    }
                    for item in items
                ]
                st.dataframe(item_rows, use_container_width=True, hide_index=True)

            with st.expander("Danger Zone", expanded=False):
                deleting_active = selected_batch_running > 0
                confirm_delete = st.checkbox(
                    "Confirm delete selected batch",
                    key=f"delete_batch_confirm_{selected_batch_id}",
                )
                st.caption("Deleting a batch keeps generated resume projects intact.")
                if st.button(
                    "Delete Batch",
                    use_container_width=True,
                    disabled=deleting_active,
                    key=f"delete_batch_{selected_batch_id}",
                ):
                    if not confirm_delete:
                        st.warning(
                            "Enable the confirmation checkbox to delete this batch."
                        )
                    else:
                        backend.delete_batch(uid=uid, batch_id=selected_batch_id)
                        st.session_state.pop("selected_batch_id", None)
                        st.rerun()

            refreshed_batch = backend.get_batch(uid=uid, batch_id=selected_batch_id)
            if refreshed_batch and refreshed_batch.get("status") == "running":
                refreshed_items = backend.list_batch_items(
                    uid=uid, batch_id=selected_batch_id
                )
                active_meta = _ensure_batch_run_meta()
                controllers = _ensure_batch_controllers()
                active_for_batch = [
                    run_id
                    for run_id, run_meta in active_meta.items()
                    if isinstance(run_meta, dict)
                    and run_meta.get("batch_id") == selected_batch_id
                    and controllers.get(run_id)
                    and controllers[run_id].is_running()
                ]
                refreshed_settings = dict(
                    refreshed_batch.get("global_settings", {}) or {}
                )
                refreshed_parallel_runs = max(
                    1,
                    min(
                        BATCH_MAX_PARALLEL_LIMIT,
                        int(refreshed_settings.get("parallel_runs", 1) or 1),
                    ),
                )
                launched_any = False
                while len(active_for_batch) < refreshed_parallel_runs:
                    next_item = backend.next_batch_item(
                        uid=uid, batch_id=selected_batch_id
                    )
                    if next_item is None:
                        break

                    if refreshed_batch.get("global_settings", {}).get(
                        "skip_existing"
                    ):
                        existing_job = backend.get_job(
                            uid=uid, job_id=str(next_item["job_id"])
                        )
                        if (
                            existing_job
                            and int(existing_job.get("resume_count", 0) or 0) > 0
                        ):
                            backend.update_batch_item_status(
                                uid=uid,
                                item_id=str(next_item["id"]),
                                status="skipped",
                                error_message="Skipped because this job already has a resume.",
                            )
                            refreshed_items = backend.list_batch_items(
                                uid=uid, batch_id=selected_batch_id
                            )
                            continue

                    run_id = f"{selected_batch_id}:{next_item['id']}"
                    run_controller = ResumeRunController(WORKSPACE_ROOT)
                    controllers[run_id] = run_controller
                    model_slot = len(active_for_batch) + len(
                        [
                            item
                            for item in refreshed_items
                            if item.get("status")
                            in {"completed", "failed", "skipped", "running"}
                        ]
                    )
                    try:
                        run_meta = _start_mass_apply_item(
                            controller=run_controller,
                            backend=backend,
                            uid=uid,
                            batch=refreshed_batch,
                            item=next_item,
                            model_slot=model_slot,
                        )
                        active_meta[run_id] = run_meta
                        active_for_batch.append(run_id)
                        launched_any = True
                    except Exception as exc:
                        controllers.pop(run_id, None)
                        if refreshed_batch.get("global_settings", {}).get(
                            "skip_existing"
                        ):
                            pass
                        backend.update_batch_item_status(
                            uid=uid,
                            item_id=str(next_item["id"]),
                            status="failed",
                            error_message=str(exc),
                        )
                        backend.update_job_state(
                            uid=uid,
                            job_id=str(next_item["job_id"]),
                            status="failed",
                            notes=str(exc),
                        )
                        st.error(f"Could not start next job: {exc}")
                        refreshed_items = backend.list_batch_items(
                            uid=uid, batch_id=selected_batch_id
                        )
                        continue

                if launched_any:
                    st.rerun()
                elif not active_for_batch and refreshed_items and all(
                    item.get("status") in {"completed", "failed", "skipped"}
                    for item in refreshed_items
                ):
                    backend.update_batch_status(
                        uid=uid, batch_id=selected_batch_id, status="completed"
                    )
                    st.rerun()


def _render_apply_tracker_tab(backend: LocalBackend, uid: str) -> None:
    jobs = backend.list_jobs(uid)
    projects = backend.list_projects(uid)
    projects_by_job: dict[str, list[dict[str, object]]] = {}
    for project in projects:
        job_id = str(project.get("job_id", "") or "")
        if job_id:
            projects_by_job.setdefault(job_id, []).append(project)

    generated_jobs = [job for job in jobs if int(job.get("resume_count", 0) or 0) > 0]

    with st.container(border=True):
        st.markdown(
            "<div class='card-title'>Apply Tracker</div>",
            unsafe_allow_html=True,
        )
        st.caption(
            "Apply and download resumes for jobs that already have generated resume projects."
        )

        if not generated_jobs:
            st.info(
                "No generated resumes yet. Build resumes from Batch Processing first."
            )
            return

        filter_cols = st.columns([1, 2])
        with filter_cols[0]:
            status_filter = st.selectbox(
                "Status",
                options=["all", "not applied", "applied"],
                key="apply_tracker_status_filter",
            )
        with filter_cols[1]:
            search = st.text_input("Search", key="apply_tracker_search").strip().lower()

        visible_jobs: list[dict[str, object]] = []
        for job in generated_jobs:
            is_applied = str(job.get("application_status", "")) == "applied"
            haystack = " ".join(
                str(job.get(key, ""))
                for key in ("title", "company", "location", "salary")
            ).lower()
            if status_filter == "applied" and not is_applied:
                continue
            if status_filter == "not applied" and is_applied:
                continue
            if search and search not in haystack:
                continue
            visible_jobs.append(job)

        if not visible_jobs:
            st.info("No generated jobs match the current filters.")
            return

        for job in visible_jobs:
            job_id = str(job.get("id", ""))
            project_id = _project_id_for_job(job, projects_by_job)
            artifact = _download_artifact_for_job(
                backend, uid=uid, project_id=project_id
            )
            applied_now = str(job.get("application_status", "")) == "applied"
            label = _job_display_label(job)

            with st.container(border=True):
                st.markdown(f"**{html.escape(label)}**")
                if job.get("location") or job.get("salary"):
                    st.caption(
                        " · ".join(
                            part
                            for part in (
                                str(job.get("location", "") or ""),
                                str(job.get("salary", "") or ""),
                            )
                            if part
                        )
                    )

                action_cols = st.columns([1, 1, 1])
                with action_cols[0]:
                    apply_url = str(job.get("apply_url", "") or "").strip()
                    if apply_url:
                        st.link_button(
                            "Apply Now",
                            apply_url,
                            use_container_width=True,
                            key=f"tracker_apply_{job_id}",
                        )
                    else:
                        st.button(
                            "No Apply Link",
                            disabled=True,
                            use_container_width=True,
                            key=f"tracker_no_apply_{job_id}",
                        )
                with action_cols[1]:
                    if artifact:
                        artifact_name = _artifact_display_name(artifact)
                        storage_path = str(artifact.get("storage_path", "") or "")
                        mime_type = str(artifact.get("mime_type", "") or "")
                        st.download_button(
                            "Download Resume",
                            data=backend.download_bytes(storage_path),
                            file_name=artifact_name,
                            mime=mime_type or "application/octet-stream",
                            use_container_width=True,
                            key=f"tracker_download_{job_id}_{artifact_name}",
                        )
                    else:
                        st.button(
                            "No Resume File",
                            disabled=True,
                            use_container_width=True,
                            key=f"tracker_no_resume_{job_id}",
                        )
                with action_cols[2]:
                    checked = st.checkbox(
                        "Applied",
                        value=applied_now,
                        key=f"tracker_applied_{job_id}",
                    )
                    if checked != applied_now:
                        backend.update_job_state(
                            uid=uid,
                            job_id=job_id,
                            status="applied" if checked else "generated",
                            latest_project_id=project_id or None,
                        )
                        st.rerun()


def _render_profile_editor_panel(backend: LocalBackend, uid: str) -> None:
    editor_key = f"profile_editor_{uid}"
    editor_buffer_key = f"profile_editor_buffer_{uid}"
    saved_snapshot_key = f"profile_editor_saved_snapshot_{uid}"
    ace_version_key = f"profile_editor_ace_version_{uid}"
    save_confirm_key = f"profile_editor_confirm_save_{uid}"
    loaded_flag_key = f"profile_editor_loaded_{uid}"

    if ace_version_key not in st.session_state:
        st.session_state[ace_version_key] = 0

    def _set_editor_content(new_text: str, *, mark_saved: bool = False) -> None:
        st.session_state[editor_buffer_key] = new_text
        st.session_state[editor_key] = new_text
        st.session_state[ace_version_key] = (
            int(st.session_state.get(ace_version_key, 0)) + 1
        )
        if mark_saved:
            st.session_state[saved_snapshot_key] = new_text
            st.session_state[save_confirm_key] = False

    with st.container(border=True):
        st.markdown(
            "<div class='card-title'>Master Profile (truth.json)</div>",
            unsafe_allow_html=True,
        )
        st.caption(
            "Edit your full master profile here. This is saved per local profile in SQLite."
        )

        action_col1, action_col2, action_col3, action_col4, action_col5 = st.columns(5)
        with action_col1:
            refresh_clicked = st.button(
                "Reload from Local DB",
                key=f"refresh_profile_{uid}",
                use_container_width=True,
            )
        with action_col2:
            load_sample_clicked = st.button(
                "Load sample template",
                key=f"load_sample_profile_{uid}",
                use_container_width=True,
            )
        with action_col3:
            format_clicked = st.button(
                "Format JSON",
                key=f"format_profile_json_{uid}",
                use_container_width=True,
            )
        with action_col4:
            minify_clicked = st.button(
                "Minify JSON",
                key=f"minify_profile_json_{uid}",
                use_container_width=True,
            )
        with action_col5:
            validate_clicked = st.button(
                "Validate JSON",
                key=f"validate_profile_json_{uid}",
                use_container_width=True,
            )

        if refresh_clicked or not st.session_state.get(loaded_flag_key, False):
            current = backend.get_truth_json(uid)
            editor_text = json.dumps(current, indent=2, ensure_ascii=False)
            _set_editor_content(editor_text, mark_saved=True)
            st.session_state[loaded_flag_key] = True

        if load_sample_clicked:
            sample = backend.sample_truth_json()
            _set_editor_content(json.dumps(sample, indent=2, ensure_ascii=False))
            st.session_state[loaded_flag_key] = True

        if editor_buffer_key not in st.session_state:
            current = backend.get_truth_json(uid)
            editor_text = json.dumps(current, indent=2, ensure_ascii=False)
            st.session_state[editor_buffer_key] = editor_text
            st.session_state[editor_key] = editor_text
            st.session_state[saved_snapshot_key] = editor_text

        buffer_text = str(st.session_state.get(editor_buffer_key, "{}"))

        if format_clicked:
            try:
                parsed = json.loads(buffer_text)
                _set_editor_content(json.dumps(parsed, indent=2, ensure_ascii=False))
                buffer_text = str(st.session_state.get(editor_buffer_key, "{}"))
            except Exception as exc:
                st.error(f"Format failed: {exc}")

        if minify_clicked:
            try:
                parsed = json.loads(buffer_text)
                _set_editor_content(
                    json.dumps(parsed, separators=(",", ":"), ensure_ascii=False)
                )
                buffer_text = str(st.session_state.get(editor_buffer_key, "{}"))
            except Exception as exc:
                st.error(f"Minify failed: {exc}")

        workspace_col, side_col = st.columns([2.2, 1], gap="medium")

        with workspace_col:
            if st_ace is not None:
                st.caption(
                    "Editor: Ace (syntax highlighting, line numbers, Ctrl/Cmd+F search)"
                )
                ace_key = (
                    f"profile_ace_{uid}_{st.session_state.get(ace_version_key, 0)}"
                )
                ace_value = st_ace(
                    value=buffer_text,
                    language="json",
                    theme="tomorrow_night",
                    key=ace_key,
                    height=700,
                    font_size=14,
                    tab_size=2,
                    show_gutter=True,
                    wrap=True,
                    auto_update=True,
                    readonly=False,
                )
                if ace_value is not None:
                    st.session_state[editor_buffer_key] = ace_value
                    st.session_state[editor_key] = ace_value
                    buffer_text = ace_value
            else:
                st.info("Advanced editor component unavailable; using fallback editor.")
                st.text_area(
                    "truth.json",
                    key=editor_key,
                    height=700,
                )
                buffer_text = str(st.session_state.get(editor_key, "{}"))
                st.session_state[editor_buffer_key] = buffer_text

        raw_text = buffer_text
        parsed_json: Any = None
        parse_error: json.JSONDecodeError | None = None
        try:
            parsed_json = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            parse_error = exc

        is_dict = isinstance(parsed_json, dict)
        structure_warnings: list[str] = (
            _truth_structure_warnings(parsed_json) if is_dict else []
        )

        line_count = raw_text.count("\n") + 1 if raw_text else 1
        char_count = len(raw_text)
        saved_snapshot = str(st.session_state.get(saved_snapshot_key, ""))
        is_dirty = raw_text != saved_snapshot
        syntax_ok = parse_error is None

        with side_col:
            st.markdown("#### Quick Status")
            m1, m2 = st.columns(2)
            with m1:
                st.metric("Lines", line_count)
            with m2:
                st.metric("Chars", char_count)
            m3, m4 = st.columns(2)
            with m3:
                st.metric("Syntax", "OK" if syntax_ok else "Error")
            with m4:
                st.metric("Dirty", "Yes" if is_dirty else "No")
            st.caption("Tip: Ctrl/Cmd+F for search, Tab/Shift+Tab for indent.")

            st.markdown("#### Diagnostics")
            if parse_error is not None:
                st.error(
                    f"Syntax error: {parse_error.msg} (line {parse_error.lineno}, column {parse_error.colno})"
                )
                st.code(_json_error_context(raw_text, parse_error), language="text")
            elif not is_dict:
                st.error("Top-level JSON must be an object.")
            else:
                st.success("JSON syntax is valid.")
                if structure_warnings:
                    st.warning("Structure warnings found.")
                    for warning in structure_warnings:
                        st.write(f"- {warning}")
                else:
                    st.success("Structure checks passed.")

                st.markdown("#### Content Stats")
                top_keys = len(parsed_json.keys())
                projects_count = (
                    len(parsed_json.get("projects", []))
                    if isinstance(parsed_json.get("projects"), list)
                    else 0
                )
                experience_count = (
                    len(parsed_json.get("experience", []))
                    if isinstance(parsed_json.get("experience"), list)
                    else 0
                )
                ms1, ms2, ms3 = st.columns(3)
                with ms1:
                    st.metric("Keys", top_keys)
                with ms2:
                    st.metric("Projects", projects_count)
                with ms3:
                    st.metric("Experience", experience_count)

            if validate_clicked:
                if parse_error is not None or not is_dict:
                    st.error("Validation failed.")
                elif structure_warnings:
                    st.warning("Validation completed with warnings.")
                else:
                    st.success("Validation successful.")

            st.markdown("#### Path Inspector")
            path_key = f"profile_path_query_{uid}"
            st.text_input(
                "Path (e.g. personal_information.email, projects[0].description)",
                key=path_key,
            )
            inspect_clicked = st.button(
                "Inspect path",
                key=f"inspect_profile_path_{uid}",
                use_container_width=True,
            )
            if inspect_clicked:
                if not is_dict:
                    st.error("Path inspector requires valid object JSON.")
                else:
                    try:
                        value = _json_path_lookup(
                            parsed_json, st.session_state.get(path_key, "")
                        )
                        if isinstance(value, (dict, list)):
                            st.code(
                                json.dumps(value, indent=2, ensure_ascii=False),
                                language="json",
                            )
                        else:
                            st.code(str(value), language="text")
                    except Exception as exc:
                        st.error(f"Path error: {exc}")

            if is_dirty:
                st.checkbox(
                    "I reviewed the changes and want to save this profile",
                    key=save_confirm_key,
                )
            else:
                st.session_state[save_confirm_key] = False

            save_disabled = (
                parse_error is not None
                or not is_dict
                or (is_dirty and not st.session_state.get(save_confirm_key, False))
            )
            if is_dirty and not st.session_state.get(save_confirm_key, False):
                st.warning("Confirm the profile changes to enable saving.")

            if st.button(
                "Save Profile",
                key=f"save_profile_{uid}",
                use_container_width=True,
                disabled=save_disabled,
            ):
                try:
                    parsed = json.loads(raw_text)
                    if not isinstance(parsed, dict):
                        raise ValueError("Profile JSON must be a JSON object.")
                    backend.save_truth_json(uid, parsed)
                    st.session_state[saved_snapshot_key] = raw_text
                    st.success("Profile saved locally.")
                except Exception as exc:
                    st.error(f"Save failed: {exc}")

        with st.expander("Diff Preview", expanded=False):
            if not is_dirty:
                st.success("No unsaved changes.")
            else:
                diff_lines = list(
                    difflib.unified_diff(
                        saved_snapshot.splitlines(),
                        raw_text.splitlines(),
                        fromfile="last_saved",
                        tofile="editor",
                        lineterm="",
                    )
                )
                if diff_lines:
                    st.code("\n".join(diff_lines), language="diff")
                else:
                    st.info("No textual diff available.")


def main() -> None:
    st.set_page_config(
        page_title="Resumer",
        page_icon="📄",
        layout="wide",
        initial_sidebar_state="collapsed",
    )

    _inject_figma_css()
    controller = _ensure_controller()
    controller.poll()
    _poll_batch_controllers()

    backend, backend_error = _ensure_local_backend()
    if backend_error:
        st.error(backend_error)
        st.info("Local backend could not be initialized.")
        return
    if backend is None:
        st.error("Local backend unavailable.")
        return

    _render_auth_panel(backend)
    auth_user = _get_auth_user()
    if not auth_user:
        return

    uid = str(auth_user["uid"])
    _sync_finished_run_artifacts(controller, backend, uid)
    _sync_finished_batch_runs(backend, uid)
    last_sync_error = st.session_state.pop("last_sync_error", "")
    if last_sync_error:
        st.warning(f"Local sync warning: {last_sync_error}")

    resume_tab, profile_tab, find_jobs_tab, mass_apply_tab, apply_tracker_tab = st.tabs(
        [
            "Resume Studio",
            "Master Profile",
            "Find Jobs",
            "Batch Processing",
            "Apply Tracker",
        ]
    )
    with resume_tab:
        left_col, right_col = st.columns([1.5, 1.5], gap="medium")
        with left_col:
            _render_resume_panel(controller, backend, uid)
        with right_col:
            _render_logs_panel(controller)
            _render_controls_panel(controller, backend, uid)
    with profile_tab:
        _render_profile_editor_panel(backend, uid)
    with find_jobs_tab:
        _render_find_jobs_tab(backend, uid)
    with mass_apply_tab:
        _render_mass_apply_tab(controller, backend, uid)
    with apply_tracker_tab:
        _render_apply_tracker_tab(backend, uid)

    if controller.is_running() or _any_batch_controller_running():
        time.sleep(1)
        st.rerun()


if __name__ == "__main__":
    main()
