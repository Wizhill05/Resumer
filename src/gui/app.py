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
            --line: #2e3138;
            --line-soft: #1e2127;
            --text: #f2f3f5;
            --muted: #a3a8b3;
            --green: #24cc5a;
            --yellow: #f6bd3f;
            --red: #e35a67;
        }

        /* ─── Global ─── */
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

        /* ─── st.container(border=True) card styling ─── */
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

        /* ─── Card Headers (raw HTML) ─── */
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

        .meta-sub {
            font-size: 0.78rem;
            color: var(--muted);
        }

        /* ─── Signal Bars ─── */
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

        /* ─── Resume Preview ─── */
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

        /* ─── Controls ─── */
        .controls-note {
            color: var(--muted);
            font-size: 0.82rem;
            margin-bottom: 0.3rem;
        }

        .mono-note {
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.78rem;
            color: var(--muted);
        }

        /* ─── Streamlit widget overrides ─── */
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

        .stSlider [data-baseweb="slider"] {
            background: transparent !important;
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

        /* For the iframe in the logs panel — remove Streamlit's padding */
        iframe {
            border-radius: 8px !important;
        }

        /* ─── Expander styling ─── */
        details summary {
            font-family: 'Manrope', sans-serif !important;
            font-weight: 600 !important;
            color: var(--muted) !important;
        }

        /* Remove extra top-margin from the form inside controls card */
        [data-testid="stForm"] {
            border: none !important;
            padding: 0 !important;
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


# ────────────────────────────────────────────────
# Panel renderers
# ────────────────────────────────────────────────


def _render_resume_panel(controller: ResumeRunController) -> None:
    """Left column: Resumer title + resume name selector + PDF preview."""

    folders = _list_output_folders()

    with st.container(border=True):
        if not folders:
            st.markdown(
                "<div class='card-header'>"
                "<div class='card-title'>Resumer</div>"
                "<div class='card-header-right'><span class='meta-label'>Resume Name</span></div>"
                "</div>",
                unsafe_allow_html=True,
            )
            st.info("No artifacts yet. Launch a run to generate resume previews.")
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


        # Title
        st.markdown("<div class='card-title'>Resumer</div>", unsafe_allow_html=True)

        # Run folder and artifact file selectors side by side
        sel_left, sel_right = st.columns(2)
        with sel_left:
            selected_folder = st.selectbox(
                "Run Folder",
                options=folder_labels,
                index=folder_index,
                key="resume_folder_selector",
            )

        # Resolve artifacts from the *selected* folder before rendering file picker
        selected_folder_path = OUTPUTS_ROOT / selected_folder
        artifacts = _list_folder_artifacts(selected_folder_path)
        if not artifacts:
            with sel_right:
                st.warning("No files in this folder.")
            return

        artifact_names = [item.name for item in artifacts]
        default_artifact = _default_artifact_name(artifacts)
        default_index = artifact_names.index(default_artifact)

        with sel_right:
            selected_artifact_name = st.selectbox(
                "Resume File",
                options=artifact_names,
                index=default_index,
                # Key tied to selected folder so Streamlit refreshes the widget
                # with fresh options whenever the folder changes.
                key=f"resume_artifact_{selected_folder}",
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
                st.warning("Preview server unavailable. Use download to open the file.")
        else:
            text = payload.decode("utf-8", errors="replace")
            st.code(text, language="markdown")

        st.download_button(
            "⬇  Download",
            data=payload,
            file_name=selected_artifact_path.name,
            mime="application/pdf"
            if selected_artifact_path.suffix.lower() == ".pdf"
            else "text/markdown",
            use_container_width=True,
            key=f"download_{selected_folder}_{selected_artifact_path.name}",
        )


def _render_logs_panel(controller: ResumeRunController) -> None:
    """Top-right: Logs panel with terminal-style log viewer."""
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


def _render_controls_panel(controller: ResumeRunController) -> None:
    """Bottom-right: Run Controls panel."""

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

        # ── Job source toggle (Outside form for instant reactivity) ──
        jd_mode = st.radio(
            "Job Source",
            options=["📝 Text Mode", "🔗 URL Mode"],
            horizontal=True,
            key="jd_mode_radio",
        )

        with st.form("pipeline_controls_form"):
            left, right = st.columns([1.55, 1])

            with left:
                # All text / select inputs stacked cleanly
                st.text_input(
                    "Run Name",
                    key="run_name_input",
                )

                if jd_mode == "🔗 URL Mode":
                    job_url = st.text_input(
                        "Job Posting URL",
                        placeholder="https://www.linkedin.com/jobs/view/... or any job board URL",
                        key="job_url_input",
                    )
                    jd_text = ""
                else:
                    jd_text = st.text_area(
                        "Job Description",
                        placeholder="Paste the full job description here...",
                        height=200,
                        key="jd_text_input",
                    )
                    job_url = ""

                data_path = st.text_input(
                    "Master Profile Path", value="input/truth.json"
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
                # Buttons in the right column, stacked
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
                # In URL mode, let main.py derive the job label from the researcher output
                # unless the user has typed a custom run name.
                run_name = st.session_state.run_name_input.strip()
                # If in URL mode and run name still looks like the auto-generated default,
                # pass empty string so main.py can auto-fill from the researcher's output.
                is_default_name = run_name.startswith("run_")
                effective_label = "" if (job_url.strip() and is_default_name) else run_name or "run_manual"

                controller.start_run(
                    jd_text=jd_text.strip(),
                    data_path=data_path.strip(),
                    max_iterations=max_iterations,
                    job_label=effective_label,
                    model=final_model,
                    api_key_env=final_key_env,
                    omissions=omissions,
                    url=job_url.strip(),
                )
                st.rerun()
            except Exception as exc:
                st.error(f"Could not start run: {exc}")


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

    left_col, right_col = st.columns([1.5, 1.5], gap="medium")

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
