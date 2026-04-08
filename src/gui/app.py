from __future__ import annotations

import functools
import html
import socket
import sys
import threading
import time
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote

import streamlit as st

APP_DIR = Path(__file__).resolve().parent
SRC_DIR = APP_DIR.parent
WORKSPACE_ROOT = SRC_DIR.parent

for _p in (WORKSPACE_ROOT, SRC_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from gui.services.runner import LogEntry, ResumeRunController  # noqa: E402


OUTPUTS_ROOT = WORKSPACE_ROOT / "outputs"

MODEL_PRESETS: dict[str, tuple[str, str]] = {
    "Mistral Large (stable)": ("mistral/mistral-large-latest", "MISTRAL_API_KEY"),
    "Mistral Medium": ("mistral/mistral-medium-latest", "MISTRAL_API_KEY"),
    "Gemini 3 Flash": ("gemini/gemini-3-flash-preview", "GEMINI_KEY"),
    "Gemini 3.1 Flash lite": ("gemini/gemini-3.1-flash-preview", "GEMINI_KEY"),
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


def _inject_figma_css() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;600;700;800&family=JetBrains+Mono:wght@400;500;700&display=swap');

        :root {
            --bg: #0b0c10;
            --panel: #111317;
            --panel-2: #06080d;
            --line: #3b3f45;
            --line-soft: #2a2d31;
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
                radial-gradient(900px 620px at 15% -8%, rgba(36, 204, 90, 0.08), transparent 60%),
                radial-gradient(900px 620px at 110% 0%, rgba(255, 255, 255, 0.03), transparent 55%),
                var(--bg);
        }

        [data-testid="stHeader"],
        [data-testid="stToolbar"],
        [data-testid="stSidebar"] {
            display: none;
        }

        .block-container {
            padding-top: 1.1rem;
            padding-bottom: 1rem;
            max-width: 1600px;
        }

        .fig-card {
            background: linear-gradient(180deg, rgba(18, 21, 27, 0.98), rgba(10, 12, 16, 0.98));
            border: 1px solid var(--line);
            border-radius: 8px;
            padding: 1.15rem 1.25rem 1.1rem;
            box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.02);
        }

        .fig-card + .fig-card {
            margin-top: 1rem;
        }

        .fig-card-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 0.8rem;
            margin-bottom: 0.7rem;
        }

        .fig-title {
            font-size: 2.55rem;
            font-weight: 800;
            letter-spacing: -0.02em;
            color: #f1f2f5;
            line-height: 1;
        }

        .fig-card-title {
            font-size: 2.2rem;
            font-weight: 800;
            letter-spacing: -0.02em;
            color: #f1f2f5;
            line-height: 1;
        }

        .fig-right-meta {
            text-align: right;
            font-size: 0.96rem;
            color: #d9dde5;
            font-weight: 700;
            white-space: nowrap;
        }

        .fig-label {
            font-size: 1.02rem;
            font-weight: 700;
            color: #e8eaf0;
            margin-bottom: 0.1rem;
        }

        .fig-small-label {
            color: var(--muted);
            text-transform: uppercase;
            letter-spacing: 0.08em;
            font-size: 0.67rem;
            margin-bottom: 0.2rem;
        }

        .signal {
            display: inline-flex;
            gap: 6px;
            align-items: center;
            margin-left: 0.55rem;
        }

        .signal span {
            display: inline-block;
            width: 34px;
            height: 7px;
            border-radius: 999px;
            background: #4a4a4a;
        }

        .signal .on { background: var(--green); }
        .signal .warn { background: var(--yellow); }
        .signal .bad { background: var(--red); }

        .preview-shell {
            border: 1px solid var(--line-soft);
            border-radius: 7px;
            overflow: hidden;
            background: #f7f7f8;
            min-height: 760px;
        }

        .preview-caption {
            margin-top: 0.55rem;
            color: var(--muted);
            font-size: 0.8rem;
        }

        .controls-note {
            color: var(--muted);
            font-size: 0.83rem;
            margin-bottom: 0.4rem;
        }

        .stTextInput > label,
        .stSelectbox > label,
        .stSlider > label,
        .stCheckbox > label,
        .stMarkdown p {
            font-family: 'Manrope', sans-serif;
        }

        .stTextInput input,
        .stSelectbox [data-baseweb="select"] div,
        .stSlider [data-baseweb="slider"] {
            background: #181b21;
            border-color: #2e3238;
            color: #f1f2f5;
        }

        .stButton > button,
        .stDownloadButton > button,
        .stFormSubmitButton > button {
            border-radius: 8px;
            border: 1px solid #2f343a;
            background: #1a1e25;
            color: #f2f4f7;
            font-weight: 700;
            height: 2.55rem;
        }

        .stButton > button:hover,
        .stDownloadButton > button:hover,
        .stFormSubmitButton > button:hover {
            border-color: #4e545d;
            background: #232934;
        }

        .mono-note {
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.78rem;
            color: var(--muted);
        }

        .run-state-grid {
            margin-top: 0.6rem;
            border: 1px solid var(--line-soft);
            border-radius: 8px;
            overflow: hidden;
        }

        .run-state-row {
            display: grid;
            grid-template-columns: 130px 1fr;
            gap: 0;
        }

        .run-state-row:not(:last-child) {
            border-bottom: 1px solid var(--line-soft);
        }

        .run-state-k,
        .run-state-v {
            padding: 0.48rem 0.6rem;
            font-size: 0.82rem;
        }

        .run-state-k {
            color: var(--muted);
            background: rgba(255, 255, 255, 0.01);
            text-transform: uppercase;
            letter-spacing: 0.06em;
        }

        .run-state-v {
            font-family: 'JetBrains Mono', monospace;
            color: #ebedf2;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
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


def _list_output_folders() -> list[Path]:
    if not OUTPUTS_ROOT.exists():
        return []
    folders = [path for path in OUTPUTS_ROOT.iterdir() if path.is_dir()]
    folders.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return folders


def _list_folder_artifacts(folder: Path) -> list[Path]:
    artifacts = [
        path
        for path in folder.iterdir()
        if path.is_file() and path.suffix.lower() in {".pdf", ".md"}
    ]
    artifacts.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return artifacts


def _default_artifact_name(artifacts: list[Path]) -> str:
    preferred = ["final_resume.pdf", "final_resume.md", "draft_v2.md", "draft_v1.md"]
    by_name = {item.name: item for item in artifacts}
    for name in preferred:
        if name in by_name:
            return name
    return artifacts[0].name


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
                    f"<span class='log-stream'>{html.escape(entry.stream.upper())}</span>",
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
    :root {{
      --line-soft: #20242a;
      --text: #d8dde6;
      --muted: #8f96a3;
      --event: #82b4ff;
      --warn: #f6bd3f;
      --bad: #e35a67;
      --good: #28cc67;
    }}
    body {{ margin: 0; background: transparent; font-family: 'JetBrains Mono', monospace; }}
    .log-shell {{
      background: #05070c;
      border: 1px solid var(--line-soft);
      border-radius: 8px;
      padding: 0.45rem 0.5rem;
      height: 470px;
      overflow-y: auto;
      box-sizing: border-box;
    }}
    .log-row {{
      display: grid;
      grid-template-columns: 80px 76px 1fr;
      gap: 9px;
      align-items: start;
      font-size: 0.77rem;
      line-height: 1.3;
      padding: 0.17rem 0.22rem;
      border-radius: 6px;
      margin-bottom: 2px;
      color: var(--text);
    }}
    .log-row:hover {{ background: rgba(130, 180, 255, 0.06); }}
    .log-time {{ color: var(--muted); }}
    .log-stream {{ color: #67da93; font-weight: 700; letter-spacing: 0.03em; }}
    .log-msg {{ margin: 0; white-space: pre-wrap; word-break: break-word; tab-size: 4; }}
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


def _render_resume_panel(controller: ResumeRunController) -> None:

    folders = _list_output_folders()
    if not folders:
        st.markdown(
            "<div class='fig-card-header'><div class='fig-title'>Resumer</div><div class='fig-right-meta'>Resume Name</div></div>",
            unsafe_allow_html=True,
        )
        st.info("No artifacts yet. Launch a run to generate resume previews.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    folder_labels = [folder.name for folder in folders]
    active_folder_name = ""
    if controller.status.output_dir not in {"", "-"}:
        active_folder_name = Path(controller.status.output_dir).name

    folder_index = (
        folder_labels.index(active_folder_name)
        if active_folder_name in folder_labels
        else 0
    )
    selected_folder = st.selectbox(
        "Run Folder",
        options=folder_labels,
        index=folder_index,
        key="resume_folder_selector",
    )

    selected_folder_path = OUTPUTS_ROOT / selected_folder
    artifacts = _list_folder_artifacts(selected_folder_path)

    if not artifacts:
        st.warning("This run folder has no previewable artifacts.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    artifact_names = [item.name for item in artifacts]
    default_artifact = _default_artifact_name(artifacts)
    default_index = artifact_names.index(default_artifact)

    head_left, head_right = st.columns([1.2, 1])
    with head_left:
        st.markdown("<div class='fig-title'>Resumer</div>", unsafe_allow_html=True)
    with head_right:
        st.markdown("<div class='fig-label'>Resume Name</div>", unsafe_allow_html=True)
        selected_artifact_name = st.selectbox(
            "Resume Name",
            options=artifact_names,
            index=default_index,
            key=f"resume_artifact_{selected_folder}",
            label_visibility="collapsed",
        )

    selected_artifact_path = next(
        (item for item in artifacts if item.name == selected_artifact_name),
        artifacts[0],
    )

    with selected_artifact_path.open("rb") as file:
        payload = file.read()

    if selected_artifact_path.suffix.lower() == ".pdf":
        pdf_url = _local_file_url(selected_artifact_path)
        if pdf_url:
            safe_url = html.escape(pdf_url)
            st.markdown(
                f"""
                <div class='preview-shell'>
                    <object data='{safe_url}' type='application/pdf' width='100%' height='760'>
                        <embed src='{safe_url}' type='application/pdf' width='100%' height='760' />
                        <iframe src='{safe_url}' width='100%' height='760' style='border:none;'></iframe>
                    </object>
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.markdown(
                f"<div class='preview-caption'>Open directly: <a href='{safe_url}' target='_blank'>new tab</a></div>",
                unsafe_allow_html=True,
            )
        else:
            st.warning("Preview server unavailable. Use download to open the file.")
    else:
        text = payload.decode("utf-8", errors="replace")
        st.code(text, language="markdown")

    st.download_button(
        "Download selected artifact",
        data=payload,
        file_name=selected_artifact_path.name,
        mime="application/pdf"
        if selected_artifact_path.suffix.lower() == ".pdf"
        else "text/markdown",
        use_container_width=True,
        key=f"download_{selected_folder}_{selected_artifact_path.name}",
    )

    st.markdown("</div>", unsafe_allow_html=True)


def _render_logs_panel(controller: ResumeRunController) -> None:
    status = controller.status
    agent = status.active_agent if status.active_agent not in {"", "-"} else "Idle"
    signal = _signal_markup(status.state)

    st.markdown(
        (
            "<div class='fig-card-header'>"
            "<div class='fig-card-title'>Logs</div>"
            f"<div class='fig-right-meta'>Current Agent - {html.escape(agent)}"
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
        st.iframe(f"{log_url}?t={int(time.time() * 1000)}", height=490)
    else:
        st.warning("Could not render logs panel. Local preview server unavailable.")

    st.markdown("</div>", unsafe_allow_html=True)


def _render_controls_panel(controller: ResumeRunController) -> None:
    st.markdown(
        "<div class='fig-card-header'><div class='fig-card-title'>Run Controls</div></div>",
        unsafe_allow_html=True,
    )

    if "run_name_input" not in st.session_state:
        st.session_state.run_name_input = (
            f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        )

    top_left, top_right = st.columns([1.7, 1])
    with top_left:
        st.markdown(
            "<div class='controls-note'>Configure inputs and model for a new run.</div>",
            unsafe_allow_html=True,
        )
    with top_right:
        st.text_input(
            "Run Name Input Field", key="run_name_input", label_visibility="visible"
        )

    preset_names = list(MODEL_PRESETS.keys())

    with st.form("pipeline_controls_form"):
        left, right = st.columns([1.55, 1])
        with left:
            jd_path = st.text_input(
                "Job Description File Path", value="input/job_description.txt"
            )
            data_path = st.text_input("Master Profile Path", value="input/truth.json")
            preset = st.selectbox("Model Selection", options=preset_names, index=0)
        with right:
            max_iterations = st.slider(
                "No of Iterations", min_value=1, max_value=20, value=10
            )
            st.markdown(
                f"<div class='mono-note'>Status: {_status_badge(controller.status.state)}</div>",
                unsafe_allow_html=True,
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
        final_key_env = custom_key_env.strip() if preset == "Custom" else preset_key_env

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

        btn_left, btn_right = st.columns(2)
        start_run = btn_left.form_submit_button(
            "Run Pipeline",
            disabled=controller.is_running(),
            use_container_width=True,
        )
        stop_run = btn_right.form_submit_button(
            "Stop Active Run",
            disabled=not controller.is_running(),
            use_container_width=True,
        )

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
            controller.start_run(
                jd_path=jd_path.strip(),
                data_path=data_path.strip(),
                max_iterations=max_iterations,
                job_label=st.session_state.run_name_input.strip() or "run_manual",
                model=final_model,
                api_key_env=final_key_env,
                omissions=omissions,
            )
            st.rerun()
        except Exception as exc:
            st.error(f"Could not start run: {exc}")

    st.markdown("</div>", unsafe_allow_html=True)


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

    left_col, right_col = st.columns([1.03, 1.47], gap="medium")

    with left_col:
        _render_resume_panel(controller)

    with right_col:
        _render_logs_panel(controller)
        _render_controls_panel(controller)

    if controller.is_running():
        time.sleep(1)
        st.rerun()


if __name__ == "__main__":
    main()
