"""
Runs router — start/stop single pipeline run, status polling, WebSocket log stream.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from api.deps import BackendDep, RunManagerDep
from api.run_manager import _profile_temp_path
from api.schemas import RunStatusOut, StartRunIn, LogEntryOut

router = APIRouter(prefix="/api/runs", tags=["runs"])

WORKSPACE_ROOT = Path(__file__).resolve().parents[3]


@router.post("/{uid}/start")
def start_run(uid: str, body: StartRunIn, backend: BackendDep, rm: RunManagerDep):
    if rm.main_controller.is_running():
        raise HTTPException(status_code=409, detail="A run is already in progress.")

    if body.jd_text:
        jd_text = body.jd_text.strip()
    elif body.jd_path:
        jd_file = Path(body.jd_path)
        if not jd_file.is_absolute():
            jd_file = WORKSPACE_ROOT / jd_file
        if not jd_file.exists():
            raise HTTPException(status_code=400, detail=f"JD file not found: {jd_file}")
        jd_text = jd_file.read_text(encoding="utf-8").strip()
    else:
        raise HTTPException(status_code=400, detail="Provide jd_text or jd_path.")

    if not jd_text:
        raise HTTPException(status_code=400, detail="Job description is empty.")

    truth = backend.get_truth_json(uid)
    profile_path = _profile_temp_path(uid)
    profile_path.write_text(json.dumps(truth, indent=2, ensure_ascii=False), encoding="utf-8")

    run_name = body.run_name.strip() or "manual_run"
    project_id = backend.create_project(
        name=run_name, job_description=jd_text, job_id=body.job_id or None,
    )

    pid = backend.get_profile_id()
    jd_tmp = WORKSPACE_ROOT / ".resumer_gui" / pid
    jd_tmp.mkdir(parents=True, exist_ok=True)
    jd_file_path = jd_tmp / f"{project_id}.jd.txt"
    jd_file_path.write_text(jd_text, encoding="utf-8")

    local_run_label = f"{run_name}_{project_id[:8]}"
    try:
        rm.start_main_run(
            jd_path=str(jd_file_path), data_path=str(profile_path),
            max_iterations=body.max_iterations, job_label=local_run_label,
            model=body.model, api_key_env=body.api_key_env,
            omissions=body.omissions, project_id=project_id, project_name=run_name,
        )
    except Exception as exc:
        backend.update_project_status(project_id=project_id, status="failed", error_message=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))

    return {"project_id": project_id, "run_name": run_name}


@router.post("/{uid}/stop")
def stop_run(uid: str, rm: RunManagerDep):
    rm.stop_main_run()
    return {"ok": True}


@router.get("/{uid}/status", response_model=RunStatusOut)
def get_status(uid: str, rm: RunManagerDep):
    return RunStatusOut(**rm.get_main_status())


@router.get("/{uid}/logs", response_model=list[LogEntryOut])
def get_logs(uid: str, rm: RunManagerDep):
    return [LogEntryOut(**e) for e in rm.get_main_logs()]


@router.websocket("/{uid}/logs/ws")
async def logs_ws(uid: str, websocket: WebSocket, rm: RunManagerDep):
    await websocket.accept()
    for entry in rm.get_main_logs():
        await websocket.send_json(entry)

    q = rm.subscribe("main")
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
        rm.unsubscribe("main", q)
