"""
RunManager — manages ResumeRunController instances and broadcasts log events
over WebSocket connections.

Replaces the Streamlit session_state controller management.
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from gui.services.local_backend import LocalBackend

from gui.services.runner import ResumeRunController, LogEntry

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
BATCH_MAX_PARALLEL = 6


class RunManager:
    """
    Manages:
    - A single 'main' controller (for single manual runs from the Studio tab)
    - A dict of batch controllers keyed by run_id (for parallel batch execution)
    - WebSocket broadcast lists per controller key
    - Background polling thread to sync finished runs to the DB
    """

    def __init__(self, backend: "LocalBackend") -> None:
        self.backend = backend

        # Main single-run controller
        self._main_controller = ResumeRunController(WORKSPACE_ROOT)

        # Batch controllers: run_id -> controller
        self._batch_controllers: dict[str, ResumeRunController] = {}
        # Batch run meta: run_id -> {batch_id, item_id, project_id, model}
        self._batch_run_meta: dict[str, dict[str, str]] = {}

        # WebSocket subscribers: controller_key -> list of asyncio.Queue
        # controller_key is "main" or a run_id
        self._ws_queues: dict[str, list[asyncio.Queue]] = {}
        self._ws_lock = threading.Lock()

        # Synced run state tracking (same as Streamlit's synced_run_states)
        self._synced_states: dict[str, str] = {}

        # Start background polling thread
        self._polling = True
        self._poll_thread = threading.Thread(
            target=self._poll_loop, daemon=True
        )
        self._poll_thread.start()

        # Background batch-tick thread — auto-launches queued items for running batches
        self._batch_tick_thread = threading.Thread(
            target=self._batch_tick_loop, daemon=True
        )
        self._batch_tick_thread.start()

    # ── Main controller ────────────────────────────────────────────────────────

    @property
    def main_controller(self) -> ResumeRunController:
        return self._main_controller

    def start_main_run(
        self,
        *,
        jd_path: str,
        data_path: str,
        max_iterations: int,
        job_label: str,
        model: str,
        api_key_env: str,
        omissions: dict[str, bool],
        project_id: str = "",
        project_name: str = "",
    ) -> None:
        self._main_controller.start_run(
            jd_path=jd_path,
            data_path=data_path,
            max_iterations=max_iterations,
            job_label=job_label,
            model=model,
            api_key_env=api_key_env,
            omissions=omissions,
            project_id=project_id,
            project_name=project_name,
        )

    def stop_main_run(self) -> None:
        self._main_controller.stop_run()

    def get_main_status(self) -> dict[str, Any]:
        return _status_to_dict(self._main_controller.status)

    def get_main_logs(self) -> list[dict[str, Any]]:
        return [_log_to_dict(e) for e in self._main_controller.logs[-1200:]]

    # ── Batch controllers ──────────────────────────────────────────────────────

    def get_batch_controllers(self) -> dict[str, ResumeRunController]:
        return self._batch_controllers

    def get_batch_run_meta(self) -> dict[str, dict[str, str]]:
        return self._batch_run_meta

    def start_batch_item(
        self,
        *,
        batch: dict[str, Any],
        item: dict[str, Any],
        uid: str,
        model_slot: int = 0,
    ) -> dict[str, str]:
        """Launch a new controller for one batch item. Returns run_meta."""
        from api.run_manager import _model_pool_from_settings, _safe_run_name

        settings = dict(batch.get("global_settings", {}) or {})
        overrides = dict(item.get("settings_override", {}) or {})
        omissions: dict[str, bool] = {**dict(settings.get("omissions", {}) or {})}
        omissions.update(overrides.get("omissions", {}) or {})

        if overrides.get("max_iterations"):
            settings["max_iterations"] = int(overrides["max_iterations"])
        if overrides.get("model"):
            settings["model"] = str(overrides["model"])
        if overrides.get("api_key_env"):
            settings["api_key_env"] = str(overrides["api_key_env"])

        if not overrides.get("model"):
            pool = _model_pool_from_settings(settings)
            if pool:
                selected = pool[model_slot % len(pool)]
                settings["model"] = selected["model"]
                settings["api_key_env"] = selected["api_key_env"]

        job_id = str(item["job_id"])
        run_name = str(overrides.get("run_name") or "").strip()
        if not run_name:
            run_name = _safe_run_name(
                str(settings.get("name_pattern", "{company}_{title}")), item
            )

        # Build JD text
        job_text = _job_description_for_pipeline(item)
        if not job_text:
            raise ValueError("Job has no usable description text.")

        pid = self.backend.get_profile_id()
        work_dir = WORKSPACE_ROOT / ".resumer_gui" / pid / "mass_apply" / str(batch["id"])
        work_dir.mkdir(parents=True, exist_ok=True)
        jd_path = work_dir / f"{str(item['id'])}.job.txt"
        jd_path.write_text(job_text, encoding="utf-8")

        profile_path = _profile_temp_path(pid)
        profile_path.write_text(
            json.dumps(self.backend.get_truth_json(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        project_id = self.backend.create_project(
            job_id=job_id,
            name=run_name,
            job_description=job_text,
        )
        self.backend.update_batch_item_status(
            item_id=str(item["id"]), status="running", project_id=project_id
        )
        self.backend.update_batch_status(
            batch_id=str(batch["id"]), status="running"
        )

        run_id = f"{batch['id']}:{item['id']}"
        controller = ResumeRunController(WORKSPACE_ROOT)
        controller.start_run(
            jd_path=str(jd_path),
            data_path=str(profile_path),
            max_iterations=int(settings.get("max_iterations", 10)),
            job_label=f"{run_name}_{project_id[:8]}",
            model=str(settings.get("model", "")),
            api_key_env=str(settings.get("api_key_env", "")),
            omissions=omissions,
            project_id=project_id,
            project_name=run_name,
        )
        self._batch_controllers[run_id] = controller
        run_meta = {
            "batch_id": str(batch["id"]),
            "item_id": str(item["id"]),
            "job_id": str(item.get("job_id", "")),
            "project_id": project_id,
            "model": str(settings.get("model", "")),
        }
        self._batch_run_meta[run_id] = run_meta
        return run_meta

    def stop_batch_runs(self, batch_id: str, *, return_to_pool: bool = True) -> None:
        """Stop all active controllers for a batch. Optionally return non-completed items to pool."""
        for run_id, controller in list(self._batch_controllers.items()):
            meta = self._batch_run_meta.get(run_id, {})
            if meta.get("batch_id") == batch_id and controller.is_running():
                controller.stop_run()
        if return_to_pool:
            try:
                self.backend.return_batch_to_pool(batch_id=batch_id)
            except Exception:
                pass
        try:
            self.backend.update_batch_status(batch_id=batch_id, status="cancelled")
        except Exception:
            pass

    def get_batch_status(self, batch_id: str) -> list[dict[str, Any]]:
        result = []
        for run_id, controller in self._batch_controllers.items():
            meta = self._batch_run_meta.get(run_id, {})
            if meta.get("batch_id") == batch_id:
                result.append({
                    "run_id": run_id,
                    "meta": meta,
                    "status": _status_to_dict(controller.status),
                    "is_running": controller.is_running(),
                })
        return result

    def get_batch_logs(self, batch_id: str) -> list[dict[str, Any]]:
        logs = []
        for run_id, controller in self._batch_controllers.items():
            meta = self._batch_run_meta.get(run_id, {})
            if meta.get("batch_id") == batch_id:
                for entry in controller.logs[-300:]:
                    d = _log_to_dict(entry)
                    d["run_id"] = run_id
                    d["item_id"] = meta.get("item_id", "")
                    logs.append(d)
        logs.sort(key=lambda x: x["ts"])
        return logs[-1200:]

    # ── WebSocket subscription ─────────────────────────────────────────────────

    def subscribe(self, key: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=2000)
        with self._ws_lock:
            self._ws_queues.setdefault(key, []).append(q)
        return q

    def unsubscribe(self, key: str, q: asyncio.Queue) -> None:
        with self._ws_lock:
            lst = self._ws_queues.get(key, [])
            if q in lst:
                lst.remove(q)

    def _broadcast(self, key: str, payload: dict) -> None:
        with self._ws_lock:
            queues = list(self._ws_queues.get(key, []))
        for q in queues:
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                pass

    # ── Background polling ─────────────────────────────────────────────────────

    def _poll_loop(self) -> None:
        while self._polling:
            try:
                self._main_controller.poll()
                self._push_main_logs()
                self._sync_main_run()

                for run_id, controller in list(self._batch_controllers.items()):
                    controller.poll()
                    self._push_batch_logs(run_id, controller)
                    self._sync_batch_run(run_id, controller)
            except Exception:
                pass
            time.sleep(0.5)

    def _batch_tick_loop(self) -> None:
        """Every 2s: for each 'running' batch, fill available parallel slots."""
        while self._polling:
            try:
                batches = self.backend.list_batches()
                for batch in batches:
                    if batch.get("status") != "running":
                        continue
                    batch_id = str(batch["id"])
                    # Count active controllers for this batch
                    active = sum(
                        1 for run_id, c in self._batch_controllers.items()
                        if self._batch_run_meta.get(run_id, {}).get("batch_id") == batch_id
                        and c.is_running()
                    )
                    prefs = batch.get("global_settings") or batch.get("preferences") or {}
                    max_parallel = int(prefs.get("parallel_runs", 1))
                    slots = max(0, max_parallel - active)
                    launched = 0
                    for _ in range(slots):
                        item = self.backend.next_batch_item(batch_id=batch_id)
                        if not item:
                            break
                        try:
                            self.start_batch_item(batch=batch, item=item, uid="")
                            launched += 1
                        except Exception as exc:
                            self.backend.update_batch_item_status(
                                item_id=str(item["id"]), status="failed",
                                error_message=f"Launch error: {exc}",
                            )
                    # If no more queued items and no active controllers → mark done/failed
                    if not self.backend.next_batch_item(batch_id=batch_id) and active == 0:
                        items = self.backend.list_batch_items(batch_id=batch_id)
                        all_done = all(i["status"] in ("completed", "failed") for i in items)
                        if all_done:
                            any_completed = any(i["status"] == "completed" for i in items)
                            self.backend.update_batch_status(
                                batch_id=batch_id,
                                status="completed" if any_completed else "failed",
                            )
            except Exception:
                pass
            time.sleep(2.0)

    def _push_main_logs(self) -> None:
        controller = self._main_controller
        sent_key = "_main_sent"
        sent = getattr(controller, sent_key, 0)
        new_entries = controller.logs[sent:]
        if not new_entries:
            return
        for entry in new_entries:
            self._broadcast("main", _log_to_dict(entry))
        setattr(controller, sent_key, len(controller.logs))

    def _push_batch_logs(self, run_id: str, controller: ResumeRunController) -> None:
        sent_key = f"_sent_{run_id}"
        sent = getattr(controller, sent_key, 0)
        new_entries = controller.logs[sent:]
        if not new_entries:
            return
        batch_id = self._batch_run_meta.get(run_id, {}).get("batch_id", "")
        for entry in new_entries:
            payload = _log_to_dict(entry)
            payload["run_id"] = run_id
            if batch_id:
                self._broadcast(f"batch:{batch_id}", payload)
        setattr(controller, sent_key, len(controller.logs))

    def _sync_main_run(self) -> None:
        controller = self._main_controller
        status = controller.status
        project_id = status.project_id.strip()
        if not project_id or project_id == "-":
            return
        if status.state not in {"completed", "failed", "stopped"}:
            return

        sync_key = f"{status.state}|{status.output_dir}|{status.exit_code}"
        if self._synced_states.get(project_id) == sync_key:
            return

        # Find owner uid by project lookup
        uid = self._find_uid_for_project(project_id)
        if not uid:
            return

        self._do_sync(controller, uid, project_id, status, batch_run=None)
        self._synced_states[project_id] = sync_key

    def _sync_batch_run(self, run_id: str, controller: ResumeRunController) -> None:
        status = controller.status
        project_id = status.project_id.strip()
        if not project_id or project_id == "-":
            return
        if status.state not in {"completed", "failed", "stopped"}:
            return

        sync_key = f"{status.state}|{status.output_dir}|{status.exit_code}"
        if self._synced_states.get(project_id) == sync_key:
            return

        uid = self._find_uid_for_project(project_id)
        if not uid:
            return

        batch_run = self._batch_run_meta.get(run_id)
        self._do_sync(controller, uid, project_id, status, batch_run=batch_run)
        self._synced_states[project_id] = sync_key

        if not controller.is_running():
            self._batch_controllers.pop(run_id, None)
            self._batch_run_meta.pop(run_id, None)

    def _do_sync(
        self,
        controller: ResumeRunController,
        uid: str,
        project_id: str,
        status: Any,
        batch_run: dict | None,
    ) -> None:
        import shutil

        output_dir_text = status.output_dir.strip()
        output_dir = None
        if output_dir_text and output_dir_text != "-":
            output_dir = Path(output_dir_text)

        try:
            if output_dir and output_dir.exists():
                self.backend.replace_project_artifacts_from_local(
                    project_id=project_id, output_dir=output_dir
                )
                shutil.rmtree(output_dir, ignore_errors=True)

            if status.state == "completed":
                self.backend.update_project_status(
                    project_id=project_id, status="completed"
                )
                self.backend.update_job_generation_status_for_project(
                    project_id=project_id, status="completed"
                )
            else:
                self.backend.update_project_status(
                    project_id=project_id,
                    status="failed",
                    error_message=f"Run ended '{status.state}' (exit: {status.exit_code})",
                )
                self.backend.update_job_generation_status_for_project(
                    project_id=project_id, status="failed"
                )

            if batch_run:
                item_status = "completed" if status.state == "completed" else "failed"
                item_id = str(batch_run.get("item_id", ""))
                self.backend.update_batch_item_status(
                    item_id=item_id,
                    status=item_status,
                    project_id=project_id,
                    error_message=""
                    if item_status == "completed"
                    else f"Run ended '{status.state}' (exit: {status.exit_code})",
                )
                # Record completed resume entry for tracker/applications view
                if item_status == "completed":
                    try:
                        artifacts = self.backend.list_artifacts(project_id=project_id)
                        resume_path = ""
                        for art in artifacts:
                            if art.get("artifact_type") in ("final_pdf", "draft_pdf"):
                                resume_path = str(art.get("storage_path", ""))
                                break
                        job = self.backend.get_job(job_id=str(batch_run.get("job_id", project_id)))
                        job_id = str(batch_run.get("job_id", "")) or (job or {}).get("id", "")
                        apply_url = (job or {}).get("apply_url", "") or ""
                        title = (job or {}).get("title", "") or ""
                        company = (job or {}).get("company", "") or ""
                        if job_id:
                            self.backend.record_completed_resume(
                                batch_item_id=item_id, job_id=job_id,
                                project_id=project_id, title=title, company=company,
                                apply_url=apply_url, resume_path=resume_path,
                            )
                    except Exception:
                        pass
        except Exception:
            pass

    def _find_uid_for_project(self, project_id: str) -> str:
        """Return the default profile ID (single-profile mode)."""
        return self.backend.get_profile_id()


# ── Helpers (package-level, re-used in routers) ────────────────────────────────

def _status_to_dict(status: Any) -> dict[str, Any]:
    return {
        "state": status.state,
        "model": status.model,
        "current_step": status.current_step,
        "active_agent": status.active_agent,
        "active_task": status.active_task,
        "iteration": status.iteration,
        "output_dir": status.output_dir,
        "final_pdf": status.final_pdf,
        "project_id": status.project_id,
        "project_name": status.project_name,
        "run_started_at": status.run_started_at,
        "run_finished_at": status.run_finished_at,
        "exit_code": status.exit_code,
    }


def _log_to_dict(entry: LogEntry) -> dict[str, Any]:
    return {
        "ts": entry.ts,
        "stream": entry.stream,
        "text": entry.text,
        "level": entry.level,
    }


def _profile_temp_path(uid: str) -> Path:
    target_dir = WORKSPACE_ROOT / ".resumer_gui" / uid
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir / "truth.runtime.json"


def _job_description_for_pipeline(job: dict) -> str:
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
    return "\n".join(str(p).strip() for p in parts).strip()


def _safe_run_name(pattern: str, job: dict) -> str:
    import re
    values = {
        "company": str(job.get("company", "") or "company"),
        "title": str(job.get("title", "") or "job"),
        "job_id": str(job.get("job_id", job.get("id", "")))[:8],
    }
    try:
        raw = pattern.format(**values)
    except Exception:
        raw = f"{values['company']}_{values['title']}"
    raw = re.sub(r"[^a-zA-Z0-9_\-]", "_", raw.strip()) or "batch_job"
    return raw[:120]


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
}


def _model_pool_from_settings(settings: dict) -> list[dict[str, str]]:
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
                pool.append({"label": label, "model": model, "api_key_env": api_key_env})
    if not pool:
        model = str(settings.get("model", "") or "").strip()
        api_key_env = str(settings.get("api_key_env", "") or "").strip()
        if model and api_key_env:
            pool.append({"label": model, "model": model, "api_key_env": api_key_env})
    return pool
