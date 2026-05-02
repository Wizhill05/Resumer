"""Jobs router — import, list, scrape, status updates."""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, UploadFile, File, Form

from api.deps import BackendDep
from api.schemas import JobOut, UpdateJobStatusIn, ImportJobsIn, ScrapeStatusOut, ScrapeRunIn

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

# Module-level scraper session state
_scraper_state: dict[str, Any] = {"driver": None, "jobs_for_scrape": []}


@router.get("/{uid}", response_model=list[JobOut])
def list_jobs(uid: str, backend: BackendDep):
    return [_job_out(j) for j in backend.list_jobs()]


@router.get("/{uid}/{job_id}", response_model=JobOut)
def get_job(uid: str, job_id: str, backend: BackendDep):
    job = backend.get_job(job_id=job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return _job_out(job)


@router.put("/{uid}/{job_id}/state")
def update_job_state(uid: str, job_id: str, body: UpdateJobStatusIn, backend: BackendDep):
    backend.update_job_status(job_id=job_id, status=body.status)
    return {"ok": True}


@router.delete("/{uid}/{job_id}")
def delete_job(uid: str, job_id: str, backend: BackendDep):
    backend.delete_job(job_id=job_id)
    return {"ok": True}


@router.post("/{uid}/import/path")
def import_jobs_from_path(uid: str, body: ImportJobsIn, backend: BackendDep):
    if not body.html_path:
        raise HTTPException(status_code=400, detail="html_path required")
    from gui.services.job_importer import parse_indeed_html_with_stats
    try:
        jobs, stats = parse_indeed_html_with_stats(body.html_path)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    upsert = backend.upsert_jobs(jobs=jobs, source=body.source)
    return {"parsed": len(jobs), "stats": stats, "upsert": upsert}


@router.post("/{uid}/import/upload")
async def import_jobs_from_upload(uid: str, file: UploadFile = File(...),
                                   source: str = Form("indeed"),
                                   backend: BackendDep = None):
    content = await file.read()
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="wb") as tmp:
        tmp.write(content)
        tmp_path = tmp.name
    from gui.services.job_importer import parse_indeed_html_with_stats
    try:
        jobs, stats = parse_indeed_html_with_stats(tmp_path)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        Path(tmp_path).unlink(missing_ok=True)
    upsert = backend.upsert_jobs(jobs=jobs, source=source)
    return {"parsed": len(jobs), "stats": stats, "upsert": upsert}


# ── Scraper endpoints ──────────────────────────────────────────────────────

@router.get("/{uid}/scrape/status", response_model=ScrapeStatusOut)
def scrape_status(uid: str, backend: BackendDep):
    driver = _scraper_state.get("driver")
    has_driver = driver is not None
    awaiting = False
    if has_driver:
        try:
            from gui.services.job_importer import is_human_check_page_source
            awaiting = is_human_check_page_source(driver.page_source)
        except Exception:
            pass
    return ScrapeStatusOut(has_driver=has_driver, awaiting_verification=awaiting)


@router.post("/{uid}/scrape/start")
def scrape_start(uid: str, backend: BackendDep):
    logs: list[str] = []
    all_jobs = backend.list_jobs()
    pending = [j for j in all_jobs if j.get("scrape_status") in ("pending", "failed")]
    if not pending:
        return {"ok": True, "logs": ["No jobs need scraping."]}
    _scraper_state["jobs_for_scrape"] = pending
    from gui.services.job_importer import start_indeed_verification_session
    mapped = [{"Link": j.get("url", j.get("source_url", "")), **j} for j in pending]
    try:
        driver = start_indeed_verification_session(mapped, log=logs.append)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    _scraper_state["driver"] = driver
    return {"ok": True, "logs": logs}


@router.post("/{uid}/scrape/run")
def scrape_run(uid: str, body: ScrapeRunIn, backend: BackendDep):
    driver = _scraper_state.get("driver")
    if driver is None:
        raise HTTPException(status_code=400, detail="No scraper session. Call /scrape/start first.")
    pending = _scraper_state.get("jobs_for_scrape", [])
    if not pending:
        return {"ok": True, "scraped": 0, "failed": 0, "upsert": {}, "logs": ["No jobs to scrape."]}

    logs: list[str] = []
    mapped = [{"Link": j.get("url", j.get("source_url", "")), "source_url": j.get("url", j.get("source_url", "")), **j} for j in pending]
    from gui.services.job_importer import scrape_indeed_descriptions_with_driver, HumanVerificationRequired
    try:
        scraped = scrape_indeed_descriptions_with_driver(
            mapped, driver=driver, wait_seconds=body.wait_seconds,
            log=logs.append, skip_completed=True,
        )
    except HumanVerificationRequired as exc:
        return {"ok": False, "scraped": 0, "failed": 0, "upsert": {},
                "logs": logs + [str(exc)]}

    scraped_count = 0
    failed_count = 0
    for job_data in scraped:
        job_id = str(job_data.get("id", ""))
        desc = str(job_data.get("Description", "") or "").strip()
        apply_url = str(job_data.get("Apply URL", job_data.get("Apply Link", "")) or "").strip()
        attrs = job_data.get("Attributes", [])
        exp_req = job_data.get("experience_required")
        req_exp = job_data.get("requires_experience")
        
        if desc and desc != "FAILED":
            backend.upsert_job_details(
                job_id=job_id, description=desc, apply_url=apply_url,
                attributes=attrs, experience_required=exp_req, requires_experience=req_exp
            )
            scraped_count += 1
        else:
            backend.upsert_job_details(job_id=job_id, description="")
            failed_count += 1

    return {"ok": True, "scraped": scraped_count, "failed": failed_count,
            "upsert": {"scraped": scraped_count, "failed": failed_count}, "logs": logs}


@router.post("/{uid}/scrape/close")
def scrape_close(uid: str):
    driver = _scraper_state.get("driver")
    if driver:
        try:
            driver.quit()
        except Exception:
            pass
    _scraper_state["driver"] = None
    _scraper_state["jobs_for_scrape"] = []
    return {"ok": True}


def _job_out(j: dict) -> JobOut:
    return JobOut(
        id=j["id"], source=j.get("source", ""), source_job_key=j.get("source_job_key", ""),
        title=j.get("title", ""), company=j.get("company", ""),
        location=j.get("location", ""), url=j.get("url", ""),
        salary_raw=j.get("salary_raw", ""), salary=j.get("salary", ""),
        min_pay_yearly=j.get("min_pay_yearly"),
        max_pay_yearly=j.get("max_pay_yearly"),
        job_type=j.get("job_type", ""),
        status=j.get("status", "new"),
        scrape_status=j.get("scrape_status", "pending"),
        relative_time=j.get("relative_time", ""),
        description=j.get("description", ""),
        attributes=j.get("attributes", []),
        posted_at=j.get("posted_at"),
        experience_required=j.get("experience_required"),
        requires_experience=j.get("requires_experience"),
        apply_url=j.get("apply_url", ""),
        source_url=j.get("source_url", j.get("url", "")),
        resume_count=j.get("resume_count", 0),
        created_at=j["created_at"], updated_at=j["updated_at"],
    )
