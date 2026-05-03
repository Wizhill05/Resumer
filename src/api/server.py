"""
server.py — FastAPI backend for Resumer.

Startup:
    uv run uvicorn src.api.server:app --reload --host 0.0.0.0 --port 8000

All API routes are prefixed with /api.
"""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ── Path bootstrap ────────────────────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()
load_dotenv(_PROJECT_ROOT / ".env.local", override=True)

from src.gui.services.local_backend import LocalBackend  # noqa: E402
from src.gui.services.runner import ResumeRunController  # noqa: E402
from src.api.scrape_service import ScrapeService  # noqa: E402

# ── Singletons ────────────────────────────────────────────────────────────────
_backend = LocalBackend()

# One controller per active run — keyed by project_id.
_controllers: dict[str, ResumeRunController] = {}
_controllers_lock = threading.Lock()

# Single scrape service instance
_scrape_service = ScrapeService(backend=_backend)

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="Resumer API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Pydantic models ───────────────────────────────────────────────────────────


class CreateUserRequest(BaseModel):
    display_name: str


class SaveTruthRequest(BaseModel):
    truth_json: dict[str, Any]


class GenerateRequest(BaseModel):
    job_description: str
    job_label: str = ""
    model: str = "mistral/mistral-large-latest"
    api_key_env: str = "MISTRAL_API_KEY"
    max_iterations: int = 10
    omissions: dict[str, bool] = {}
    mandatory_words: list[str] = []


# ── Helpers ───────────────────────────────────────────────────────────────────


def _get_controller(project_id: str) -> ResumeRunController | None:
    with _controllers_lock:
        return _controllers.get(project_id)


def _set_controller(project_id: str, ctrl: ResumeRunController) -> None:
    with _controllers_lock:
        _controllers[project_id] = ctrl


def _remove_controller(project_id: str) -> None:
    with _controllers_lock:
        _controllers.pop(project_id, None)


def _sanitize_label(label: str) -> str:
    import re
    label = label.lower().strip()
    label = re.sub(r"[^a-z0-9]+", "_", label)
    return label.strip("_") or "untitled_run"


# ── User endpoints ────────────────────────────────────────────────────────────


@app.get("/api/users")
def list_users() -> list[dict[str, Any]]:
    return _backend.list_users()


@app.post("/api/users", status_code=201)
def create_user(body: CreateUserRequest) -> dict[str, Any]:
    if not body.display_name.strip():
        raise HTTPException(400, "display_name is required")
    user = _backend.create_user(body.display_name.strip())
    return {"uid": user.uid, "display_name": user.email}


# ── Profile / truth.json endpoints ───────────────────────────────────────────


@app.get("/api/users/{uid}/truth")
def get_truth(uid: str) -> dict[str, Any]:
    return _backend.get_truth_json(uid)


@app.put("/api/users/{uid}/truth")
def save_truth(uid: str, body: SaveTruthRequest) -> dict[str, str]:
    _backend.save_truth_json(uid, body.truth_json)
    return {"status": "ok"}


class SavePreferencesRequest(BaseModel):
    preferences: dict[str, Any]


@app.get("/api/users/{uid}/preferences")
def get_preferences(uid: str) -> dict[str, Any]:
    return _backend.get_preferences(uid)


@app.put("/api/users/{uid}/preferences")
def save_preferences(uid: str, body: SavePreferencesRequest) -> dict[str, str]:
    _backend.save_preferences(uid, body.preferences)
    return {"status": "ok"}


# ── Projects ──────────────────────────────────────────────────────────────────


@app.get("/api/users/{uid}/projects")
def list_projects(uid: str) -> list[dict[str, Any]]:
    projects = _backend.list_projects(uid)
    # Serialize datetime objects to ISO strings
    result: list[dict[str, Any]] = []
    for p in projects:
        serialized: dict[str, Any] = {}
        for k, v in p.items():
            if hasattr(v, "isoformat"):
                serialized[k] = v.isoformat()
            else:
                serialized[k] = v
        result.append(serialized)
    return result


@app.delete("/api/users/{uid}/projects/{project_id}", status_code=204)
def delete_project(uid: str, project_id: str) -> Response:
    _backend.delete_project(uid=uid, project_id=project_id)
    return Response(status_code=204)


# ── Artifacts ─────────────────────────────────────────────────────────────────


@app.get("/api/users/{uid}/projects/{project_id}/artifacts")
def list_artifacts(uid: str, project_id: str) -> list[dict[str, Any]]:
    artifacts = _backend.list_artifacts(uid=uid, project_id=project_id)
    result: list[dict[str, Any]] = []
    for a in artifacts:
        serialized: dict[str, Any] = {}
        for k, v in a.items():
            if hasattr(v, "isoformat"):
                serialized[k] = v.isoformat()
            else:
                serialized[k] = v
        result.append(serialized)
    return result


@app.get("/api/artifacts/download")
def download_artifact(path: str) -> Response:
    """Serve a stored artifact file (PDF or MD) by its absolute storage_path."""
    artifact_path = Path(path)
    if not artifact_path.exists() or not artifact_path.is_file():
        raise HTTPException(404, f"Artifact not found: {path}")

    suffix = artifact_path.suffix.lower()
    mime = "application/pdf" if suffix == ".pdf" else "text/markdown"
    content_disposition = f'inline; filename="{artifact_path.name}"'

    data = artifact_path.read_bytes()
    return Response(
        content=data,
        media_type=mime,
        headers={"Content-Disposition": content_disposition},
    )


# ── Generation ────────────────────────────────────────────────────────────────


@app.post("/api/users/{uid}/generate", status_code=202)
def start_generate(uid: str, body: GenerateRequest, background_tasks: BackgroundTasks) -> dict[str, str]:
    """
    Kick off a resume generation run for the given user.
    Returns the project_id immediately; poll /api/users/{uid}/projects/{project_id}/status
    to track progress.
    """
    # Fetch the user's truth profile from the DB
    truth_data = _backend.get_truth_json(uid)

    # Resolve the job label
    job_label = body.job_label.strip() or body.job_description[:60].strip()
    sanitized_label = _sanitize_label(job_label)

    # Create a DB project entry (status: running)
    project_id = _backend.create_project(
        uid=uid,
        name=job_label or sanitized_label,
        job_description=body.job_description,
    )

    # Write inputs to temp files that the CLI needs
    run_dir = _PROJECT_ROOT / "outputs" / sanitized_label
    run_dir.mkdir(parents=True, exist_ok=True)

    jd_path = run_dir / "job_description.txt"
    jd_path.write_text(body.job_description, encoding="utf-8")

    data_path = run_dir / "truth.runtime.json"
    data_path.write_text(json.dumps(truth_data, ensure_ascii=False, indent=2), encoding="utf-8")

    # Build and start the controller
    controller = ResumeRunController(workspace_root=_PROJECT_ROOT)
    _set_controller(project_id, controller)

    controller.start_run(
        jd_path=str(jd_path.relative_to(_PROJECT_ROOT)),
        data_path=str(data_path.relative_to(_PROJECT_ROOT)),
        max_iterations=body.max_iterations,
        job_label=sanitized_label,
        model=body.model,
        api_key_env=body.api_key_env,
        omissions=body.omissions,
        mandatory_words=body.mandatory_words,
        project_id=project_id,
        project_name=job_label or sanitized_label,
    )

    # Background poller: polls controller until done, then syncs artifacts to DB
    background_tasks.add_task(
        _poll_until_done,
        uid=uid,
        project_id=project_id,
        controller=controller,
    )

    return {"project_id": project_id, "status": "started"}


@app.get("/api/users/{uid}/projects/{project_id}/status")
def get_run_status(uid: str, project_id: str) -> dict[str, Any]:
    """Return the live pipeline status for a running project."""
    ctrl = _get_controller(project_id)
    if ctrl is None:
        # Fetch terminal state from DB
        projects = _backend.list_projects(uid)
        for p in projects:
            if p["id"] == project_id:
                return {
                    "state": p.get("status", "unknown"),
                    "project_id": project_id,
                    "model": "-",
                    "current_step": "-",
                    "iteration": "-",
                    "output_dir": "-",
                }
        raise HTTPException(404, "Project not found")

    ctrl.poll()
    s = ctrl.status
    return {
        "state": s.state,
        "project_id": project_id,
        "model": s.model,
        "current_step": s.current_step,
        "active_agent": s.active_agent,
        "active_task": s.active_task,
        "iteration": s.iteration,
        "output_dir": s.output_dir,
        "final_pdf": s.final_pdf,
        "run_started_at": s.run_started_at,
        "run_finished_at": s.run_finished_at,
        "exit_code": s.exit_code,
    }


@app.get("/api/users/{uid}/projects/{project_id}/logs")
def get_run_logs(uid: str, project_id: str, limit: int = 500) -> list[dict[str, Any]]:
    """Return recent log entries for a running project."""
    ctrl = _get_controller(project_id)
    if ctrl is None:
        return []
    ctrl.poll()
    entries = ctrl.logs[-limit:]
    return [
        {"ts": e.ts, "stream": e.stream, "text": e.text, "level": e.level}
        for e in entries
    ]


@app.post("/api/users/{uid}/projects/{project_id}/stop", status_code=200)
def stop_run(uid: str, project_id: str) -> dict[str, str]:
    ctrl = _get_controller(project_id)
    if ctrl is None:
        raise HTTPException(404, "No active run found for this project")
    ctrl.stop_run()
    return {"status": "stopping"}


@app.get("/api/jobs")
def list_scraped_jobs() -> list[dict[str, Any]]:
    """Return all scraped jobs from the database."""
    jobs = _backend.list_scraped_jobs()
    result: list[dict[str, Any]] = []
    for j in jobs:
        serialized: dict[str, Any] = {}
        for k, v in j.items():
            if hasattr(v, "isoformat"):
                serialized[k] = v.isoformat()
            else:
                serialized[k] = v
        result.append(serialized)
    return result


@app.delete("/api/jobs", status_code=204)
def delete_all_scraped_jobs() -> Response:
    _backend.delete_all_scraped_jobs()
    return Response(status_code=204)


@app.delete("/api/jobs/{job_id}", status_code=204)
def delete_scraped_job(job_id: str) -> Response:
    _backend.delete_scraped_jobs([job_id])
    return Response(status_code=204)


# ── Scrape lifecycle ──────────────────────────────────────────────────────────


class ScrapeRequest(BaseModel):
    query: str = "ai engineer"
    location: str = "Bengaluru, Karnataka"
    job_type: str = ""       # fulltime|parttime|internship|contract|temporary|permanent|fresher
    radius: str = "25"       # km
    fromage: str = ""        # days: 1|3|7|14
    target_count: int = 50
    salary_filter: str = ""  # e.g. "₹3,00,000"
    direct_url: str = ""     # Bypass build URL logic


@app.post("/api/scrape/start", status_code=202)
def start_scrape(body: ScrapeRequest) -> dict[str, str]:
    """Start a background scrape run."""
    if _scrape_service.is_running:
        raise HTTPException(409, "A scrape run is already in progress")
    _scrape_service.start(
        query=body.query,
        location=body.location,
        job_type=body.job_type,
        radius=body.radius,
        fromage=body.fromage,
        target_count=body.target_count,
        salary_filter=body.salary_filter,
        direct_url=body.direct_url,
    )
    return {"status": "started"}


@app.get("/api/scrape/status")
def get_scrape_status() -> dict[str, Any]:
    """Return the current scrape status and recent logs."""
    s = _scrape_service.status
    entries = _scrape_service.logs[-500:]
    return {
        "state": s.state,
        "phase": s.phase,
        "progress": s.progress,
        "total_jobs": s.total_jobs,
        "enriched_jobs": s.enriched_jobs,
        "error": s.error,
        "logs": [
            {"ts": e.ts, "text": e.text, "level": e.level}
            for e in entries
        ],
    }


@app.post("/api/scrape/stop", status_code=200)
def stop_scrape() -> dict[str, str]:
    if not _scrape_service.is_running:
        raise HTTPException(404, "No active scrape run")
    _scrape_service.stop()
    return {"status": "stopping"}

# ── Internal poller ───────────────────────────────────────────────────────────


def _poll_until_done(uid: str, project_id: str, controller: ResumeRunController) -> None:
    """Runs in a background thread. Polls the controller until the run finishes,
    then syncs artifacts into the DB and cleans up the controller."""
    import shutil

    POLL_INTERVAL = 2.0  # seconds

    while True:
        time.sleep(POLL_INTERVAL)
        controller.poll()
        state = controller.status.state
        if state in {"completed", "failed", "stopped"}:
            break

    # Sync artifacts from output_dir into the DB
    output_dir_str = controller.status.output_dir.strip()
    output_dir = Path(output_dir_str) if output_dir_str and output_dir_str != "-" else None

    try:
        if output_dir and output_dir.exists():
            _backend.replace_project_artifacts_from_local(
                uid=uid,
                project_id=project_id,
                output_dir=output_dir,
            )
            shutil.rmtree(output_dir, ignore_errors=True)

        final_status = "completed" if state == "completed" else "failed"
        error_msg = (
            "" if state == "completed"
            else f"Run ended with state='{state}' (exit_code={controller.status.exit_code})"
        )
        _backend.update_project_status(
            uid=uid,
            project_id=project_id,
            status=final_status,
            error_message=error_msg,
        )
    except Exception as exc:
        try:
            _backend.update_project_status(
                uid=uid,
                project_id=project_id,
                status="failed",
                error_message=f"Sync error: {exc}",
            )
        except Exception:
            pass
    finally:
        _remove_controller(project_id)
