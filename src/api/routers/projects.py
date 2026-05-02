"""Projects router — list, delete, artifacts, preview, download, re-render."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response

from api.deps import BackendDep
from api.schemas import ArtifactOut, ProjectOut, RerenderIn

router = APIRouter(prefix="/api/projects", tags=["projects"])

WORKSPACE_ROOT = Path(__file__).resolve().parents[3]


@router.get("/{uid}", response_model=list[ProjectOut])
def list_projects(uid: str, backend: BackendDep):
    return [_project_out(p) for p in backend.list_projects()]


@router.delete("/{uid}/{project_id}")
def delete_project(uid: str, project_id: str, backend: BackendDep):
    backend.delete_project(project_id=project_id)
    return {"ok": True}


@router.get("/{uid}/{project_id}/artifacts", response_model=list[ArtifactOut])
def list_artifacts(uid: str, project_id: str, backend: BackendDep):
    return [_artifact_out(a) for a in backend.list_artifacts(project_id=project_id)]


@router.get("/{uid}/{project_id}/artifacts/{artifact_id}/download")
def download_artifact(uid: str, project_id: str, artifact_id: int, backend: BackendDep):
    artifacts = backend.list_artifacts(project_id=project_id)
    artifact = next((a for a in artifacts if a["id"] == artifact_id), None)
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")
    file_path = Path(str(artifact.get("storage_path", "")))
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Artifact file not found on disk")
    return FileResponse(
        path=str(file_path),
        filename=str(artifact.get("file_name", file_path.name)),
        media_type=str(artifact.get("mime_type", "application/octet-stream")),
    )


@router.get("/{uid}/{project_id}/artifacts/download-best")
def download_best_artifact(uid: str, project_id: str, backend: BackendDep):
    """Return the best PDF artifact for a project (final > draft, highest iteration)."""
    artifacts = backend.list_artifacts(project_id=project_id)
    pdf_arts = [a for a in artifacts if a.get("mime_type") == "application/pdf"]
    if not pdf_arts:
        raise HTTPException(status_code=404, detail="No PDF artifact found for this project")
    best = pdf_arts[0]  # list_artifacts already sorted by type rank + iteration desc
    file_path = Path(str(best.get("storage_path", "")))
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Artifact file not found on disk")
    return FileResponse(
        path=str(file_path),
        filename=str(best.get("file_name", file_path.name)),
        media_type="application/pdf",
    )


@router.get("/{uid}/{project_id}/artifacts/{artifact_id}/preview")
def preview_artifact(uid: str, project_id: str, artifact_id: int, backend: BackendDep):
    artifacts = backend.list_artifacts(project_id=project_id)
    artifact = next((a for a in artifacts if a["id"] == artifact_id), None)
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")
    file_path = Path(str(artifact.get("storage_path", "")))
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Artifact file not found on disk")
    return Response(
        content=file_path.read_bytes(),
        media_type=str(artifact.get("mime_type", "application/octet-stream")),
        headers={"Content-Disposition": "inline"},
    )


@router.post("/{uid}/{project_id}/rerender")
def rerender_project(uid: str, project_id: str, body: RerenderIn, backend: BackendDep):
    try:
        _rerender_project_with_omissions(backend=backend, project_id=project_id, omissions=body.omissions)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"ok": True}


def _project_out(p: dict) -> ProjectOut:
    return ProjectOut(
        id=p["id"], job_id=p.get("job_id", ""), name=p["name"], status=p["status"],
        job_description=p.get("job_description", ""), error_message=p.get("error_message", ""),
        created_at=p["created_at"], updated_at=p["updated_at"],
    )


def _artifact_out(a: dict) -> ArtifactOut:
    return ArtifactOut(
        id=a["id"], project_id=a["project_id"], artifact_type=a["artifact_type"],
        iteration=a.get("iteration"), storage_path=a["storage_path"],
        file_name=a["file_name"], mime_type=a["mime_type"],
        size_bytes=a.get("size_bytes"), created_at=a["created_at"],
    )


def _rerender_project_with_omissions(*, backend, project_id: str, omissions: dict) -> None:
    artifacts = backend.list_artifacts(project_id=project_id)

    def _find(names):
        by_name = {str(a.get("file_name", "")): a for a in artifacts}
        for n in names:
            if n in by_name:
                return by_name[n]
        return None

    source_json = _find(("final_resume.source.json", "final_resume.json"))
    if source_json is None:
        json_artifacts = [a for a in artifacts if str(a.get("file_name", "")).lower().endswith(".json")]
        json_artifacts.sort(key=lambda a: int(a.get("iteration") or -1), reverse=True)
        source_json = json_artifacts[0] if json_artifacts else None
    if source_json is None:
        raise ValueError("No saved resume JSON found. Re-run generation once to enable fast re-render.")

    source_path = Path(str(source_json.get("storage_path", "")))
    resume_data = json.loads(source_path.read_text(encoding="utf-8"))
    if not isinstance(resume_data, dict):
        raise ValueError("Saved resume JSON is not an object.")

    profile = backend.get_truth_json()
    rendered_profile = json.loads(json.dumps(profile))
    rendered_resume = json.loads(json.dumps(resume_data))

    if omissions.get("no_education"):
        rendered_profile["education"] = []
    if omissions.get("no_photo"):
        rendered_profile.pop("photo", None)
    if omissions.get("no_objective"):
        rendered_resume["objective"] = None
    if omissions.get("no_skills"):
        rendered_resume["skills"] = None
    if omissions.get("no_projects"):
        rendered_resume["projects"] = None
    if omissions.get("no_experience"):
        rendered_resume["experience"] = None
    if omissions.get("no_activities"):
        rendered_resume["activities"] = None
    if omissions.get("no_applying_for"):
        rendered_resume["applying_for"] = None

    pid = backend.get_profile_id()
    work_dir = WORKSPACE_ROOT / ".resumer_gui" / pid / "rerender" / project_id
    if work_dir.exists():
        shutil.rmtree(work_dir, ignore_errors=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    for artifact in artifacts:
        sp = Path(str(artifact.get("storage_path", "")))
        fn = str(artifact.get("file_name", ""))
        if sp.exists() and fn:
            shutil.copy2(sp, work_dir / fn)

    from src.resumer.tools.pdf_tools import render_resume_artifacts
    render_resume_artifacts(profile=rendered_profile, resume_data=rendered_resume,
                            output_dir=work_dir, stem="final_resume")
    backend.replace_project_artifacts_from_local(project_id=project_id, output_dir=work_dir)
    shutil.rmtree(work_dir, ignore_errors=True)
