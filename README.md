<div align="center">
  <h1 align="center">Resumer</h1>
  <p align="center">
    <strong>Agentic Resume Builder & Intelligent Job Scraping Pipeline</strong>
  </p>
</div>

---

**Resumer** is a powerful, locally-hosted platform designed to supercharge your job hunt. It combines stealth web scraping, NLP-powered data extraction, and agentic AI to automatically tailor high-converting resumes based on specific job descriptions.

## Features

- **Stealth Job Scraper**: Bypass bot-detection to scrape jobs from Indeed, complete with multi-threading, proxy support, and deep-fetching.
- **NLP Enrichment**: Automatically normalize salary bounds and extract hard technical skills using Mistral AI.
- **Agentic Generation**: Leverages CrewAI to analyze job descriptions and inject precise, verbatim keywords into your resume to beat ATS systems.
- **Local-First Backend**: Powered by a lightning-fast FastAPI backend and a local SQLite database (`scraped_jobs`, `profiles`, `projects`).
- **Beautiful UI**: A reactive, dark-mode Next.js frontend with live terminal logs, split-pane job library, and interactive generation controls.

---

## Workflow Architecture

1. **Discovery (Phase 1)**: The scraper executes localized, paginated searches on Indeed to build a basic list of job listings.
2. **Deep Fetch (Phase 2)**: Bypassing Cloudflare, it individually visits each job page to extract the full job description and metadata, saving successfully fetched jobs to the local SQLite database.
3. **Enrichment (Phase 3)**: A Mistral-powered NLP layer parses the raw text to filter out soft-skill noise, leaving structured technical skills and normalized salary bands.
4. **Generation**: You select a target job from the Job Library, and the CrewAI agents draft a tailored resume, injecting the exact required skills into your experience and skills sections.

---

## Quickstart

### Prerequisites

- Python 3.12+ (Using [uv](https://github.com/astral-sh/uv) for lightning-fast dependency management)
- Node.js & [pnpm](https://pnpm.io/)
- API Keys for Mistral (Scraping NLP) and OpenAI/Anthropic (CrewAI Generation)

### 1. Environment Setup

Create a `.env` file in the root directory:

```env
MISTRAL_API_KEY=your_mistral_key_here
OPENAI_API_KEY=your_openai_key_here
```

### 2. Start the Backend (FastAPI)

```bash
# Install dependencies
uv sync

# Start the server (runs on http://localhost:8000)
uv run uvicorn src.api.server:app --reload --port 8000
```

### 3. Start the Frontend (React / Vite)

Open a new terminal window:

```bash
cd frontend

# Install dependencies
pnpm install

# Start the development server
pnpm run dev
```

The UI will be available at **http://localhost:5173**.

---

## User Interface Overview

The frontend is divided into specialized modules accessible via the sidebar:

- **01 / PROFILES**: Manage your base resume, personal details, and core experience.
- **02 / GENERATE**: The core engine. Select a job from the database, configure generation parameters (e.g., omitting photos or specific sections), and watch the AI agents stream their progress in the live terminal.
- **03 / SCRAPE INDEED**: Configure broad searches (by location, job type, salary bounds, date) or paste a direct Indeed link to kick off a background scraping job.
- **04 / JOB LIBRARY**: A split-pane interface to instantly search across thousands of scraped jobs locally, filtering by NLP enrichment status or salary presence.

## CLI Tools

For headless operations or debugging, the platform includes raw Python scripts:

- **Manual Crawling**: Test stealth session bypassing.
  ```bash
  uv run python src/scraping/crawl_indeed.py
  ```
- **DB Management**: Interact directly with the local SQLite backend to purge or verify records.

---

<div align="center">
  <sub>Built locally. Powered by Agents.</sub>
</div>
