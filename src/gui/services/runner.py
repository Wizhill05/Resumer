from __future__ import annotations

import asyncio
import os
import queue
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")
STEP_RE = re.compile(r"\[Step\s+(\d+)\]\s*(.+)")
ITER_RE = re.compile(r"Draft iteration\s+(\d+)/(\d+)")
AGENT_RE = re.compile(r"Agent:\s*(.+)")
TASK_NAME_RE = re.compile(r"Name:\s*(.+)")
PANEL_BORDER_CHARS = "┌┐└┘├┤┬┴┼╭╮╯╰─═"
PANEL_TITLE_KEYWORDS = (
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


def _strip_ansi(text: str) -> str:
    return ANSI_ESCAPE_RE.sub("", text).replace("\r", "").rstrip("\n")


def _ensure_windows_subprocess_event_loop_support() -> None:
    """Ensure Windows asyncio policy supports subprocesses in GUI contexts."""
    if os.name == "nt":
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        except Exception:
            # Keep app resilient even if policy cannot be changed in current runtime.
            return


@dataclass
class LogEntry:
    ts: float
    stream: str
    text: str
    level: str


@dataclass
class PipelineStatus:
    state: str = "idle"
    model: str = "-"
    current_step: str = "-"
    active_agent: str = "-"
    active_task: str = "-"
    iteration: str = "-"
    output_dir: str = "-"
    final_pdf: str = "-"
    run_started_at: float | None = None
    run_finished_at: float | None = None
    exit_code: int | None = None


class ResumeRunController:
    """Runs the CLI pipeline as a subprocess and exposes live status/log data."""

    def __init__(self, workspace_root: Path, max_log_lines: int = 5000):
        self.workspace_root = workspace_root
        self.max_log_lines = max_log_lines

        self._process: subprocess.Popen[str] | None = None
        self._log_queue: queue.Queue[tuple[str, str]] = queue.Queue()
        self._threads: list[threading.Thread] = []
        self._lock = threading.Lock()

        self.logs: list[LogEntry] = []
        self.status = PipelineStatus()
        self._suppress_prompt_block = False
        self._suppress_profile_block = False
        self._suppress_final_answer_block = False

    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def start_run(
        self,
        *,
        jd_path: str,
        data_path: str,
        max_iterations: int,
        job_label: str,
        model: str,
        api_key_env: str,
        omissions: dict[str, bool],
    ) -> None:
        if self.is_running():
            raise RuntimeError("A run is already in progress")

        _ensure_windows_subprocess_event_loop_support()

        self.logs = []
        self.status = PipelineStatus(
            state="starting",
            model=model,
            run_started_at=time.time(),
        )

        cmd = [
            "uv",
            "run",
            "python",
            "src/resumer/main.py",
            "--jd",
            jd_path,
            "--data",
            data_path,
            "--max-iterations",
            str(max_iterations),
            "--job-label",
            job_label,
            "--model",
            model,
            "--api-key-env",
            api_key_env,
        ]

        flag_map = {
            "no_objective": "--no-objective",
            "no_education": "--no-education",
            "no_skills": "--no-skills",
            "no_projects": "--no-projects",
            "no_experience": "--no-experience",
            "no_activities": "--no-activities",
            "no_applying_for": "--no-applying-for",
            "no_photo": "--no-photo",
        }
        for key, flag in flag_map.items():
            if omissions.get(key, False):
                cmd.append(flag)

        env = os.environ.copy()
        env["RESUMER_MODEL"] = model
        env["RESUMER_API_KEY_ENV"] = api_key_env

        creationflags = 0
        if os.name == "nt":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

        self._process = subprocess.Popen(
            cmd,
            cwd=str(self.workspace_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=env,
            creationflags=creationflags,
        )

        self.status.state = "running"
        self._start_reader_threads()

    def stop_run(self) -> None:
        if not self.is_running() or self._process is None:
            return

        self.status.state = "stopping"

        try:
            self._process.terminate()
            self._process.wait(timeout=8)
        except Exception:
            self._process.kill()

    def poll(self) -> None:
        while True:
            try:
                stream, line = self._log_queue.get_nowait()
            except queue.Empty:
                break
            self._consume_line(stream, line)

        if self._process is not None and self._process.poll() is not None:
            if self.status.state not in {"completed", "failed", "stopped"}:
                code = self._process.returncode
                self.status.exit_code = code
                self.status.run_finished_at = time.time()
                if self.status.state == "stopping":
                    self.status.state = "stopped"
                elif code == 0:
                    self.status.state = "completed"
                else:
                    self.status.state = "failed"

    def latest_artifacts(self, limit: int = 50) -> list[Path]:
        outputs_root = self.workspace_root / "outputs"
        if not outputs_root.exists():
            return []

        candidates: list[Path] = []
        for ext in ("*.pdf", "*.md"):
            candidates.extend(p for p in outputs_root.rglob(ext) if p.is_file())

        candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return candidates[:limit]

    def _start_reader_threads(self) -> None:
        if self._process is None:
            return

        self._threads = []
        for stream_name, pipe in (
            ("stdout", self._process.stdout),
            ("stderr", self._process.stderr),
        ):
            if pipe is None:
                continue
            t = threading.Thread(
                target=self._reader_loop,
                args=(stream_name, pipe),
                daemon=True,
            )
            t.start()
            self._threads.append(t)

    def _reader_loop(self, stream_name: str, pipe: Any) -> None:
        try:
            for raw in iter(pipe.readline, ""):
                self._log_queue.put((stream_name, raw))
        finally:
            try:
                pipe.close()
            except Exception:
                pass

    def _consume_line(self, stream: str, raw_line: str) -> None:
        clean_line = self._normalize_log_line(_strip_ansi(raw_line))
        if not clean_line:
            return

        synthetic = self._maybe_emit_synthetic_event(clean_line, stream)
        if synthetic is None:
            return
        if synthetic:
            clean_line = synthetic

        level = self._classify_level(clean_line)
        entry = LogEntry(ts=time.time(), stream=stream, text=clean_line, level=level)
        self.logs.append(entry)
        if len(self.logs) > self.max_log_lines:
            self.logs = self.logs[-self.max_log_lines :]

        self._update_status_from_line(clean_line)

    def _normalize_log_line(self, line: str) -> str:
        text = line.strip()
        if not text:
            return ""

        # Convert panel title bars into clean titles and drop pure borders.
        if any(ch in text for ch in PANEL_BORDER_CHARS):
            cleaned = re.sub(r"[┌┐└┘├┤┬┴┼╭╮╯╰─═│]+", " ", text)
            cleaned = re.sub(r"\s+", " ", cleaned).strip()
            if cleaned:
                lower_cleaned = cleaned.lower()
                if any(keyword in lower_cleaned for keyword in PANEL_TITLE_KEYWORDS):
                    text = cleaned
                elif text[0] in {"┌", "└", "╭", "╰", "─", "═"}:
                    return ""
                else:
                    text = cleaned
            else:
                return ""

        if text.startswith("│"):
            text = text.strip("│").strip()

        # Also strip ascii pipe wrappers like "| message |".
        if text.startswith("|") and text.endswith("|"):
            text = text.strip("|").strip()

        if not text:
            return ""

        return text

    def _maybe_emit_synthetic_event(self, line: str, stream: str) -> str | None:
        lower = line.lower()

        # Suppress long task prompt dumps.
        if self._suppress_prompt_block:
            if (
                "task started" in lower
                or "final answer" in lower
                or "task completed" in lower
                or "task failed" in lower
                or "crew execution" in lower
            ):
                self._suppress_prompt_block = False
            else:
                return None

        # Suppress large injected profile JSON dumps.
        if self._suppress_profile_block:
            if "target job description:" in lower:
                self._suppress_profile_block = False
                return "Job description injected"
            return None

        # Suppress verbose final structured JSON answer block.
        if self._suppress_final_answer_block:
            if "task completed" in lower or "task failed" in lower:
                self._suppress_final_answer_block = False
            else:
                return None

        if "task: given the candidate's master profile" in lower:
            self._suppress_prompt_block = True
            return "System prompt given"

        if "step 1 — draft the resume content" in lower:
            self._suppress_prompt_block = True
            return "System prompt given"

        if "candidate profile:" in lower:
            self._suppress_profile_block = True
            return "Candidate profile injected"

        if "final answer:" in lower:
            self._suppress_final_answer_block = True
            return "Agent returned structured response"

        # Drop noisy JSON-like lines that clutter console view.
        json_noise_markers = (
            '"personal_information"',
            '"education"',
            '"skills"',
            '"projects"',
            '"experience"',
            '"activities"',
            '"photo"',
            '"coursework"',
            '"numerical data"',
            "{",
            "}",
            "[",
            "]",
        )
        if lower in {"{", "}", "[", "]", "},", "],"}:
            return None
        if any(marker in lower for marker in json_noise_markers):
            return None

        # Make shortener phase explicit in logs.
        if "draft iteration" in lower and "/" in line and not line.startswith("Draft"):
            return f"{line}"
        if "shorten_resume" in lower:
            return "Shortening"

        return line

    def _classify_level(self, line: str) -> str:
        lower = line.lower()
        if "traceback" in lower or "error" in lower or "✗" in line:
            return "error"
        if "warning" in lower or "⚠" in line:
            return "warn"
        if "✅" in line or "approved" in lower:
            return "success"
        if "[step" in lower or "agent" in lower or "task" in lower:
            return "event"
        return "info"

    def _update_status_from_line(self, line: str) -> None:
        step_match = STEP_RE.search(line)
        if step_match:
            step_num, step_name = step_match.groups()
            self.status.current_step = f"Step {step_num}: {step_name.strip()}"

        iter_match = ITER_RE.search(line)
        if iter_match:
            current, total = iter_match.groups()
            self.status.iteration = f"{current}/{total}"

        if "Agent:" in line:
            agent_match = AGENT_RE.search(line)
            if agent_match:
                self.status.active_agent = agent_match.group(1).strip()

        if "Task Started" in line or "Task Completed" in line or "Task Failed" in line:
            self.status.active_task = line.strip()

        if "Name:" in line:
            task_match = TASK_NAME_RE.search(line)
            if task_match and "write_resume" in task_match.group(1):
                self.status.active_task = "write_resume"
            elif task_match and "shorten_resume" in task_match.group(1):
                self.status.active_task = "shorten_resume"

        if "Output folder:" in line:
            self.status.output_dir = line.split("Output folder:", 1)[1].strip()

        if "Final resume" in line and "→" in line:
            self.status.final_pdf = line.split("→", 1)[1].strip()

        if line.strip().startswith("Model:"):
            self.status.model = line.split("Model:", 1)[1].strip()
