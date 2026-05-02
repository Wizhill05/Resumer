from __future__ import annotations

import json
import re
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = WORKSPACE_ROOT / "data"
DB_PATH = DATA_DIR / "resumer.db"
ARTIFACTS_ROOT = DATA_DIR / "artifacts"
SAMPLE_TRUTH_PATH = WORKSPACE_ROOT / "input" / "sampletruth.json"

DEFAULT_PROFILE_ID = "default-profile"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except Exception:
            pass
    return datetime(1970, 1, 1, tzinfo=timezone.utc)


class LocalBackend:
    """Zero-setup local backend â€” single profile, no auth."""

    def __init__(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        ARTIFACTS_ROOT.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON;")
        self._init_schema()
        self._ensure_default_profile()

    # â”€â”€ Schema â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _init_schema(self) -> None:
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS profiles (
                id TEXT PRIMARY KEY,
                truth_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL DEFAULT 'indeed',
                source_job_key TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                company TEXT NOT NULL DEFAULT '',
                location TEXT NOT NULL DEFAULT '',
                url TEXT NOT NULL DEFAULT '',
                salary_raw TEXT NOT NULL DEFAULT '',
                min_pay_yearly INTEGER,
                max_pay_yearly INTEGER,
                job_type TEXT,
                status TEXT NOT NULL DEFAULT 'new',
                scrape_status TEXT NOT NULL DEFAULT 'pending',
                relative_time TEXT NOT NULL DEFAULT '',
                raw_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(source, source_job_key)
            );

            CREATE TABLE IF NOT EXISTS job_details (
                job_id TEXT PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
                description TEXT NOT NULL DEFAULT '',
                description_html TEXT NOT NULL DEFAULT '',
                attributes_json TEXT NOT NULL DEFAULT '[]',
                posted_at INTEGER,
                experience_required INTEGER,
                requires_experience INTEGER,
                apply_url TEXT NOT NULL DEFAULT '',
                raw_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                job_id TEXT REFERENCES jobs(id) ON DELETE SET NULL,
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
                artifact_type TEXT NOT NULL,
                iteration INTEGER,
                storage_path TEXT NOT NULL,
                file_name TEXT NOT NULL,
                mime_type TEXT NOT NULL,
                size_bytes INTEGER,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS batches (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'draft',
                preferences_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS batch_items (
                id TEXT PRIMARY KEY,
                batch_id TEXT NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
                job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                error_message TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS batch_runs (
                id TEXT PRIMARY KEY,
                batch_id TEXT NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
                model TEXT NOT NULL,
                api_key_env TEXT NOT NULL,
                max_iterations INTEGER NOT NULL DEFAULT 10,
                parallel_runs INTEGER NOT NULL DEFAULT 3,
                status TEXT NOT NULL DEFAULT 'running',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS completed_resumes (
                id TEXT PRIMARY KEY,
                batch_item_id TEXT REFERENCES batch_items(id) ON DELETE SET NULL,
                job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                title TEXT NOT NULL DEFAULT '',
                company TEXT NOT NULL DEFAULT '',
                apply_url TEXT NOT NULL DEFAULT '',
                resume_path TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'ready',
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
            CREATE INDEX IF NOT EXISTS idx_jobs_scrape ON jobs(scrape_status);
            CREATE INDEX IF NOT EXISTS idx_batch_items_batch ON batch_items(batch_id, status);
            CREATE INDEX IF NOT EXISTS idx_batch_runs_batch ON batch_runs(batch_id);
            CREATE INDEX IF NOT EXISTS idx_artifacts_project ON project_artifacts(project_id);
            CREATE INDEX IF NOT EXISTS idx_completed_job ON completed_resumes(job_id);
        """)
        self.conn.commit()

    def _ensure_default_profile(self) -> None:
        row = self.conn.execute("SELECT id FROM profiles LIMIT 1").fetchone()
        if row is None:
            seed = self._read_sample_truth_json()
            now = _now_iso()
            self.conn.execute(
                "INSERT INTO profiles (id, truth_json, created_at, updated_at) VALUES (?,?,?,?)",
                (DEFAULT_PROFILE_ID, json.dumps(seed, ensure_ascii=False), now, now),
            )
            self.conn.commit()

    # â”€â”€ Profile â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def get_profile_id(self) -> str:
        row = self.conn.execute("SELECT id FROM profiles LIMIT 1").fetchone()
        return str(row["id"]) if row else DEFAULT_PROFILE_ID

    def get_truth_json(self, uid: str = "") -> dict[str, Any]:
        pid = uid or self.get_profile_id()
        row = self.conn.execute("SELECT truth_json FROM profiles WHERE id = ?", (pid,)).fetchone()
        if row:
            try:
                data = json.loads(str(row["truth_json"]))
                if isinstance(data, dict) and data:
                    return data
            except Exception:
                pass
        seed = self._read_sample_truth_json()
        self.save_truth_json(uid=pid, truth_json=seed)
        return seed

    def save_truth_json(self, truth_json: dict[str, Any], uid: str = "") -> None:
        pid = uid or self.get_profile_id()
        now = _now_iso()
        self.conn.execute(
            """INSERT INTO profiles (id, truth_json, created_at, updated_at) VALUES (?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET truth_json=excluded.truth_json, updated_at=excluded.updated_at""",
            (pid, json.dumps(truth_json, ensure_ascii=False), now, now),
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

    # â”€â”€ Jobs â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def upsert_jobs(self, *, jobs: list[dict[str, Any]], source: str = "indeed",
                    uid: str = "") -> dict[str, int]:
        from gui.services.salary_parser import parse_salary
        now = _now_iso()
        inserted = updated = skipped = 0
        for raw in jobs:
            n = _normalize_job_payload(raw, source=source)
            if not n["source_job_key"]:
                skipped += 1; continue
            min_pay, max_pay = parse_salary(n["salary_raw"])
            existing = self.conn.execute(
                "SELECT id FROM jobs WHERE source=? AND source_job_key=? LIMIT 1",
                (n["source"], n["source_job_key"]),
            ).fetchone()
            raw_json = json.dumps(raw, ensure_ascii=False, default=str)
            if existing is None:
                job_id = str(uuid4())
                self.conn.execute("""
                    INSERT INTO jobs (id,source,source_job_key,title,company,location,url,
                        salary_raw,min_pay_yearly,max_pay_yearly,job_type,status,scrape_status,
                        relative_time,raw_json,created_at,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (job_id, n["source"], n["source_job_key"], n["title"], n["company"],
                     n["location"], n["url"], n["salary_raw"], min_pay, max_pay,
                     n["job_type"], "new", "pending", n["relative_time"], raw_json, now, now))
                inserted += 1
            else:
                job_id = str(existing["id"])
                self.conn.execute("""
                    UPDATE jobs SET title=?,company=?,location=?,url=?,salary_raw=?,
                        min_pay_yearly=COALESCE(?,min_pay_yearly),
                        max_pay_yearly=COALESCE(?,max_pay_yearly),
                        job_type=COALESCE(?,job_type),relative_time=?,raw_json=?,updated_at=?
                    WHERE id=?""",
                    (n["title"], n["company"], n["location"], n["url"], n["salary_raw"],
                     min_pay, max_pay, n["job_type"], n["relative_time"], raw_json, now, job_id))
                updated += 1
        self.conn.commit()
        return {"inserted": inserted, "updated": updated, "skipped": skipped}

    def list_jobs(self, uid: str = "") -> list[dict[str, Any]]:
        rows = self.conn.execute("""
            SELECT j.*, d.description, d.description_html, d.attributes_json,
                   d.posted_at, d.experience_required, d.requires_experience, d.apply_url,
                   (SELECT COUNT(*) FROM projects p WHERE p.job_id=j.id) AS resume_count
            FROM jobs j LEFT JOIN job_details d ON d.job_id=j.id
            ORDER BY j.updated_at DESC""").fetchall()
        return [_job_row_to_dict(row) for row in rows]

    def get_job(self, *, job_id: str, uid: str = "") -> dict[str, Any] | None:
        row = self.conn.execute("""
            SELECT j.*, d.description, d.description_html, d.attributes_json,
                   d.posted_at, d.experience_required, d.requires_experience, d.apply_url,
                   (SELECT COUNT(*) FROM projects p WHERE p.job_id=j.id) AS resume_count
            FROM jobs j LEFT JOIN job_details d ON d.job_id=j.id
            WHERE j.id=? LIMIT 1""", (job_id,)).fetchone()
        return _job_row_to_dict(row) if row else None

    def update_job_status(self, *, job_id: str, status: str, uid: str = "") -> None:
        self.conn.execute("UPDATE jobs SET status=?,updated_at=? WHERE id=?",
                          (status, _now_iso(), job_id))
        self.conn.commit()

    def delete_job(self, *, job_id: str, uid: str = "") -> None:
        self.conn.execute("DELETE FROM jobs WHERE id=?", (job_id,))
        self.conn.commit()

    # â”€â”€ Job Details â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def upsert_job_details(self, *, job_id: str, description: str = "",
                           description_html: str = "", attributes: list[str] | None = None,
                           posted_at: int | None = None, experience_required: int | None = None,
                           requires_experience: int | None = None, apply_url: str = "",
                           raw_json: str = "{}") -> None:
        now = _now_iso()
        attrs_json = json.dumps(attributes or [], ensure_ascii=False)
        scrape_status = "scraped" if description else "failed"
        self.conn.execute("""
            INSERT INTO job_details (job_id,description,description_html,attributes_json,
                posted_at,experience_required,requires_experience,apply_url,raw_json,created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(job_id) DO UPDATE SET description=excluded.description,
                description_html=excluded.description_html,attributes_json=excluded.attributes_json,
                posted_at=COALESCE(excluded.posted_at,posted_at),
                experience_required=COALESCE(excluded.experience_required,experience_required),
                requires_experience=COALESCE(excluded.requires_experience,requires_experience),
                apply_url=CASE WHEN excluded.apply_url!='' THEN excluded.apply_url ELSE apply_url END,
                raw_json=excluded.raw_json""",
            (job_id, description, description_html, attrs_json, posted_at,
             experience_required, requires_experience, apply_url, raw_json, now))
        self.conn.execute("UPDATE jobs SET scrape_status=?,updated_at=? WHERE id=?",
                          (scrape_status, now, job_id))
        self.conn.commit()

    # â”€â”€ Projects â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def create_project(self, *, name: str, job_description: str,
                       job_id: str | None = None, uid: str = "") -> str:
        project_id = str(uuid4())
        now = _now_iso()
        self.conn.execute("""
            INSERT INTO projects (id,job_id,name,status,job_description,created_at,updated_at)
            VALUES (?,?,?,'running',?,?,?)""",
            (project_id, job_id, name, job_description, now, now))
        self.conn.commit()
        return project_id

    def update_project_status(self, *, project_id: str, status: str,
                              error_message: str = "", uid: str = "") -> None:
        self.conn.execute("UPDATE projects SET status=?,error_message=?,updated_at=? WHERE id=?",
                          (status, error_message, _now_iso(), project_id))
        self.conn.commit()

    def list_projects(self, uid: str = "") -> list[dict[str, Any]]:
        rows = self.conn.execute("""
            SELECT id,job_id,name,status,job_description,error_message,created_at,updated_at
            FROM projects ORDER BY created_at DESC""").fetchall()
        return [{"id": str(r["id"]), "job_id": str(r["job_id"] or ""),
                 "name": str(r["name"]), "status": str(r["status"]),
                 "job_description": str(r["job_description"] or ""),
                 "error_message": str(r["error_message"] or ""),
                 "created_at": _safe_dt(r["created_at"]),
                 "updated_at": _safe_dt(r["updated_at"])} for r in rows]

    def delete_project(self, *, project_id: str, uid: str = "") -> None:
        target_dir = ARTIFACTS_ROOT / "default" / project_id
        if target_dir.exists():
            shutil.rmtree(target_dir, ignore_errors=True)
        self.conn.execute("DELETE FROM project_artifacts WHERE project_id=?", (project_id,))
        self.conn.execute("DELETE FROM projects WHERE id=?", (project_id,))
        self.conn.commit()

    # â”€â”€ Artifacts â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def replace_project_artifacts_from_local(self, *, project_id: str,
                                              output_dir: Path, uid: str = "") -> list[dict]:
        target_dir = ARTIFACTS_ROOT / "default" / project_id
        if target_dir.exists():
            shutil.rmtree(target_dir, ignore_errors=True)
        target_dir.mkdir(parents=True, exist_ok=True)
        self.conn.execute("DELETE FROM project_artifacts WHERE project_id=?", (project_id,))
        files = sorted(
            [p for p in output_dir.iterdir() if p.is_file() and p.suffix.lower() in {".pdf",".md",".json"}],
            key=lambda p: p.stat().st_mtime)
        stored = []
        now = _now_iso()
        for fp in files:
            meta = self._artifact_meta_from_file_name(fp.name)
            dest = target_dir / fp.name
            shutil.copy2(fp, dest)
            self.conn.execute("""
                INSERT INTO project_artifacts (project_id,artifact_type,iteration,storage_path,
                    file_name,mime_type,size_bytes,created_at) VALUES (?,?,?,?,?,?,?,?)""",
                (project_id, meta["artifact_type"], meta["iteration"],
                 str(dest.resolve()), fp.name, meta["mime_type"], fp.stat().st_size, now))
            stored.append({"project_id": project_id, "file_name": fp.name})
        self.conn.execute("UPDATE projects SET updated_at=? WHERE id=?", (now, project_id))
        self.conn.commit()
        return stored

    def list_artifacts(self, *, project_id: str, uid: str = "") -> list[dict[str, Any]]:
        rows = self.conn.execute("""
            SELECT id,project_id,artifact_type,iteration,storage_path,file_name,mime_type,
                   size_bytes,created_at FROM project_artifacts WHERE project_id=?""",
            (project_id,)).fetchall()
        docs = [{"id": int(r["id"]), "project_id": str(r["project_id"]),
                 "artifact_type": str(r["artifact_type"]),
                 "iteration": r["iteration"] if r["iteration"] is not None else None,
                 "storage_path": str(r["storage_path"]), "file_name": str(r["file_name"]),
                 "mime_type": str(r["mime_type"]),
                 "size_bytes": int(r["size_bytes"]) if r["size_bytes"] is not None else None,
                 "created_at": _safe_dt(r["created_at"])} for r in rows]
        docs.sort(key=lambda i: _artifact_sort_key(i), reverse=True)
        return docs

    def signed_url(self, storage_path: str, *, ttl_minutes: int = 60) -> str:
        return storage_path

    def download_bytes(self, storage_path: str) -> bytes:
        return Path(storage_path).read_bytes()

    # â”€â”€ Batches â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def create_batch(self, *, name: str, job_ids: list[str],
                     preferences: dict[str, Any] | None = None,
                     uid: str = "", global_settings: dict | None = None,
                     overrides_by_job: dict | None = None) -> str:
        batch_id = str(uuid4())
        now = _now_iso()
        prefs = preferences or global_settings or {}
        self.conn.execute("""
            INSERT INTO batches (id,name,status,preferences_json,created_at,updated_at)
            VALUES (?,?,'draft',?,?,?)""",
            (batch_id, name.strip() or f"Batch {now[:10]}",
             json.dumps(prefs, ensure_ascii=False), now, now))
        for jid in job_ids:
            self.conn.execute("""
                INSERT INTO batch_items (id,batch_id,job_id,status,created_at,updated_at)
                VALUES (?,?,?,'queued',?,?)""", (str(uuid4()), batch_id, jid, now, now))
            self.conn.execute("UPDATE jobs SET status='queued',updated_at=? WHERE id=? AND status IN ('new','interested')",
                              (now, jid))
        self.conn.commit()
        return batch_id

    def list_batches(self, uid: str = "") -> list[dict[str, Any]]:
        rows = self.conn.execute("""
            SELECT b.*, COUNT(i.id) AS item_count,
                   SUM(CASE WHEN i.status='completed' THEN 1 ELSE 0 END) AS completed_count,
                   SUM(CASE WHEN i.status='failed' THEN 1 ELSE 0 END) AS failed_count
            FROM batches b LEFT JOIN batch_items i ON i.batch_id=b.id
            GROUP BY b.id ORDER BY b.created_at DESC""").fetchall()
        return [_batch_row_to_dict(r) for r in rows]

    def get_batch(self, *, batch_id: str, uid: str = "") -> dict[str, Any] | None:
        for b in self.list_batches():
            if str(b.get("id")) == batch_id:
                return b
        return None

    def list_batch_items(self, *, batch_id: str, uid: str = "") -> list[dict[str, Any]]:
        rows = self.conn.execute("""
            SELECT i.*, j.title, j.company, j.location, j.salary_raw, j.url,
                   d.description, d.apply_url, j.scrape_status
            FROM batch_items i JOIN jobs j ON j.id=i.job_id
            LEFT JOIN job_details d ON d.job_id=j.id
            WHERE i.batch_id=? ORDER BY i.created_at ASC""", (batch_id,)).fetchall()
        return [_batch_item_row_to_dict(r) for r in rows]

    def update_batch_status(self, *, batch_id: str, status: str, uid: str = "") -> None:
        self.conn.execute("UPDATE batches SET status=?,updated_at=? WHERE id=?",
                          (status, _now_iso(), batch_id))
        self.conn.commit()

    def update_batch_settings(self, *, batch_id: str,
                              global_settings: dict[str, Any], uid: str = "") -> None:
        self.conn.execute("UPDATE batches SET preferences_json=?,updated_at=? WHERE id=?",
                          (json.dumps(global_settings, ensure_ascii=False), _now_iso(), batch_id))
        self.conn.commit()

    def delete_batch(self, *, batch_id: str, uid: str = "") -> None:
        self.conn.execute("DELETE FROM batches WHERE id=?", (batch_id,))
        self.conn.commit()

    def update_batch_item_status(self, *, item_id: str, status: str,
                                 project_id: str | None = None,
                                 error_message: str = "", uid: str = "") -> None:
        self.conn.execute("""
            UPDATE batch_items SET status=?,project_id=COALESCE(?,project_id),
                error_message=?,updated_at=? WHERE id=?""",
            (status, project_id, error_message, _now_iso(), item_id))
        self.conn.commit()

    def next_batch_item(self, *, batch_id: str, uid: str = "") -> dict[str, Any] | None:
        for item in self.list_batch_items(batch_id=batch_id):
            if item.get("status") == "queued":
                return item
        return None

    def return_batch_to_pool(self, *, batch_id: str, uid: str = "") -> int:
        """Return failed/queued items back to interested pool."""
        items = self.list_batch_items(batch_id=batch_id)
        count = 0
        now = _now_iso()
        for item in items:
            if item.get("status") in {"failed", "queued", "running"}:
                self.conn.execute("DELETE FROM batch_items WHERE id=?", (str(item["id"]),))
                self.conn.execute("UPDATE jobs SET status='interested',updated_at=? WHERE id=?",
                                  (now, str(item["job_id"])))
                count += 1
        self.conn.commit()
        return count

    # kept for backward compat
    def reset_batch_items_to_interested(self, *, batch_id: str, uid: str = "") -> int:
        return self.return_batch_to_pool(batch_id=batch_id)

    # â”€â”€ Batch Runs â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def create_batch_run(self, *, batch_id: str, model: str, api_key_env: str,
                         max_iterations: int = 10, parallel_runs: int = 3) -> str:
        run_id = str(uuid4())
        now = _now_iso()
        self.conn.execute("""
            INSERT INTO batch_runs (id,batch_id,model,api_key_env,max_iterations,
                parallel_runs,status,created_at,updated_at)
            VALUES (?,?,?,?,?,?,'running',?,?)""",
            (run_id, batch_id, model, api_key_env, max_iterations, parallel_runs, now, now))
        self.conn.commit()
        return run_id

    def get_batch_run(self, *, run_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM batch_runs WHERE id=?", (run_id,)).fetchone()
        if not row:
            return None
        return {"id": str(row["id"]), "batch_id": str(row["batch_id"]),
                "model": str(row["model"]), "api_key_env": str(row["api_key_env"]),
                "max_iterations": int(row["max_iterations"]),
                "parallel_runs": int(row["parallel_runs"]),
                "status": str(row["status"]),
                "created_at": _safe_dt(row["created_at"]),
                "updated_at": _safe_dt(row["updated_at"])}

    def update_batch_run_status(self, *, run_id: str, status: str) -> None:
        self.conn.execute("UPDATE batch_runs SET status=?,updated_at=? WHERE id=?",
                          (status, _now_iso(), run_id))
        self.conn.commit()

    def list_batch_runs(self, *, batch_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM batch_runs WHERE batch_id=? ORDER BY created_at DESC",
            (batch_id,)).fetchall()
        return [{"id": str(r["id"]), "batch_id": str(r["batch_id"]),
                 "model": str(r["model"]), "api_key_env": str(r["api_key_env"]),
                 "max_iterations": int(r["max_iterations"]),
                 "parallel_runs": int(r["parallel_runs"]),
                 "status": str(r["status"]),
                 "created_at": _safe_dt(r["created_at"]),
                 "updated_at": _safe_dt(r["updated_at"])} for r in rows]

    # â”€â”€ Completed Resumes â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def record_completed_resume(self, *, batch_item_id: str | None, job_id: str,
                                project_id: str, title: str, company: str,
                                apply_url: str, resume_path: str) -> str:
        cr_id = str(uuid4())
        self.conn.execute("""
            INSERT INTO completed_resumes (id,batch_item_id,job_id,project_id,title,company,
                apply_url,resume_path,status,created_at)
            VALUES (?,?,?,?,?,?,?,?,'ready',?)""",
            (cr_id, batch_item_id, job_id, project_id, title, company,
             apply_url, resume_path, _now_iso()))
        self.conn.commit()
        return cr_id

    def list_completed_resumes(self) -> list[dict[str, Any]]:
        rows = self.conn.execute("""
            SELECT c.*, j.url AS job_url, j.location
            FROM completed_resumes c JOIN jobs j ON j.id=c.job_id
            ORDER BY c.created_at DESC""").fetchall()
        return [{"id": str(r["id"]), "batch_item_id": str(r["batch_item_id"] or ""),
                 "job_id": str(r["job_id"]), "project_id": str(r["project_id"]),
                 "title": str(r["title"]), "company": str(r["company"]),
                 "apply_url": str(r["apply_url"]), "resume_path": str(r["resume_path"]),
                 "status": str(r["status"]), "job_url": str(r["job_url"] or ""),
                 "location": str(r["location"] or ""),
                 "created_at": _safe_dt(r["created_at"])} for r in rows]

    def update_completed_resume_status(self, *, resume_id: str, status: str) -> None:
        self.conn.execute("UPDATE completed_resumes SET status=? WHERE id=?", (status, resume_id))
        self.conn.commit()

    # â”€â”€ Job generation status (used by run_manager) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def update_job_generation_status_for_project(self, *, project_id: str,
                                                  status: str, uid: str = "") -> None:
        row = self.conn.execute("SELECT job_id FROM projects WHERE id=? LIMIT 1",
                                (project_id,)).fetchone()
        if row and row["job_id"]:
            new_status = "generated" if status == "completed" else "failed"
            self.conn.execute("UPDATE jobs SET status=?,updated_at=? WHERE id=?",
                              (new_status, _now_iso(), str(row["job_id"])))
            self.conn.commit()

    # â”€â”€ Backward compat stubs â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def list_users(self) -> list[dict[str, Any]]:
        pid = self.get_profile_id()
        return [{"id": pid, "display_name": "Default Local User",
                 "created_at": _safe_dt(_now_iso())}]

    def _artifact_meta_from_file_name(self, file_name: str) -> dict[str, Any]:
        lower = file_name.lower()
        m = re.match(r"draft_v(\d+)\.(pdf|md)$", lower)
        if m:
            return {"artifact_type": f"draft_{m.group(2)}", "iteration": int(m.group(1)),
                    "mime_type": "application/pdf" if m.group(2)=="pdf" else "text/markdown"}
        if lower == "final_resume.pdf":
            return {"artifact_type": "final_pdf", "iteration": None, "mime_type": "application/pdf"}
        if lower == "final_resume.md":
            return {"artifact_type": "final_md", "iteration": None, "mime_type": "text/markdown"}
        if lower == "final_resume.json":
            return {"artifact_type": "final_json", "iteration": None, "mime_type": "application/json"}
        m = re.match(r"draft_v(\d+)\.json$", lower)
        if m:
            return {"artifact_type": "draft_json", "iteration": int(m.group(1)),
                    "mime_type": "application/json"}
        ext = Path(file_name).suffix.lower()
        return {"artifact_type": "other", "iteration": None,
                "mime_type": "application/pdf" if ext==".pdf" else
                             "application/json" if ext==".json" else "text/plain"}


# â”€â”€ Module-level helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _first_text(payload: dict[str, Any], *keys: str) -> str:
    for key in keys:
        v = payload.get(key)
        if v is not None:
            t = str(v).strip()
            if t:
                return t
    return ""


def _normalize_job_payload(raw: dict[str, Any], *, source: str) -> dict[str, str]:
    title = _first_text(raw, "Title", "title", "displayTitle")
    company = _first_text(raw, "Company", "company")
    location = _first_text(raw, "Location", "location", "formattedLocation")
    source_job_key = _first_text(raw, "source_job_key", "Job Key", "job_key", "jobkey", "id")
    url = _first_text(raw, "Link", "source_url", "url")
    salary_raw = _first_text(raw, "Salary", "salary", "salary_raw")
    relative_time = _first_text(raw, "Relative Time", "relative_time", "formattedRelativeTime")
    job_type = _first_text(raw, "job_type", "Job Type")
    if not source_job_key:
        identity = "|".join(p for p in (url, title, company, location) if p)
        source_job_key = re.sub(r"\s+", "-", identity.strip().lower())[:160]
    return {"source": source.strip().lower() or "manual", "source_job_key": source_job_key,
            "title": title, "company": company, "location": location, "url": url,
            "salary_raw": salary_raw, "relative_time": relative_time, "job_type": job_type}


def _job_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    desc = str(row["description"] or "") if "description" in row.keys() else ""
    attrs_raw = str(row["attributes_json"] or "[]") if "attributes_json" in row.keys() else "[]"
    try:
        attrs = json.loads(attrs_raw)
    except Exception:
        attrs = []
    return {
        "id": str(row["id"]), "source": str(row["source"]),
        "source_job_key": str(row["source_job_key"]),
        "title": str(row["title"] or ""), "company": str(row["company"] or ""),
        "location": str(row["location"] or ""), "url": str(row["url"] or ""),
        "salary_raw": str(row["salary_raw"] or ""),
        "min_pay_yearly": row["min_pay_yearly"], "max_pay_yearly": row["max_pay_yearly"],
        "job_type": str(row["job_type"] or ""),
        "status": str(row["status"] or "new"),
        "scrape_status": str(row["scrape_status"] or "pending"),
        "relative_time": str(row["relative_time"] or ""),
        "description": desc, "attributes": attrs,
        "posted_at": row["posted_at"] if "posted_at" in row.keys() else None,
        "experience_required": row["experience_required"] if "experience_required" in row.keys() else None,
        "requires_experience": row["requires_experience"] if "requires_experience" in row.keys() else None,
        "apply_url": str(row["apply_url"] or "") if "apply_url" in row.keys() else "",
        "resume_count": int(row["resume_count"] or 0) if "resume_count" in row.keys() else 0,
        "created_at": _safe_dt(row["created_at"]),
        "updated_at": _safe_dt(row["updated_at"]),
        # backward compat aliases
        "source_url": str(row["url"] or ""),
        "salary": str(row["salary_raw"] or ""),
    }


def _batch_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    prefs_text = str(row["preferences_json"] or "{}")
    try:
        prefs = json.loads(prefs_text)
    except Exception:
        prefs = {}
    return {"id": str(row["id"]), "name": str(row["name"]), "status": str(row["status"]),
            "preferences": prefs if isinstance(prefs, dict) else {},
            "global_settings": prefs if isinstance(prefs, dict) else {},
            "item_count": int(row["item_count"] or 0),
            "completed_count": int(row["completed_count"] or 0),
            "failed_count": int(row["failed_count"] or 0),
            "created_at": _safe_dt(row["created_at"]),
            "updated_at": _safe_dt(row["updated_at"])}


def _batch_item_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    keys = row.keys()
    return {
        "id": str(row["id"]), "batch_id": str(row["batch_id"]),
        "job_id": str(row["job_id"]),
        "project_id": str(row["project_id"] or ""),
        "status": str(row["status"]),
        "error_message": str(row["error_message"] or ""),
        "title": str(row["title"] or "") if "title" in keys else "",
        "company": str(row["company"] or "") if "company" in keys else "",
        "location": str(row["location"] or "") if "location" in keys else "",
        "salary": str(row["salary_raw"] or "") if "salary_raw" in keys else "",
        "description": str(row["description"] or "") if "description" in keys else "",
        "description_status": str(row["scrape_status"] or "pending") if "scrape_status" in keys else "pending",
        "source_url": str(row["url"] or "") if "url" in keys else "",
        "apply_url": str(row["apply_url"] or "") if "apply_url" in keys else "",
        "created_at": _safe_dt(row["created_at"]),
        "updated_at": _safe_dt(row["updated_at"]),
        # backward compat
        "settings_override": {},
        "user_id": "",
    }


def _artifact_sort_key(item: dict[str, Any]) -> tuple:
    t = str(item.get("artifact_type", ""))
    rank = {"final_pdf":5,"final_md":4,"final_json":3,"draft_pdf":2,"draft_md":1,"draft_json":0}.get(t, -1)
    it = item.get("iteration")
    if not isinstance(it, int):
        it = -1
    return (rank, it, _safe_dt(item.get("created_at")))

