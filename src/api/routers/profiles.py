"""Profiles router — truth.json CRUD. Single profile, uid kept in path for compat."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from api.deps import BackendDep
from api.schemas import ProfileOut, SaveProfileIn, ValidateProfileOut

router = APIRouter(prefix="/api/profiles", tags=["profiles"])

REQUIRED_KEYS = ["personal_information", "education", "skills", "projects", "experience"]
REQUIRED_PERSONAL = ["name", "phone", "email", "linkedin", "github", "location"]


def _structure_warnings(payload: dict) -> list[str]:
    warnings: list[str] = []
    for key in REQUIRED_KEYS:
        if key not in payload:
            warnings.append(f"Missing top-level key: '{key}'.")
    personal = payload.get("personal_information")
    if not isinstance(personal, dict):
        warnings.append("'personal_information' should be an object.")
    else:
        for key in REQUIRED_PERSONAL:
            value = personal.get(key)
            if not isinstance(value, str) or not value.strip():
                warnings.append(f"'personal_information.{key}' should be a non-empty string.")
    for key in ("education", "projects", "experience"):
        value = payload.get(key)
        if value is not None and not isinstance(value, list):
            warnings.append(f"'{key}' should be an array.")
    skills = payload.get("skills")
    if skills is not None and not isinstance(skills, dict):
        warnings.append("'skills' should be an object of skill categories.")
    return warnings


@router.get("/sample", response_model=ProfileOut)
def get_sample_profile(backend: BackendDep):
    sample = backend.sample_truth_json()
    return ProfileOut(uid="sample", truth_json=sample)


@router.get("/{uid}", response_model=ProfileOut)
def get_profile(uid: str, backend: BackendDep):
    truth = backend.get_truth_json(uid)
    return ProfileOut(uid=uid, truth_json=truth)


@router.put("/{uid}", response_model=ProfileOut)
def save_profile(uid: str, body: SaveProfileIn, backend: BackendDep):
    if not isinstance(body.truth_json, dict):
        raise HTTPException(status_code=400, detail="Profile must be a JSON object.")
    backend.save_truth_json(body.truth_json, uid=uid)
    return ProfileOut(uid=uid, truth_json=body.truth_json)


@router.post("/{uid}/validate", response_model=ValidateProfileOut)
def validate_profile(uid: str, body: SaveProfileIn, backend: BackendDep):
    payload = body.truth_json
    is_dict = isinstance(payload, dict)
    if not is_dict:
        return ValidateProfileOut(
            syntax_ok=True, is_dict=False, warnings=[], error="Top-level must be a JSON object."
        )
    warnings = _structure_warnings(payload)
    return ValidateProfileOut(syntax_ok=True, is_dict=True, warnings=warnings)
