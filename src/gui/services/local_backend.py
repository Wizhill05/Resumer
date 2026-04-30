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

        self.conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON;")
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

            CREATE INDEX IF NOT EXISTS idx_projects_user_created
                ON projects(user_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_artifacts_project_created
                ON project_artifacts(project_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_artifacts_user_project
                ON project_artifacts(user_id, project_id);
            """
        )
        self.conn.commit()

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
            if p.is_file() and p.suffix.lower() in {".pdf", ".md"}
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
        ext = Path(file_name).suffix.lower()
        return {
            "artifact_type": "other",
            "iteration": None,
            "mime_type": "application/pdf" if ext == ".pdf" else "text/plain",
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
    elif artifact_type == "draft_pdf":
        rank = 3
    elif artifact_type == "draft_md":
        rank = 2
    else:
        rank = 1
    iteration = item.get("iteration")
    if not isinstance(iteration, int):
        iteration = -1
    created_at = _safe_dt(item.get("created_at"))
    return (rank, iteration, created_at)
