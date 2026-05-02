"""
Resumer FastAPI application entry point.

Run with:
    uv run uvicorn src.api.main:app --reload --port 8000
"""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root on sys.path for imports
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
for _p in (_PROJECT_ROOT, _PROJECT_ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from dotenv import load_dotenv

load_dotenv(_PROJECT_ROOT / ".env.local", override=False)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routers import users, profiles, projects, runs, jobs, batches

app = FastAPI(
    title="Resumer API",
    description="Local-first resume generation API backed by SQLite + CrewAI pipeline.",
    version="1.0.0",
)

# Allow Next.js dev server and production build
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(users.router)
app.include_router(profiles.router)
app.include_router(projects.router)
app.include_router(runs.router)
app.include_router(jobs.router)
app.include_router(batches.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/models")
def list_model_presets():
    from api.run_manager import MODEL_PRESETS
    return [
        {"label": label, "model": model, "api_key_env": key_env}
        for label, (model, key_env) in MODEL_PRESETS.items()
    ]
