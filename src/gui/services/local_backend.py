from __future__ import annotations

import json
import re
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = WORKSPACE_ROOT / "data"
DB_PATH = DATA_DIR / "resumer.db"
ARTIFACTS_ROOT = DATA_DIR / "artifacts"
SAMPLE_TRUTH_PATH = WORKSPACE_ROOT / "input" / "sampletruth.json"
DEFAULT_TEMPLATE_PATH = WORKSPACE_ROOT / "template" / "base_resume.jinja2"
DEFAULT_TEMPLATE_CSS_PATH = WORKSPACE_ROOT / "template" / "template.css"


@dataclass(slots=True)
class AuthUser:
    uid: str
    email: str
    id_token: str = ""
    refresh_token: str = ""


class LocalBackend:
    """Zero-setup local backend using SQLite + filesystem storage."""

    def __init__(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        ARTIFACTS_ROOT.mkdir(parents=True, exist_ok=True)

        self.conn = sqlite3.connect(
            str(DB_PATH),
            check_same_thread=False,
            timeout=30,
        )
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON;")
        self.conn.execute("PRAGMA busy_timeout = 30000;")
        try:
            self.conn.execute("PRAGMA journal_mode = WAL;")
        except Exception:
            pass
        self._init_schema()
        self._ensure_default_user()

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS profiles (
                user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                truth_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'running',
                job_description TEXT NOT NULL DEFAULT '',
                error_message TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS project_artifacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                artifact_type TEXT NOT NULL,
                iteration INTEGER NULL,
                storage_path TEXT NOT NULL,
                file_name TEXT NOT NULL,
                mime_type TEXT NOT NULL,
                size_bytes INTEGER NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS resume_templates (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                content TEXT NOT NULL,
                css_content TEXT NOT NULL DEFAULT '',
                is_default INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_projects_user_created
                ON projects(user_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_artifacts_project_created
                ON project_artifacts(project_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_artifacts_user_project
                ON project_artifacts(user_id, project_id);

            CREATE TABLE IF NOT EXISTS scraped_jobs (
                id             TEXT PRIMARY KEY,
                title          TEXT NOT NULL DEFAULT '',
                company        TEXT NOT NULL DEFAULT '',
                location       TEXT NOT NULL DEFAULT '',
                link           TEXT NOT NULL DEFAULT '',
                pay            TEXT NOT NULL DEFAULT '',
                posted_date    TEXT NOT NULL DEFAULT '',
                metadata       TEXT NOT NULL DEFAULT '[]',
                snippet        TEXT NOT NULL DEFAULT '[]',
                description    TEXT NOT NULL DEFAULT '',
                technical_skills TEXT NOT NULL DEFAULT '[]',
                raw_attributes TEXT NOT NULL DEFAULT '[]',
                analysis_applying_for TEXT NOT NULL DEFAULT '',
                analysis_required_skills TEXT NOT NULL DEFAULT '[]',
                analysis_preferred_skills TEXT NOT NULL DEFAULT '[]',
                analysis_key_responsibilities TEXT NOT NULL DEFAULT '[]',
                analysis_keywords TEXT NOT NULL DEFAULT '[]',
                analysis_experience_years INTEGER,
                analysis_seniority_level TEXT NOT NULL DEFAULT '',
                scrape_session TEXT NOT NULL DEFAULT '',
                status         TEXT NOT NULL DEFAULT 'basic',
                scrape_source  TEXT NOT NULL DEFAULT 'indeed',
                project_id     TEXT DEFAULT '',
                resume_error_project_id TEXT DEFAULT '',
                resume_error_path TEXT DEFAULT '',
                resume_error_message TEXT DEFAULT '',
                applied        INTEGER DEFAULT 0,
                created_at     TEXT NOT NULL
            );
            """
        )
        self.conn.commit()
        # Live migration: add preferences_json if the DB was created before this column existed.
        try:
            self.conn.execute(
                "ALTER TABLE profiles ADD COLUMN preferences_json TEXT NOT NULL DEFAULT '{}'"
            )
            self.conn.commit()
        except Exception:
            pass  # Column already exists

        # Live migration: add css_content if the DB was created before this column existed.
        try:
            self.conn.execute(
                "ALTER TABLE resume_templates ADD COLUMN css_content TEXT NOT NULL DEFAULT ''"
            )
            self.conn.commit()
        except Exception:
            pass  # Column already exists

        # Live migration: add job analysis fields if the DB was created earlier.
        for stmt in (
            "ALTER TABLE scraped_jobs ADD COLUMN analysis_applying_for TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE scraped_jobs ADD COLUMN analysis_required_skills TEXT NOT NULL DEFAULT '[]'",
            "ALTER TABLE scraped_jobs ADD COLUMN analysis_preferred_skills TEXT NOT NULL DEFAULT '[]'",
            "ALTER TABLE scraped_jobs ADD COLUMN analysis_key_responsibilities TEXT NOT NULL DEFAULT '[]'",
            "ALTER TABLE scraped_jobs ADD COLUMN analysis_keywords TEXT NOT NULL DEFAULT '[]'",
            "ALTER TABLE scraped_jobs ADD COLUMN analysis_experience_years INTEGER",
            "ALTER TABLE scraped_jobs ADD COLUMN analysis_seniority_level TEXT NOT NULL DEFAULT ''",
        ):
            try:
                self.conn.execute(stmt)
                self.conn.commit()
            except Exception:
                pass  # Column already exists
            
        # Live migration: add project_id if the DB was created before this column existed.
        try:
            self.conn.execute(
                "ALTER TABLE scraped_jobs ADD COLUMN project_id TEXT DEFAULT ''"
            )
            self.conn.commit()
        except Exception:
            pass  # Column already exists

        # Live migration: add applied if the DB was created before this column existed.
        try:
            self.conn.execute(
                "ALTER TABLE scraped_jobs ADD COLUMN applied INTEGER DEFAULT 0"
            )
            self.conn.commit()
        except Exception:
            pass  # Column already exists

        for stmt in (
            "ALTER TABLE scraped_jobs ADD COLUMN resume_error_project_id TEXT DEFAULT ''",
            "ALTER TABLE scraped_jobs ADD COLUMN resume_error_path TEXT DEFAULT ''",
            "ALTER TABLE scraped_jobs ADD COLUMN resume_error_message TEXT DEFAULT ''",
        ):
            try:
                self.conn.execute(stmt)
                self.conn.commit()
            except Exception:
                pass

        # Live migration: salary range fields were removed in favor of raw pay text.
        for stmt in (
            "ALTER TABLE scraped_jobs DROP COLUMN min_salary",
            "ALTER TABLE scraped_jobs DROP COLUMN max_salary",
        ):
            try:
                self.conn.execute(stmt)
                self.conn.commit()
            except Exception:
                pass

        # Live migration: add scrape_source to distinguish Indeed vs LinkedIn jobs.
        try:
            self.conn.execute(
                "ALTER TABLE scraped_jobs ADD COLUMN scrape_source TEXT NOT NULL DEFAULT 'indeed'"
            )
            self.conn.commit()
        except Exception:
            pass  # Column already exists

    def _ensure_default_user(self) -> None:
        count = self.conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if count == 0:
            self.create_user("Default Local User")

    def list_users(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT id, display_name, created_at FROM users ORDER BY created_at DESC"
        ).fetchall()
        users: list[dict[str, Any]] = []
        for row in rows:
            users.append(
                {
                    "id": str(row["id"]),
                    "display_name": str(row["display_name"]),
                    "created_at": _safe_dt(row["created_at"]),
                }
            )
        return users

    def create_user(self, display_name: str) -> AuthUser:
        name = re.sub(r"\s+", " ", display_name.strip())
        if not name:
            raise ValueError("Profile name is required.")

        now = _now_iso()
        user_id = str(uuid4())
        self.conn.execute(
            """
            INSERT INTO users (id, display_name, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, name, now, now),
        )
        self.conn.commit()
        self.save_truth_json(user_id, self._read_sample_truth_json())
        return AuthUser(uid=user_id, email=name)

    def use_user(self, user_id: str) -> AuthUser:
        row = self.conn.execute(
            "SELECT id, display_name FROM users WHERE id = ? LIMIT 1", (user_id,)
        ).fetchone()
        if row is None:
            raise RuntimeError("Selected profile not found.")
        return AuthUser(uid=str(row["id"]), email=str(row["display_name"]))

    def get_truth_json(self, uid: str) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT truth_json FROM profiles WHERE user_id = ? LIMIT 1", (uid,)
        ).fetchone()
        if row is not None:
            try:
                payload = json.loads(str(row["truth_json"]))
                if isinstance(payload, dict):
                    if payload:
                        return payload
                    seed = self._read_sample_truth_json()
                    self.save_truth_json(uid, seed)
                    return seed
            except Exception:
                pass

        seed = self._read_sample_truth_json()
        self.save_truth_json(uid, seed)
        return seed

    def save_truth_json(self, uid: str, truth_json: dict[str, Any]) -> None:
        now = _now_iso()
        payload = json.dumps(truth_json, ensure_ascii=False)
        self.conn.execute(
            """
            INSERT INTO profiles (user_id, truth_json, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                truth_json = excluded.truth_json,
                updated_at = excluded.updated_at
            """,
            (uid, payload, now, now),
        )
        self.conn.commit()

    def get_preferences(self, uid: str) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT preferences_json FROM profiles WHERE user_id = ? LIMIT 1", (uid,)
        ).fetchone()
        if row is not None:
            try:
                data = json.loads(str(row["preferences_json"] or "{}"))
                if isinstance(data, dict):
                    return data
            except Exception:
                pass
        return {}

    def save_preferences(self, uid: str, preferences: dict[str, Any]) -> None:
        now = _now_iso()
        payload = json.dumps(preferences, ensure_ascii=False)
        self.conn.execute(
            """
            INSERT INTO profiles (user_id, truth_json, preferences_json, created_at, updated_at)
            VALUES (?, '{}', ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                preferences_json = excluded.preferences_json,
                updated_at = excluded.updated_at
            """,
            (uid, payload, now, now),
        )
        self.conn.commit()

    def list_resume_templates(self, uid: str) -> list[dict[str, Any]]:
        self._ensure_default_template(uid)
        rows = self.conn.execute(
            """
            SELECT id, user_id, name, content, css_content, is_default, created_at, updated_at
            FROM resume_templates
            WHERE user_id = ?
            ORDER BY is_default DESC, updated_at DESC
            """,
            (uid,),
        ).fetchall()
        return [
            {
                "id": str(row["id"]),
                "user_id": str(row["user_id"]),
                "name": str(row["name"]),
                "content": str(row["content"]),
                "css_content": str(row["css_content"]),
                "is_default": bool(row["is_default"]),
                "created_at": _safe_dt(row["created_at"]),
                "updated_at": _safe_dt(row["updated_at"]),
            }
            for row in rows
        ]

    def create_resume_template(
        self, uid: str, name: str, content: str, *, css_content: str = "", is_default: bool = False
    ) -> dict[str, Any]:
        template_id = str(uuid4())
        now = _now_iso()
        if is_default:
            self.conn.execute(
                "UPDATE resume_templates SET is_default = 0 WHERE user_id = ?",
                (uid,),
            )
        self.conn.execute(
            """
            INSERT INTO resume_templates (id, user_id, name, content, css_content, is_default, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (template_id, uid, name.strip() or "Untitled Template", content, css_content, 1 if is_default else 0, now, now),
        )
        self.conn.commit()
        return self.get_resume_template(uid, template_id) or {}

    def get_resume_template(self, uid: str, template_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT id, user_id, name, content, css_content, is_default, created_at, updated_at
            FROM resume_templates
            WHERE user_id = ? AND id = ?
            LIMIT 1
            """,
            (uid, template_id),
        ).fetchone()
        if row is None:
            return None
        return {
            "id": str(row["id"]),
            "user_id": str(row["user_id"]),
            "name": str(row["name"]),
            "content": str(row["content"]),
            "css_content": str(row["css_content"]),
            "is_default": bool(row["is_default"]),
            "created_at": _safe_dt(row["created_at"]),
            "updated_at": _safe_dt(row["updated_at"]),
        }

    def get_default_resume_template(self, uid: str) -> dict[str, Any] | None:
        self._ensure_default_template(uid)
        row = self.conn.execute(
            """
            SELECT id
            FROM resume_templates
            WHERE user_id = ? AND is_default = 1
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (uid,),
        ).fetchone()
        if row is None:
            return None
        return self.get_resume_template(uid, str(row["id"]))

    def update_resume_template(
        self, uid: str, template_id: str, name: str, content: str, css_content: str = ""
    ) -> None:
        now = _now_iso()
        self.conn.execute(
            """
            UPDATE resume_templates
            SET name = ?, content = ?, css_content = ?, updated_at = ?
            WHERE user_id = ? AND id = ?
            """,
            (name.strip() or "Untitled Template", content, css_content, now, uid, template_id),
        )
        self.conn.commit()

    def delete_resume_template(self, uid: str, template_id: str) -> None:
        row = self.conn.execute(
            "SELECT is_default FROM resume_templates WHERE user_id = ? AND id = ?",
            (uid, template_id),
        ).fetchone()
        self.conn.execute(
            "DELETE FROM resume_templates WHERE user_id = ? AND id = ?",
            (uid, template_id),
        )
        self.conn.commit()
        if row is not None and bool(row["is_default"]):
            remaining = self.list_resume_templates(uid)
            if remaining:
                self.set_default_resume_template(uid, remaining[0]["id"])

    def set_default_resume_template(self, uid: str, template_id: str) -> None:
        now = _now_iso()
        self.conn.execute(
            "UPDATE resume_templates SET is_default = 0 WHERE user_id = ?",
            (uid,),
        )
        self.conn.execute(
            """
            UPDATE resume_templates
            SET is_default = 1, updated_at = ?
            WHERE user_id = ? AND id = ?
            """,
            (now, uid, template_id),
        )
        self.conn.commit()

    def _ensure_default_template(self, uid: str) -> None:
        existing = self.conn.execute(
            "SELECT COUNT(*) FROM resume_templates WHERE user_id = ?",
            (uid,),
        ).fetchone()[0]
        if existing:
            return

        content = DEFAULT_TEMPLATE_PATH.read_text(encoding="utf-8")
        css_content = DEFAULT_TEMPLATE_CSS_PATH.read_text(encoding="utf-8")
        self.create_resume_template(
            uid,
            "Readable Tabulated Resume",
            content,
            css_content=css_content,
            is_default=True,
        )

    def create_project(self, *, uid: str, name: str, job_description: str) -> str:
        project_id = str(uuid4())
        now = _now_iso()
        self.conn.execute(
            """
            INSERT INTO projects (id, user_id, name, status, job_description, created_at, updated_at)
            VALUES (?, ?, ?, 'running', ?, ?, ?)
            """,
            (project_id, uid, name, job_description, now, now),
        )
        self.conn.commit()
        return project_id

    def update_project_status(
        self,
        *,
        uid: str,
        project_id: str,
        status: str,
        error_message: str = "",
    ) -> None:
        now = _now_iso()
        self.conn.execute(
            """
            UPDATE projects
            SET status = ?, error_message = ?, updated_at = ?
            WHERE id = ? AND user_id = ?
            """,
            (status, error_message, now, project_id, uid),
        )
        self.conn.commit()

    def list_projects(self, uid: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT id, user_id, name, status, job_description, error_message, created_at, updated_at
            FROM projects
            WHERE user_id = ?
            ORDER BY created_at DESC
            """,
            (uid,),
        ).fetchall()
        projects: list[dict[str, Any]] = []
        for row in rows:
            projects.append(
                {
                    "id": str(row["id"]),
                    "user_id": str(row["user_id"]),
                    "name": str(row["name"]),
                    "status": str(row["status"]),
                    "job_description": str(row["job_description"] or ""),
                    "error_message": str(row["error_message"] or ""),
                    "created_at": _safe_dt(row["created_at"]),
                    "updated_at": _safe_dt(row["updated_at"]),
                }
            )
        return projects

    def replace_project_artifacts_from_local(
        self,
        *,
        uid: str,
        project_id: str,
        output_dir: Path,
    ) -> list[dict[str, Any]]:
        target_dir = ARTIFACTS_ROOT / uid / project_id
        if target_dir.exists():
            shutil.rmtree(target_dir, ignore_errors=True)
        target_dir.mkdir(parents=True, exist_ok=True)
        self._delete_all_artifact_rows(uid=uid, project_id=project_id)

        output_files = [
            p
            for p in output_dir.iterdir()
            if p.is_file() and p.suffix.lower() in {".pdf", ".md", ".json"}
        ]
        output_files.sort(key=lambda p: p.stat().st_mtime)

        stored: list[dict[str, Any]] = []
        now = _now_iso()
        for file_path in output_files:
            meta = self._artifact_meta_from_file_name(file_path.name)
            destination = target_dir / file_path.name
            shutil.copy2(file_path, destination)
            storage_path = str(destination.resolve())

            self.conn.execute(
                """
                INSERT INTO project_artifacts (
                    project_id, user_id, artifact_type, iteration, storage_path, file_name, mime_type, size_bytes, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    uid,
                    meta["artifact_type"],
                    meta["iteration"],
                    storage_path,
                    file_path.name,
                    meta["mime_type"],
                    file_path.stat().st_size,
                    now,
                ),
            )
            stored.append(
                {
                    "project_id": project_id,
                    "user_id": uid,
                    "artifact_type": meta["artifact_type"],
                    "iteration": meta["iteration"],
                    "storage_path": storage_path,
                    "file_name": file_path.name,
                    "mime_type": meta["mime_type"],
                    "size_bytes": file_path.stat().st_size,
                    "created_at": _safe_dt(now),
                }
            )

        self.conn.execute(
            "UPDATE projects SET updated_at = ? WHERE id = ? AND user_id = ?",
            (now, project_id, uid),
        )
        self.conn.commit()
        return stored

    def list_artifacts(self, *, uid: str, project_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT id, project_id, user_id, artifact_type, iteration, storage_path, file_name, mime_type, size_bytes, created_at
            FROM project_artifacts
            WHERE user_id = ? AND project_id = ?
            """,
            (uid, project_id),
        ).fetchall()
        docs: list[dict[str, Any]] = []
        for row in rows:
            docs.append(
                {
                    "id": int(row["id"]),
                    "project_id": str(row["project_id"]),
                    "user_id": str(row["user_id"]),
                    "artifact_type": str(row["artifact_type"]),
                    "iteration": row["iteration"] if row["iteration"] is not None else None,
                    "storage_path": str(row["storage_path"]),
                    "file_name": str(row["file_name"]),
                    "mime_type": str(row["mime_type"]),
                    "size_bytes": int(row["size_bytes"]) if row["size_bytes"] is not None else None,
                    "created_at": _safe_dt(row["created_at"]),
                }
            )
        docs.sort(key=lambda item: _artifact_sort_key(item), reverse=True)
        return docs

    def signed_url(self, storage_path: str, *, ttl_minutes: int = 60) -> str:
        _ = ttl_minutes
        return storage_path

    def download_bytes(self, storage_path: str) -> bytes:
        path = Path(storage_path)
        return path.read_bytes()

    def delete_project(self, *, uid: str, project_id: str) -> None:
        target_dir = ARTIFACTS_ROOT / uid / project_id
        if target_dir.exists():
            shutil.rmtree(target_dir, ignore_errors=True)
        self._delete_all_artifact_rows(uid=uid, project_id=project_id)
        self.conn.execute(
            "DELETE FROM projects WHERE id = ? AND user_id = ?",
            (project_id, uid),
        )
        self.conn.commit()

    def _delete_all_artifact_rows(self, *, uid: str, project_id: str) -> None:
        self.conn.execute(
            "DELETE FROM project_artifacts WHERE user_id = ? AND project_id = ?",
            (uid, project_id),
        )
        self.conn.commit()

    def _read_sample_truth_json(self) -> dict[str, Any]:
        if SAMPLE_TRUTH_PATH.exists():
            try:
                data = json.loads(SAMPLE_TRUTH_PATH.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
            except Exception:
                pass
        return {}

    def sample_truth_json(self) -> dict[str, Any]:
        return self._read_sample_truth_json()

    # ── Scraped Jobs CRUD ─────────────────────────────────────────────────────

    def upsert_scraped_job(self, job: dict[str, Any]) -> None:
        now = _now_iso()
        self.conn.execute(
            """
            INSERT INTO scraped_jobs (
                id, title, company, location, link, pay,
                posted_date, metadata, snippet, description,
                technical_skills, raw_attributes,
                analysis_applying_for, analysis_required_skills,
                analysis_preferred_skills, analysis_key_responsibilities,
                analysis_keywords, analysis_experience_years,
                analysis_seniority_level,
                scrape_session, status, scrape_source, project_id,
                resume_error_project_id, resume_error_path, resume_error_message,
                applied, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title = excluded.title,
                company = excluded.company,
                location = excluded.location,
                link = excluded.link,
                pay = excluded.pay,
                posted_date = excluded.posted_date,
                metadata = excluded.metadata,
                snippet = excluded.snippet,
                description = excluded.description,
                technical_skills = excluded.technical_skills,
                raw_attributes = excluded.raw_attributes,
                analysis_applying_for = excluded.analysis_applying_for,
                analysis_required_skills = excluded.analysis_required_skills,
                analysis_preferred_skills = excluded.analysis_preferred_skills,
                analysis_key_responsibilities = excluded.analysis_key_responsibilities,
                analysis_keywords = excluded.analysis_keywords,
                analysis_experience_years = excluded.analysis_experience_years,
                analysis_seniority_level = excluded.analysis_seniority_level,
                scrape_session = excluded.scrape_session,
                status = excluded.status,
                scrape_source = excluded.scrape_source,
                project_id = COALESCE(NULLIF(scraped_jobs.project_id, ''), excluded.project_id),
                resume_error_project_id = scraped_jobs.resume_error_project_id,
                resume_error_path = scraped_jobs.resume_error_path,
                resume_error_message = scraped_jobs.resume_error_message,
                applied = excluded.applied
            """,
            (
                job.get("id"),
                job.get("title", ""),
                job.get("company", ""),
                job.get("location", ""),
                job.get("link", ""),
                job.get("pay", ""),
                job.get("posted_date", ""),
                json.dumps(job.get("metadata", []), ensure_ascii=False),
                json.dumps(job.get("snippet", []), ensure_ascii=False),
                job.get("description", ""),
                json.dumps(job.get("technical_skills", []), ensure_ascii=False),
                json.dumps(job.get("raw_attributes", []), ensure_ascii=False),
                str(job.get("applying_for", "")),
                json.dumps(job.get("required_skills", []), ensure_ascii=False),
                json.dumps(job.get("preferred_skills", []), ensure_ascii=False),
                json.dumps(job.get("key_responsibilities", []), ensure_ascii=False),
                json.dumps(job.get("keywords", []), ensure_ascii=False),
                job.get("experience_years"),
                str(job.get("seniority_level", "")),
                job.get("scrape_session", ""),
                job.get("status", "basic"),
                job.get("scrape_source", "indeed"),
                job.get("project_id", ""),
                job.get("resume_error_project_id", ""),
                job.get("resume_error_path", ""),
                job.get("resume_error_message", ""),
                job.get("applied", 0),
                now,
            ),
        )
        self.conn.commit()

    def upsert_scraped_jobs(self, jobs: list[dict[str, Any]]) -> None:
        """Batch upsert a list of scraped jobs."""
        for job in jobs:
            self.upsert_scraped_job(job)

    def list_scraped_jobs(self) -> list[dict[str, Any]]:
        """Return all scraped jobs."""
        self.reconcile_job_resume_links()
        rows = self.conn.execute(
            """
            SELECT id, title, company, location, link, pay,
                   posted_date,
                   metadata, snippet, description,
                   technical_skills, raw_attributes,
                   analysis_applying_for, analysis_required_skills,
                   analysis_preferred_skills, analysis_key_responsibilities,
                   analysis_keywords, analysis_experience_years,
                   analysis_seniority_level,
                   scrape_session, status, scrape_source, project_id,
                   resume_error_project_id, resume_error_path, resume_error_message,
                   applied, created_at
            FROM scraped_jobs
            ORDER BY created_at DESC
            """
        ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            result.append({
                "id": str(row["id"]),
                "title": str(row["title"]),
                "company": str(row["company"]),
                "location": str(row["location"]),
                "link": str(row["link"]),
                "pay": str(row["pay"]),
                "posted_date": str(row["posted_date"]),
                "metadata": json.loads(row["metadata"] or "[]"),
                "snippet": json.loads(row["snippet"] or "[]"),
                "description": str(row["description"]),
                "technical_skills": json.loads(row["technical_skills"] or "[]"),
                "raw_attributes": json.loads(row["raw_attributes"] or "[]"),
                "applying_for": str(row["analysis_applying_for"] or ""),
                "required_skills": json.loads(row["analysis_required_skills"] or "[]"),
                "preferred_skills": json.loads(
                    row["analysis_preferred_skills"] or "[]"
                ),
                "key_responsibilities": json.loads(
                    row["analysis_key_responsibilities"] or "[]"
                ),
                "keywords": json.loads(row["analysis_keywords"] or "[]"),
                "experience_years": row["analysis_experience_years"],
                "seniority_level": str(row["analysis_seniority_level"] or ""),
                "scrape_session": str(row["scrape_session"]),
                "status": str(row["status"]),
                "scrape_source": str(row["scrape_source"] or "indeed"),
                "project_id": str(row["project_id"] or ""),
                "resume_error_project_id": str(row["resume_error_project_id"] or ""),
                "resume_error_path": str(row["resume_error_path"] or ""),
                "resume_error_message": str(row["resume_error_message"] or ""),
                "applied": bool(row["applied"]),
                "created_at": _safe_dt(row["created_at"]),
            })
        return result

    def reconcile_job_resume_links(self) -> None:
        rows = self.conn.execute(
            """
            SELECT sj.id, sj.project_id, pa.storage_path
            FROM scraped_jobs sj
            LEFT JOIN project_artifacts pa ON sj.project_id = pa.project_id AND pa.artifact_type IN ('final_pdf', 'final_md')
            WHERE COALESCE(sj.project_id, '') != ''
            """
        ).fetchall()

        job_validity = {}
        for row in rows:
            job_id = str(row["id"])
            storage_path = row["storage_path"]
            
            if job_id not in job_validity:
                job_validity[job_id] = False
            
            if storage_path and Path(str(storage_path)).is_file():
                job_validity[job_id] = True

        to_unlink = [job_id for job_id, is_valid in job_validity.items() if not is_valid]

        if to_unlink:
            chunk_size = 999
            for i in range(0, len(to_unlink), chunk_size):
                chunk = to_unlink[i : i + chunk_size]
                placeholders = ",".join("?" for _ in chunk)
                self.conn.execute(
                    f"UPDATE scraped_jobs SET project_id = '' WHERE id IN ({placeholders})",
                    chunk,
                )
            self.conn.commit()

    def update_job_analysis_by_project_id(
        self, *, project_id: str, analysis: dict[str, Any]
    ) -> None:
        self.conn.execute(
            """
            UPDATE scraped_jobs
            SET analysis_applying_for = ?,
                analysis_required_skills = ?,
                analysis_preferred_skills = ?,
                analysis_key_responsibilities = ?,
                analysis_keywords = ?,
                analysis_experience_years = ?,
                analysis_seniority_level = ?
            WHERE project_id = ?
            """,
            (
                str(analysis.get("applying_for", "")),
                json.dumps(analysis.get("required_skills", []), ensure_ascii=False),
                json.dumps(analysis.get("preferred_skills", []), ensure_ascii=False),
                json.dumps(
                    analysis.get("key_responsibilities", []), ensure_ascii=False
                ),
                json.dumps(analysis.get("keywords", []), ensure_ascii=False),
                analysis.get("experience_years"),
                str(analysis.get("seniority_level", "")),
                project_id,
            ),
        )
        self.conn.commit()

    def update_job_analysis_by_job_id_from_project(
        self, *, job_id: str, project_id: str
    ) -> None:
        row = self.conn.execute(
            """
            SELECT storage_path
            FROM project_artifacts
            WHERE project_id = ? AND artifact_type = 'job_analysis_json'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (project_id,),
        ).fetchone()
        if row is None:
            return
        analysis_path = Path(str(row["storage_path"]))
        if not analysis_path.exists() or not analysis_path.is_file():
            return
        analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
        if not isinstance(analysis, dict):
            return

        self.conn.execute(
            """
            UPDATE scraped_jobs
            SET analysis_applying_for = ?,
                analysis_required_skills = ?,
                analysis_preferred_skills = ?,
                analysis_key_responsibilities = ?,
                analysis_keywords = ?,
                analysis_experience_years = ?,
                analysis_seniority_level = ?
            WHERE id = ?
            """,
            (
                str(analysis.get("applying_for", "")),
                json.dumps(analysis.get("required_skills", []), ensure_ascii=False),
                json.dumps(analysis.get("preferred_skills", []), ensure_ascii=False),
                json.dumps(
                    analysis.get("key_responsibilities", []), ensure_ascii=False
                ),
                json.dumps(analysis.get("keywords", []), ensure_ascii=False),
                analysis.get("experience_years"),
                str(analysis.get("seniority_level", "")),
                job_id,
            ),
        )
        self.conn.commit()

    def set_job_applied(self, job_id: str, applied: bool) -> None:
        """Mark a job as applied or not applied."""
        self.conn.execute(
            "UPDATE scraped_jobs SET applied = ? WHERE id = ?",
            (1 if applied else 0, job_id)
        )
        self.conn.commit()

    def delete_scraped_jobs(self, ids: list[str]) -> None:
        """Delete scraped jobs by ID."""
        if not ids:
            return
        placeholders = ",".join("?" for _ in ids)
        self.conn.execute(
            f"DELETE FROM scraped_jobs WHERE id IN ({placeholders})", ids
        )
        self.conn.commit()

    def link_job_to_project(self, job_id: str, project_id: str) -> None:
        """Update the project_id for a scraped job."""
        self.conn.execute(
            """
            UPDATE scraped_jobs
            SET project_id = ?,
                resume_error_project_id = '',
                resume_error_path = '',
                resume_error_message = ''
            WHERE id = ?
            """,
            (project_id, job_id),
        )
        self.conn.commit()

    def mark_job_resume_error(
        self,
        *,
        job_id: str,
        project_id: str,
        error_path: str,
        error_message: str,
    ) -> None:
        self.conn.execute(
            """
            UPDATE scraped_jobs
            SET project_id = '',
                resume_error_project_id = ?,
                resume_error_path = ?,
                resume_error_message = ?
            WHERE id = ?
            """,
            (project_id, error_path, error_message, job_id),
        )
        self.conn.commit()

    def delete_all_scraped_jobs(self) -> None:
        """Wipe all scraped jobs."""
        self.conn.execute("DELETE FROM scraped_jobs")
        self.conn.commit()

    def _artifact_meta_from_file_name(self, file_name: str) -> dict[str, Any]:
        lower_name = file_name.lower()
        match = re.match(r"draft_v(\d+)\.(pdf|md)$", lower_name)
        if match:
            iteration = int(match.group(1))
            ext = match.group(2)
            return {
                "artifact_type": f"draft_{ext}",
                "iteration": iteration,
                "mime_type": "application/pdf" if ext == "pdf" else "text/markdown",
            }
        if lower_name == "final_resume.pdf":
            return {
                "artifact_type": "final_pdf",
                "iteration": None,
                "mime_type": "application/pdf",
            }
        if lower_name == "final_resume.md":
            return {
                "artifact_type": "final_md",
                "iteration": None,
                "mime_type": "text/markdown",
            }
        if lower_name == "job_analysis.json":
            return {
                "artifact_type": "job_analysis_json",
                "iteration": None,
                "mime_type": "application/json",
            }
        if lower_name == "error.md":
            return {
                "artifact_type": "error_md",
                "iteration": None,
                "mime_type": "text/markdown",
            }
        if lower_name == "model_conversations.md":
            return {
                "artifact_type": "model_conversations_md",
                "iteration": None,
                "mime_type": "text/markdown",
            }
        ext = Path(file_name).suffix.lower()
        return {
            "artifact_type": "other",
            "iteration": None,
            "mime_type": (
                "application/pdf"
                if ext == ".pdf"
                else "text/markdown"
                if ext == ".md"
                else "application/json"
                if ext == ".json"
                else "text/plain"
            ),
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except Exception:
            pass
    return datetime(1970, 1, 1, tzinfo=timezone.utc)


def _artifact_sort_key(item: dict[str, Any]) -> tuple[int, int, datetime]:
    artifact_type = str(item.get("artifact_type", ""))
    if artifact_type == "final_pdf":
        rank = 5
    elif artifact_type == "final_md":
        rank = 4
    elif artifact_type == "model_conversations_md":
        rank = 3
    elif artifact_type == "draft_pdf":
        rank = 2
    elif artifact_type == "draft_md":
        rank = 1
    else:
        rank = 0
    iteration = item.get("iteration")
    if not isinstance(iteration, int):
        iteration = -1
    created_at = _safe_dt(item.get("created_at"))
    return (rank, iteration, created_at)
