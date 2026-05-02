"""
Dependency injection for FastAPI — shared singleton instances.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from gui.services.local_backend import LocalBackend
from api.run_manager import RunManager


@lru_cache(maxsize=1)
def _get_backend_singleton() -> LocalBackend:
    return LocalBackend()


@lru_cache(maxsize=1)
def _get_run_manager_singleton() -> RunManager:
    return RunManager(_get_backend_singleton())


def get_backend() -> LocalBackend:
    return _get_backend_singleton()


def get_run_manager() -> RunManager:
    return _get_run_manager_singleton()


BackendDep = Annotated[LocalBackend, Depends(get_backend)]
RunManagerDep = Annotated[RunManager, Depends(get_run_manager)]
