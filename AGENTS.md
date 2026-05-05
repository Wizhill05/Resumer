# Agent Context & Codebase Guide

This document provides architectural context, setup instructions, and guidelines for AI agents working on the Resumer codebase. If you are an AI assistant tasked with modifying this project, read this first.

## 1. Architecture Overview

Resumer is a local-first platform for job scraping, NLP enrichment, and agentic resume generation. 

- **Backend**: Python 3.12+ powered by FastAPI. Dependency management is handled strictly by `uv`.
- **Frontend**: React + TypeScript (Vite).
- **Database**: Local SQLite. Raw SQL queries are used (no heavy ORMs) via the `local_backend.py` service.
- **AI Integration**:
  - Mistral AI is used for structured NLP tasks (salary normalization, technical skill extraction).
  - CrewAI (OpenAI/Anthropic) is used for the complex resume drafting and tailoring logic.

## 2. Codebase Structure

- `/src/api/` - FastAPI backend application. `server.py` contains the route definitions. `scrape_service.py` contains the threaded background scraper logic.
- `/src/scraping/` - Raw scraping scripts. `crawl_indeed.py` relies on `scrapling.fetchers.StealthySession` to bypass Cloudflare.
- `/src/agents/` - CrewAI task definitions and agent logic for parsing job descriptions and tailoring resumes.
- `/src/gui/services/local_backend.py` - Centralized SQLite database operations.
- `/frontend/` - The React frontend application. Uses standard CSS (`index.css`) rather than Tailwind.

## 3. The Scraping Pipeline (Important Context)

The scraping architecture in `scrape_service.py` executes in three distinct phases. 

- **Phase 1 (Search Crawl)**: Scrapes the search results page to gather basic job IDs and metadata. This phase does **not** persist to the database preemptively.
- **Phase 2 (Deep Fetch)**: Iterates over the gathered jobs and directly requests the `viewjob` page to get the full description. 
  - *Direct URL Bypass*: If a user provides a single job link, the pipeline skips Phase 1, creates a mock job entry, and extracts all metadata (title, company, etc.) directly from the `viewjob` page during Phase 2.
  - *Persistence*: Jobs are only persisted to SQLite (`upsert_scraped_job`) *after* successfully completing Phase 2 to avoid cluttering the DB with 404s.
- **Phase 3 (NLP Enrichment)**: Passes raw text attributes to Mistral to extract `technical_skills` and parse salary into `min_salary_inr` and `max_salary_inr`. Errors are caught gracefully, leaving the job in the DB without skills rather than failing.

## 4. Local Database Schema

The SQLite schema is initialized in `local_backend.py`. Key tables:
- `scraped_jobs`: Stores the output of the scraping pipeline. Primary key is the Indeed `jk` (Job Key).
- `profiles`: Stores the user's base resume and preferences in JSON blobs.
- `projects`: Represents a specific application target (mapped to a job description).
- `project_artifacts`: Tracks the iterations of generated resumes for a specific project.

## 5. Development Guidelines for Agents

1. **Specific Tools**: Use the most specific tool available (e.g., `replace_file_content` instead of bash commands for file editing).
2. **Design Philosophy**: The UI should look extremely premium. Use custom CSS in `index.css` to build clean, dark-mode, glassmorphic UI components. Avoid generic styles. 
3. **No Emojis**: Do not use emojis in user-facing documentation (like READMEs) unless explicitly requested.
4. **Environment Execution**:
   - Backend: `uv run uvicorn src.api.server:app --reload --port 8000`
   - Frontend: `cd frontend && pnpm run dev`
5. **Data Management**: Never use `cat` to create or append files. Use built-in file writing tools. When querying the database for debugging, use `uv run python` snippets.
