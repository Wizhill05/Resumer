# Resumer Setup and Command Guide

This project has multiple entry points. Use them in this order of importance.

## 0. One-time setup

```powershell
# from repo root
uv sync
cd frontend
pnpm install
cd ..
```

If Playwright browser binaries are missing for PDF/render flows:

```powershell
uv run playwright install chromium
```

## 1. Main frontend (Vite) — highest priority

```powershell
cd frontend
pnpm run dev
```

Frontend URL: `http://localhost:5173`

## 2. Main backend API (FastAPI + Uvicorn) — highest priority

```powershell
uv run uvicorn src.api.server:app --reload --host 0.0.0.0 --port 8000
```

API base URL: `http://localhost:8000`

## Run frontend + backend with one command

PowerShell:

```powershell
.\start-dev.ps1
```

Bash:

```bash
bash ./start-dev.sh
```

## 3. Resume generator CLI (CrewAI flow)

```powershell
uv run python src\resumer\main.py --job-label "target_company"
```

Useful options:

```powershell
uv run python src\resumer\main.py --jd input\job_description.txt --data input\truth.json --max-iterations 5
```

## 4. Indeed scraper CLI (3-phase pipeline)

```powershell
uv run python src\scraping\crawl_indeed.py
```

Writes scraped output under `src\scraping\output\`.

## 4b. LinkedIn scraper CLI (3-phase pipeline)

```powershell
uv run python src\linkedin_scraping\crawl_linkedin.py
```

Build a fresh LinkedIn search URL from filters (role/location/experience/work type/date/salary tag):

```powershell
uv run python src\linkedin_scraping\crawl_linkedin.py --keywords "Software Engineer" --location "India" --geo-id 102713980 --experience-levels 1,2 --work-types 2,1 --posted-within 7d --salary-tag 5 --target-count 50
```

Print the resolved URL without scraping:

```powershell
uv run python src\linkedin_scraping\crawl_linkedin.py --keywords "Backend Engineer" --location "Bengaluru" --print-url
```

Fully formed URL can still be overridden directly:

```powershell
uv run python src\linkedin_scraping\crawl_linkedin.py --target-url "https://www.linkedin.com/jobs/search/?alertAction=viewjobs&currentJobId=4415434087&distance=25&f_E=1&f_TPR=a1778869397-&f_WT=2%2C1&geoId=102713980&keywords=Software%20Engineer&location=India&origin=JOB_SEARCH_PAGE_JOB_FILTER&sortBy=R&spellCorrectionEnabled=true" --target-count 50
```

Writes scraped output under `src\linkedin_scraping\output\`.

## 5. Auto-apply CLI (currently not reliable)

Start with dry-run first:

```powershell
uv run python src\autoApply\auto_apply_indeed.py --dry-run --limit 5
```

Real run example:

```powershell
uv run python src\autoApply\auto_apply_indeed.py --limit 5 --button-timeout-ms 20000 --page-timeout-ms 45000
```

## 6. Legacy GUI (Streamlit)

```powershell
uv run streamlit run src\gui\app.py
```

## 7. Scraping debug/support scripts

Fetch raw Indeed HTML:

```powershell
uv run python src\scraping\fetch_indeed_html.py
```

Parse saved HTML to JSON:

```powershell
uv run python src\scraping\parse_indeed_html.py
```

Find/inspect Indeed `sc` filter codes:

```powershell
uv run python src\scraping\find_sc.py
```

Run URL builder script-tests:

```powershell
uv run python src\scraping\test_indeed_url_builder.py
```

## 8. Browser profile helper (for manual login/session prep)

```powershell
uv run python src\otherScripts\open_chrome_profile.py --browser chrome --url "https://in.indeed.com/account/login"
```

## 9. Standalone PDF utility

```powershell
uv run python makepdf.py --md template\template.md --css template\template.css -o output\resume.pdf
```
