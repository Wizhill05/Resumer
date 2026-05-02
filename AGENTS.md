# AGENTS.md

Guidance for AI/code agents working in this repository.

## 1) Project summary

Resumer is an AI-assisted resume tailoring app with:

- a **CLI pipeline** (`src/resumer/main.py`) that generates markdown + PDF resume drafts/finals,
- a **Next.js frontend** (`frontend/`) — the primary UI (App Router, TypeScript, Tailwind),
- a **FastAPI backend** (`src/api/main.py`) exposing REST + WebSocket APIs (uvicorn),
- a **local-first data layer** (`src/gui/services/local_backend.py`) using SQLite + filesystem storage (no cloud keys required).
- a **legacy Streamlit GUI** (`src/gui/app.py`) — kept for reference until Next.js UI is fully validated.

## 2) Tech stack

- Python `>=3.12,<3.14`
- Dependency/runtime tool: `uv`
- LLM orchestration: CrewAI
- PDF rendering: Playwright (Chromium) + markdown/jinja2 template flow
- **Backend API**: FastAPI + uvicorn (`src/api/`)
- **Frontend**: Next.js 16 + TypeScript + Tailwind CSS (`frontend/`)
- Legacy GUI: Streamlit + `streamlit-ace` (`src/gui/app.py`)
- Local persistence:
  - SQLite DB at `data/resumer.db`
  - Artifacts at `data/artifacts/<user_id>/<project_id>/...`

## 3) Local setup and run

1. Install Python deps:
   - `uv sync`
2. Install Playwright browser:
   - `uv run playwright install chromium`
3. **Run FastAPI backend** (terminal 1):
   - `uv run uvicorn src.api.main:app --reload --port 8000`
4. **Run Next.js frontend** (terminal 2):
   - `cd frontend && npm run dev`
   - Opens at http://localhost:3000
5. Legacy Streamlit (optional):
   - `uv run streamlit run src/gui/app.py`
6. Run CLI directly:
   - `uv run python src/resumer/main.py`

## 4) Environment variables

No backend/cloud keys are required.

LLM keys are still required for generation depending on selected model:

- `MISTRAL_API_KEY`
- `GEMINI_KEY`
- `OPENROUTER_API_KEY`
- (other provider keys if adding new model providers)

Loaded from `.env.local` by app/CLI.

## 5) Important architecture details

### 5.1 API orchestration flow

- `src/api/run_manager.py` manages `ResumeRunController` instances (single + batch).
- `RunManager` runs a background polling thread (0.5s interval) that:
  - calls `controller.poll()` to drain subprocess stdout/stderr,
  - broadcasts new `LogEntry` items to WebSocket subscribers,
  - syncs finished runs by calling `backend.replace_project_artifacts_from_local()`.
- Pipeline writes intermediate outputs under `outputs/<run_label>/...`.
- After sync, the `outputs/<run_label>` folder is removed.
- Frontend receives real-time logs via WebSocket at `/api/runs/{uid}/logs/ws`.

### 5.1b Legacy Streamlit flow

- `src/gui/services/runner.py` runs `src/resumer/main.py` in a subprocess.
- Streamlit polls and syncs artifacts on each page rerun.

### 5.2 Local backend schema

`src/gui/services/local_backend.py` manages:

- `users`
- `profiles` (`truth_json` text JSON payload)
- `projects`
- `project_artifacts`

Behavior notes:

- First run auto-creates user: **Default Local User**
- Empty/new profile seeds from `input/sampletruth.json`
- Project deletion removes both DB rows and artifact files

### 5.3 Resume rendering pipeline

- Jinja template: `template/base_resume.jinja2`
- CSS: `template/template.css`
- Renderer: `makepdf.py`

`makepdf.py` includes important asset behavior:

- local font/image path resolution to `file://` URIs,
- wait for images/fonts before PDF capture to avoid partial image renders.

### 5.4 JSON editor

Next.js Master Profile page uses **Monaco Editor** (`@monaco-editor/react`) with:

- JSON syntax highlighting + error squiggles,
- validation via `POST /api/profiles/{uid}/validate`,
- path inspector (dot-path + bracket notation),
- unified diff preview (using `diff` npm package),
- save with confirmation checkbox.

Legacy Streamlit tab uses `streamlit-ace` (Ace editor) with `st.text_area` fallback.

## 6) Conventions and constraints for changes

1. **Keep it local-first** by default.
   - Do not introduce required cloud dependencies/keys for core flow.
2. Preserve current file layout contracts:
   - DB: `data/resumer.db`
   - Artifacts: `data/artifacts/...`
3. Avoid breaking CLI flags in `src/resumer/main.py`.
4. Reuse existing helpers rather than duplicating path/sync logic.
5. Keep project description text plain in output (no unintended markdown emphasis bleed).
6. Ensure local photo/font support continues to work in generated PDFs.

## 7) Files and folders to know

**Backend (Python)**
- `src/api/main.py` — FastAPI app entry point
- `src/api/run_manager.py` — subprocess controller manager + WebSocket broadcaster
- `src/api/schemas.py` — Pydantic request/response models
- `src/api/routers/` — endpoint routers: users, profiles, projects, runs, jobs, batches
- `src/api/deps.py` — FastAPI dependency injection
- `src/gui/services/local_backend.py` — SQLite/filesystem backend (shared by API + legacy Streamlit)
- `src/gui/services/runner.py` — `ResumeRunController` (subprocess wrapper)
- `src/gui/services/job_importer.py` — Indeed HTML parser + Selenium scraper
- `src/resumer/main.py` — resume generation CLI + normalization logic
- `src/resumer/tools/pdf_tools.py` — PDF tools used by CrewAI loop
- `makepdf.py` — HTML/CSS to PDF rendering
- `template/base_resume.jinja2` — resume Jinja2 template
- `template/template.css` — template styles
- `input/sampletruth.json` — default profile seed

**Frontend (Next.js)**
- `frontend/src/app/` — App Router pages: studio, profile, jobs, batch, tracker
- `frontend/src/lib/api.ts` — typed API client
- `frontend/src/lib/types.ts` — TypeScript interfaces
- `frontend/src/lib/ws.ts` — WebSocket hook for real-time log streaming
- `frontend/src/lib/user-context.tsx` — active user/profile React context
- `frontend/src/components/layout/` — Sidebar + Header
- `frontend/src/components/ui/` — StatusBadge, LogViewer

**Legacy**
- `src/gui/app.py` — Streamlit UI (kept for reference)

## 8) Validation expectations

There is no formal test suite yet. Minimum checks after non-trivial changes:

1. `uv sync`
2. `uv run python -m compileall src makepdf.py`
3. API smoke import:
   - `uv run python -c "import sys; sys.path.insert(0,'src'); from api.main import app; print(app.title)"`
4. Frontend build:
   - `cd frontend && npm run build`
5. If touching rendering, run:
   - `uv run python makepdf.py --md template\\template.md --css template\\template.css -o output\\check.pdf`

## 9) Git hygiene

- `data/`, `outputs/`, `.resumer_gui/`, and virtual env artifacts are generated runtime data; do not commit them.
- Keep changes scoped; avoid unrelated refactors.
