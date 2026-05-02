"""
Pydantic request/response schemas for the Resumer API.
These are separate from schemas/resume_schema.py (which defines TailoredResume).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel


# ── Profiles ───────────────────────────────────────────────────────────────

class ProfileOut(BaseModel):
    uid: str
    truth_json: dict[str, Any]


class SaveProfileIn(BaseModel):
    truth_json: dict[str, Any]


class ValidateProfileOut(BaseModel):
    syntax_ok: bool
    is_dict: bool
    warnings: list[str]
    error: Optional[str] = None


# ── Artifacts ──────────────────────────────────────────────────────────────

class ArtifactOut(BaseModel):
    id: int
    project_id: str
    artifact_type: str
    iteration: Optional[int]
    storage_path: str
    file_name: str
    mime_type: str
    size_bytes: Optional[int]
    created_at: datetime


# ── Projects ───────────────────────────────────────────────────────────────

class ProjectOut(BaseModel):
    id: str
    job_id: str
    name: str
    status: str
    job_description: str
    error_message: str
    created_at: datetime
    updated_at: datetime


class RerenderIn(BaseModel):
    omissions: dict[str, bool]


# ── Run controls ───────────────────────────────────────────────────────────

class StartRunIn(BaseModel):
    jd_text: Optional[str] = None
    jd_path: Optional[str] = None
    run_name: str = "manual_run"
    model: str
    api_key_env: str
    max_iterations: int = 10
    omissions: dict[str, bool] = {}
    job_id: Optional[str] = None


class RunStatusOut(BaseModel):
    state: str
    model: str
    current_step: str
    active_agent: str
    active_task: str
    iteration: str
    output_dir: str
    final_pdf: str
    project_id: str
    project_name: str
    run_started_at: Optional[float]
    run_finished_at: Optional[float]
    exit_code: Optional[int]


class LogEntryOut(BaseModel):
    ts: float
    stream: str
    text: str
    level: str


# ── Jobs ───────────────────────────────────────────────────────────────────

class JobOut(BaseModel):
    id: str
    source: str
    source_job_key: str
    title: str
    company: str
    location: str
    url: str
    salary_raw: str
    min_pay_yearly: Optional[int]
    max_pay_yearly: Optional[int]
    job_type: str
    status: str
    scrape_status: str
    relative_time: str
    description: str
    attributes: list[str]
    posted_at: Optional[int]
    experience_required: Optional[int]
    requires_experience: Optional[int]
    apply_url: str
    resume_count: int
    created_at: datetime
    updated_at: datetime
    # backward compat
    source_url: str = ""
    salary: str = ""


class UpdateJobStatusIn(BaseModel):
    status: str


class ImportJobsIn(BaseModel):
    html_path: Optional[str] = None
    source: str = "indeed"


class ScrapeStatusOut(BaseModel):
    has_driver: bool
    awaiting_verification: bool


class ScrapeRunIn(BaseModel):
    wait_seconds: int = 120


# ── Batches ────────────────────────────────────────────────────────────────

class BatchOut(BaseModel):
    id: str
    name: str
    status: str
    preferences: dict[str, Any]
    global_settings: dict[str, Any]
    item_count: int
    completed_count: int
    failed_count: int
    created_at: datetime
    updated_at: datetime


class BatchItemOut(BaseModel):
    id: str
    batch_id: str
    job_id: str
    project_id: str
    status: str
    error_message: str
    title: str
    company: str
    location: str
    salary: str
    description: str
    description_status: str
    source_url: str
    apply_url: str
    created_at: datetime
    updated_at: datetime
    settings_override: dict[str, Any] = {}
    user_id: str = ""


class CreateBatchIn(BaseModel):
    name: str
    job_ids: list[str]
    preferences: dict[str, Any] = {}
    # backward compat
    global_settings: dict[str, Any] = {}
    overrides_by_job: dict[str, dict[str, Any]] = {}


class UpdateBatchSettingsIn(BaseModel):
    global_settings: dict[str, Any]


class CreateBatchRunIn(BaseModel):
    model: str
    api_key_env: str
    max_iterations: int = 10
    parallel_runs: int = 3


class BatchRunOut(BaseModel):
    id: str
    batch_id: str
    model: str
    api_key_env: str
    max_iterations: int
    parallel_runs: int
    status: str
    created_at: datetime
    updated_at: datetime


class CompletedResumeOut(BaseModel):
    id: str
    batch_item_id: str
    job_id: str
    project_id: str
    title: str
    company: str
    apply_url: str
    resume_path: str
    status: str
    job_url: str
    location: str
    created_at: datetime


class RerenderBatchIn(BaseModel):
    omissions: dict[str, bool]
    project_ids: list[str]
