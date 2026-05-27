from __future__ import annotations

import difflib
import functools
import html
import json
import shutil
import socket
import sys
import threading
import time
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
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
    "GPT OSS 120B": ("groq/qwen/qwen3-32b", "GROQ_API_KEY"),
    "OpenRouter Mistral Large": (
        "openrouter/mistralai/mistral-large-latest",
        "OPENROUTER_API_KEY",
    ),
    "Kimi K2.6 (Cloudflare)": (
        "cloudflare/@cf/moonshotai/kimi-k2.6",
        "CLOUDFLARE_AUTH_TOKEN",
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


def _sync_finished_run_artifacts(
    controller: ResumeRunController, backend: LocalBackend, uid: str
) -> None:
    status = controller.status
    project_id = status.project_id.strip()
    if not project_id or project_id == "-":
        return
    if status.state not in {"completed", "failed", "stopped"}:
        return

    sync_state = st.session_state.setdefault("synced_run_states", {})
    sync_key = f"{status.state}|{status.output_dir}|{status.exit_code}"
    if sync_state.get(project_id) == sync_key:
        return

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
        else:
            backend.update_project_status(
                uid=uid,
                project_id=project_id,
                status="failed",
                error_message=f"Run ended with status '{status.state}' (exit code: {status.exit_code}).",
            )
        sync_state[project_id] = sync_key
    except Exception as exc:
        st.session_state["last_sync_error"] = str(exc)


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
            custom_api_base = ""
            if preset == "Custom":
                custom_model = st.text_input(
                    "Custom Model ID", value="anthropic/gemini-3.5-flash-low"
                )
                custom_key_env = st.text_input(
                    "API Key Env Variable", value="OPENAI_API_KEY"
                )
                custom_api_base = st.text_input("API Base URL (optional)", value="")

            final_model = custom_model.strip() if preset == "Custom" else preset_model
            final_key_env = (
                custom_key_env.strip() if preset == "Custom" else preset_key_env
            )
            final_api_base = custom_api_base.strip() if preset == "Custom" else ""

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
                        job_label=local_run_label,
                        model=final_model,
                        api_key_env=final_key_env,
                        api_base=final_api_base,
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

            save_disabled = (
                parse_error is not None
                or not is_dict
                or (is_dirty and not st.session_state.get(save_confirm_key, False))
            )
            if is_dirty and not st.session_state.get(save_confirm_key, False):
                st.warning("Review diff and confirm before saving.")

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
                    st.session_state[save_confirm_key] = False
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
                st.checkbox(
                    "I reviewed the diff and want to save these changes",
                    key=save_confirm_key,
                )


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
    last_sync_error = st.session_state.pop("last_sync_error", "")
    if last_sync_error:
        st.warning(f"Local sync warning: {last_sync_error}")

    resume_tab, profile_tab = st.tabs(["Resume Studio", "Master Profile"])
    with resume_tab:
        left_col, right_col = st.columns([1.5, 1.5], gap="medium")
        with left_col:
            _render_resume_panel(controller, backend, uid)
        with right_col:
            _render_logs_panel(controller)
            _render_controls_panel(controller, backend, uid)
    with profile_tab:
        _render_profile_editor_panel(backend, uid)

    if controller.is_running():
        time.sleep(1)
        st.rerun()


if __name__ == "__main__":
    main()
