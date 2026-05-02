"""Batches router — create, manage, run batches + completed resumes."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from api.deps import BackendDep, RunManagerDep
from api.schemas import (
    BatchOut, BatchItemOut, CreateBatchIn, UpdateBatchSettingsIn,
    CreateBatchRunIn, BatchRunOut, CompletedResumeOut, RerenderBatchIn,
)

router = APIRouter(prefix="/api/batches", tags=["batches"])


@router.get("/{uid}", response_model=list[BatchOut])
def list_batches(uid: str, backend: BackendDep):
    return [_batch_out(b) for b in backend.list_batches()]


@router.post("/{uid}", response_model=BatchOut)
def create_batch(uid: str, body: CreateBatchIn, backend: BackendDep):
    prefs = body.preferences or body.global_settings or {}
    batch_id = backend.create_batch(
        name=body.name, job_ids=body.job_ids, preferences=prefs,
    )
    batch = backend.get_batch(batch_id=batch_id)
    if not batch:
        raise HTTPException(status_code=500, detail="Batch created but not found")
    return _batch_out(batch)


@router.get("/{uid}/{batch_id}", response_model=BatchOut)
def get_batch(uid: str, batch_id: str, backend: BackendDep):
    batch = backend.get_batch(batch_id=batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    return _batch_out(batch)


@router.get("/{uid}/{batch_id}/items", response_model=list[BatchItemOut])
def get_batch_items(uid: str, batch_id: str, backend: BackendDep):
    return [_batch_item_out(i) for i in backend.list_batch_items(batch_id=batch_id)]


@router.put("/{uid}/{batch_id}/settings")
def update_batch_settings(uid: str, batch_id: str, body: UpdateBatchSettingsIn, backend: BackendDep):
    backend.update_batch_settings(batch_id=batch_id, global_settings=body.global_settings)
    return {"ok": True}


@router.delete("/{uid}/{batch_id}")
def delete_batch(uid: str, batch_id: str, backend: BackendDep):
    backend.delete_batch(batch_id=batch_id)
    return {"ok": True}


@router.post("/{uid}/{batch_id}/start")
def start_batch(uid: str, batch_id: str, body: UpdateBatchSettingsIn, backend: BackendDep):
    """
    Save generation settings into the batch preferences, then mark it running.
    The RunManager's background _batch_tick_loop picks it up automatically
    and starts launching queued items into parallel slots.
    """
    batch = backend.get_batch(batch_id=batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    if batch.get("status") == "running":
        raise HTTPException(status_code=400, detail="Batch is already running")

    # Save settings (model, iterations, etc.) into preferences_json
    backend.update_batch_settings(batch_id=batch_id, global_settings=body.global_settings)
    # Mark running — the auto-tick loop will start popping queued items
    backend.update_batch_status(batch_id=batch_id, status="running")
    return {"ok": True}


@router.post("/{uid}/{batch_id}/stop")
def stop_batch(uid: str, batch_id: str, backend: BackendDep, rm: RunManagerDep):
    """
    Stop all active controllers for this batch, return non-completed items back
    to the pool (status → new/interested), and mark the batch cancelled.
    No resume possible — create a new batch from the pool instead.
    """
    rm.stop_batch_runs(batch_id, return_to_pool=True)
    return {"ok": True}


@router.post("/{uid}/{batch_id}/return-to-pool")
def return_to_pool(uid: str, batch_id: str, backend: BackendDep):
    """Manually return all non-completed items back to the job pool."""
    count = backend.return_batch_to_pool(batch_id=batch_id)
    backend.update_batch_status(batch_id=batch_id, status="cancelled")
    return {"ok": True, "reset": count}


# backward compat
@router.post("/{uid}/{batch_id}/reset-interested")
def reset_interested(uid: str, batch_id: str, backend: BackendDep):
    count = backend.return_batch_to_pool(batch_id=batch_id)
    return {"ok": True, "reset": count}


@router.get("/{uid}/{batch_id}/run-status")
def get_batch_run_status(uid: str, batch_id: str, rm: RunManagerDep):
    return rm.get_batch_status(batch_id)


@router.websocket("/{uid}/{batch_id}/logs/ws")
async def batch_logs_ws(uid: str, batch_id: str, websocket: WebSocket, rm: RunManagerDep):
    await websocket.accept()
    for entry in rm.get_batch_logs(batch_id):
        await websocket.send_json(entry)
    q = rm.subscribe(f"batch:{batch_id}")
    try:
        while True:
            try:
                payload = q.get_nowait()
            except Exception:
                import asyncio
                await asyncio.sleep(0.2)
                continue
            await websocket.send_json(payload)
    except WebSocketDisconnect:
        pass
    finally:
        rm.unsubscribe(f"batch:{batch_id}", q)


@router.post("/{uid}/{batch_id}/rerender")
def rerender_batch(uid: str, batch_id: str, body: RerenderBatchIn, backend: BackendDep):
    from api.routers.projects import _rerender_project_with_omissions
    errors: list[str] = []
    ok_count = 0
    for pid in body.project_ids:
        try:
            _rerender_project_with_omissions(backend=backend, project_id=pid, omissions=body.omissions)
            ok_count += 1
        except Exception as exc:
            errors.append(f"{pid}: {exc}")
    return {"ok": ok_count, "errors": errors}


# ── Batch Runs endpoints ──────────────────────────────────────────────────

@router.post("/{uid}/{batch_id}/runs", response_model=BatchRunOut)
def create_batch_run(uid: str, batch_id: str, body: CreateBatchRunIn, backend: BackendDep):
    run_id = backend.create_batch_run(
        batch_id=batch_id, model=body.model, api_key_env=body.api_key_env,
        max_iterations=body.max_iterations, parallel_runs=body.parallel_runs,
    )
    run = backend.get_batch_run(run_id=run_id)
    if not run:
        raise HTTPException(status_code=500, detail="Run created but not found")
    return BatchRunOut(**run)


@router.get("/{uid}/{batch_id}/runs")
def list_batch_runs(uid: str, batch_id: str, backend: BackendDep):
    return backend.list_batch_runs(batch_id=batch_id)


# ── Completed Resumes ─────────────────────────────────────────────────────

@router.get("/completed-resumes")
def list_completed_resumes_no_uid(backend: BackendDep):
    return [CompletedResumeOut(**r) for r in backend.list_completed_resumes()]

@router.get("/{uid}/completed-resumes")
def list_completed_resumes(uid: str, backend: BackendDep):
    return backend.list_completed_resumes()


def _batch_out(b: dict) -> BatchOut:
    return BatchOut(
        id=b["id"], name=b["name"], status=b["status"],
        preferences=b.get("preferences", {}),
        global_settings=b.get("global_settings", {}),
        item_count=b.get("item_count", 0),
        completed_count=b.get("completed_count", 0),
        failed_count=b.get("failed_count", 0),
        created_at=b["created_at"], updated_at=b["updated_at"],
    )


def _batch_item_out(i: dict) -> BatchItemOut:
    return BatchItemOut(
        id=i["id"], batch_id=i["batch_id"], job_id=i["job_id"],
        project_id=i.get("project_id", ""), status=i["status"],
        error_message=i.get("error_message", ""),
        title=i.get("title", ""), company=i.get("company", ""),
        location=i.get("location", ""), salary=i.get("salary", ""),
        description=i.get("description", ""),
        description_status=i.get("description_status", "pending"),
        source_url=i.get("source_url", ""),
        apply_url=i.get("apply_url", ""),
        settings_override=i.get("settings_override", {}),
        user_id=i.get("user_id", ""),
        created_at=i["created_at"], updated_at=i["updated_at"],
    )
