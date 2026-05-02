"""Users router — backward compat stub returning single profile as a user."""
from __future__ import annotations

from fastapi import APIRouter

from api.deps import BackendDep

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("")
def list_users(backend: BackendDep):
    return backend.list_users()


@router.post("")
def create_user(backend: BackendDep):
    return backend.list_users()[0]


@router.post("/{user_id}/activate")
def activate_user(user_id: str, backend: BackendDep):
    return backend.list_users()[0]
