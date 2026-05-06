from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal


PROJECT_ROOT = Path(__file__).resolve().parents[2]
AUTO_APPLY_DIR = Path(__file__).resolve().parent
DEFAULT_PROFILE_DIR = PROJECT_ROOT / "chrome_profile"
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "resumer.db"
DEFAULT_TRUTH_PATH = AUTO_APPLY_DIR / "truth.json"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@dataclass(frozen=True, slots=True)
class ReadyJob:
    id: str
    title: str
    company: str
    link: str
    project_id: str
    project_status: str


@dataclass(slots=True)
class ApplyActionResult:
    button_kind: str = "none"
    direct_apply_attempted: bool = False
    direct_apply_url: str = ""
    direct_apply_type: str = ""
    click_attempted: bool = False
    reacted: bool = False
    reaction: str = ""
    before_url: str = ""
    after_url: str = ""
    error: str = ""


@dataclass(slots=True)
class ApplyFlowResult:
    status: str = "not_started"
    detail: str = ""
    steps: int = 0
    resume_uploaded: bool = False
    answers_applied: int = 0


INDEED_APPLY_SELECTORS = (
    "#indeedApplyButton",
    '[data-testid="indeedApplyButton-test"]',
    '[data-testid="indeed-apply-widget"] button',
    'button[aria-label*="Apply with Indeed" i]',
    'button[aria-label*="Apply on Indeed" i]',
    'button:has-text("Apply with Indeed")',
    'button:has-text("Apply on Indeed")',
    'a:has-text("Apply with Indeed")',
    'a:has-text("Apply on Indeed")',
)

COMPANY_APPLY_SELECTORS = (
    'button:has-text("Apply on company site")',
    'a:has-text("Apply on company site")',
    'button[aria-label*="Apply on company site" i]',
    'a[aria-label*="Apply on company site" i]',
)

REACTION_SELECTORS = (
    'iframe[src*="indeedapply" i]',
    'iframe[name*="indeedapply" i]',
    '[id*="indeedApplyModal" i]',
    '[id*="ia-container" i]',
    '[data-testid*="indeedApply" i]:not([data-testid="indeedApplyButton-test"])',
    'text=/Continue|Review your application|Submit your application|Contact information|Application step/i',
)

RESUME_OPTIONS_SELECTORS = (
    'button:has-text("CV options")',
    'button:has-text("Resume options")',
    'text=/CV options/i',
    'text=/Resume options/i',
)

UPLOAD_DIFFERENT_FILE_SELECTORS = (
    'button:has-text("Upload a different file")',
    'label:has-text("Upload a different file")',
    'text=/Upload a different file/i',
)

FILE_CHOOSER_TRIGGER_SELECTORS = (
    *UPLOAD_DIFFERENT_FILE_SELECTORS,
    'button:has-text("Upload file")',
    'button:has-text("Upload resume")',
    'text=/Browse|Choose file|Select file/i',
)

PROGRESS_BUTTON_SELECTORS = (
    'button:has-text("Continue")',
    'button:has-text("Next")',
    'button:has-text("Review")',
    'button:has-text("Submit")',
    'button:has-text("Apply")',
    'button[type="submit"]',
    'input[type="submit"]',
)

SUBMITTED_SELECTORS = (
    'text=/Application submitted/i',
    'text=/Your application has been submitted/i',
    'text=/Thanks for applying/i',
    'text=/Thank you for applying/i',
)

ANSWER_MAPPING_KEYS = (
    "answers",
    "question_answers",
    "qa",
    "indeed_answers",
    "truth",
    "facts",
)

RESUME_PATH_COLUMN_CANDIDATES = (
    "resume_path",
    "file_path",
    "artifact_path",
    "local_path",
    "output_path",
    "path",
    "resume_file",
    "file",
)

RESUME_MARKER_COLUMN_CANDIDATES = (
    "artifact_type",
    "type",
    "kind",
    "category",
    "name",
    "label",
)

ORDER_COLUMN_CANDIDATES = (
    "created_at",
    "updated_at",
    "id",
    "version",
    "iteration",
)

IDENTIFIER_COLUMN_CANDIDATES = (
    "project_id",
    "id",
    "job_id",
    "jk",
    "scraped_job_id",
)


def _wait_for_indeed_apply_ready(page: Any, timeout_ms: int) -> bool:
    try:
        return bool(
            page.wait_for_function(
                """
                () => {
                    const button = document.querySelector(
                        '#indeedApplyButton, [data-testid="indeedApplyButton-test"]'
                    );
                    const widget = document.querySelector('[data-testid="indeed-apply-widget"]');
                    if (!button || button.disabled || button.getAttribute("aria-disabled") === "true") {
                        return false;
                    }
                    if (widget) {
                        return widget.getAttribute("data-click-handler") === "attached";
                    }
                    if (button.dataset.clickHandler === "attached") {
                        return true;
                    }
                    return Boolean(
                        window._initialData?.indeedApplyButtonContainer?.indeedApplyButtonAttributes?.jk
                    );
                }
                """,
                timeout=timeout_ms,
            )
        )
    except Exception:
        return False


def get_ready_jobs(
    *,
    db_path: Path = DEFAULT_DB_PATH,
    require_completed_project: bool = True,
    limit: int | None = None,
) -> list[ReadyJob]:
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    where = [
        "COALESCE(sj.applied, 0) = 0",
        "TRIM(COALESCE(sj.project_id, '')) != ''",
        "TRIM(COALESCE(sj.link, '')) != ''",
    ]
    params: list[Any] = []
    if require_completed_project:
        where.append("p.status = ?")
        params.append("completed")

    query = f"""
        SELECT
            sj.id,
            sj.title,
            sj.company,
            sj.link,
            sj.project_id,
            p.status AS project_status,
            sj.created_at
        FROM scraped_jobs sj
        JOIN projects p ON p.id = sj.project_id
        WHERE {" AND ".join(where)}
        ORDER BY sj.created_at ASC
    """
    if limit is not None:
        query += " LIMIT ?"
        params.append(limit)

    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(query, params).fetchall()

    return [
        ReadyJob(
            id=str(row["id"]),
            title=str(row["title"] or ""),
            company=str(row["company"] or ""),
            link=str(row["link"] or ""),
            project_id=str(row["project_id"] or ""),
            project_status=str(row["project_status"] or ""),
        )
        for row in rows
    ]


def _first_visible(page: Any, selectors: tuple[str, ...]) -> Any | None:
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if locator.count() and locator.is_visible(timeout=500):
                return locator
        except Exception:
            continue
    return None


def _wait_for_apply_button(page: Any, timeout_ms: int) -> tuple[str, Any | None]:
    deadline = time.monotonic() + (timeout_ms / 1000)
    while time.monotonic() < deadline:
        indeed_button = _first_visible(page, INDEED_APPLY_SELECTORS)
        if indeed_button is not None:
            remaining_ms = max(500, int((deadline - time.monotonic()) * 1000))
            _wait_for_indeed_apply_ready(page, min(remaining_ms, 5_000))
            return "indeed", indeed_button

        company_button = _first_visible(page, COMPANY_APPLY_SELECTORS)
        if company_button is not None:
            return "company", company_button

        page.wait_for_timeout(500)

    return "none", None


def _has_apply_reaction(page: Any, before_url: str) -> tuple[bool, str]:
    try:
        if page.url != before_url:
            return True, f"url changed: {page.url}"
    except Exception:
        pass

    for selector in REACTION_SELECTORS:
        try:
            locator = page.locator(selector).first
            if locator.count() and locator.is_visible(timeout=500):
                return True, f"visible selector: {selector}"
        except Exception:
            continue

    try:
        if len(page.context.pages) > 1:
            urls = [p.url for p in page.context.pages]
            return True, f"new page opened: {urls[-1]}"
    except Exception:
        pass

    return False, ""


def _open_direct_apply_url(page: Any, *, after_click_ms: int) -> ApplyActionResult:
    result = ApplyActionResult(before_url=page.url)
    direct = page.evaluate(
        """
        async () => {
            const data = window._initialData || {};
            const container = data.indeedApplyButtonContainer || {};
            const button = container.indeedApplyButtonAttributes || {};
            const bootstrap = container.indeedApplyBootStrapAttributes || {};

            if (!button.jk || !container.indeedApplyBaseUrl) {
                return { ok: false, error: "Indeed apply config not found on page." };
            }

            const lower = (obj) => Object.fromEntries(
                Object.entries(obj || {}).map(([key, value]) => [key.toLowerCase(), value])
            );
            const truthy = (value) => ["true", "1"].includes(String(value || "").toLowerCase());
            const fromLower = (obj, key) => lower(obj)[key.toLowerCase()];
            const cookieValue = (name) => {
                const prefix = `${name}=`;
                const part = document.cookie.split("; ").find((item) => item.startsWith(prefix));
                return part ? decodeURIComponent(part.slice(prefix.length)) : "";
            };
            const pruneEmpty = (obj) => Object.fromEntries(
                Object.entries(obj).filter(([, value]) => value !== undefined && value !== null && value !== "")
            );

            const n = lower(button);
            const o = lower(bootstrap);
            const buttonParams = pruneEmpty({
                iip: true,
                isGql: truthy(n.isgql) || truthy(o.isgql),
                isApi: truthy(n.isapi) || truthy(o.isapi),
                source: o.source,
                hl: o.hl,
                co: o.co,
                spn: truthy(o.spn),
                locale: n.locale || o.locale,
                name: n.name || o.name,
                apiToken: n.apitoken,
                jobTitle: n.jobtitle,
                jobId: n.jobid,
                jobLocation: n.joblocation,
                jobCompany: n.jobcompanyname,
                jobUrl: n.joburl,
                jobMeta: n.jobmeta,
                jobCountry: n.jobcountry || o.jobcountry,
                jobFeedId: n.jobfeedid,
                questions: n.questions,
                email: n.email,
                postUrl: n.posturl,
                coverletter: n.coverletter,
                phone: n.phone,
                resume: n.resume,
                advNum: n.advnum,
                pingbackUrl: n.pingbackurl,
                finishAppUrl: n.finishappurl,
                jk: n.jk,
                continueUrl: n.continueurl,
                recentsearchquery: n.recentsearchquery,
                returnToJobSearchUrl: n.returntojobsearchurl || o.returntojobsearchurl,
                exitUrl: n.exiturl,
                iaMeta: n.iameta || o.iameta,
                partnerMeta: n.partnermeta || o.partnermeta,
                partnerSa: n.partnersa,
                partnerApiToken: n.partnerapitoken,
                newTab: truthy(n.newtab),
                noButtonUI: truthy(n.nobuttonui),
                resumeFieldsRequired: n.resumefieldsrequired,
                resumeFieldsOptional: n.resumefieldsoptional,
                clientmeta: n.clientmeta,
                jobResultTrackingKey: o.jobresulttrackingkey,
                onAppliedStatus: n.onappliedstatus,
                onReady: n.onready,
                onClick: n.onclick,
                onFailure: n.onfailure,
                href: n.href,
                from: n.from,
                buttonLoadMethod: truthy(n.isgql) || truthy(o.isgql) ? "BUTTON_SDK_CCS" : "BUTTON_SDK",
            });

            const query = new URLSearchParams(pruneEmpty({
                tk: bootstrap.tk,
                vjtk: bootstrap.vjtk,
                mobtk: bootstrap.mobtk,
                mobvjtk: bootstrap.mobvjtk,
                gtk: bootstrap.gtk,
                rojc: bootstrap.rojc,
                rsjc: bootstrap.rsjc,
                ctk: cookieValue("CTK") || "NO_CTK",
                jk: button.jk || "NO_JK",
            }));
            const envUrl = `https://apply.indeed.com/api/v1/env?${query.toString()}`;
            const response = await fetch(envUrl, {
                method: "POST",
                body: JSON.stringify(buttonParams),
                credentials: "include",
                headers: { "Content-Type": "text/plain", "referer": document.referrer },
                referrerPolicy: "origin",
            });
            const payload = await response.json();
            if (!response.ok || payload.errorCode) {
                return {
                    ok: false,
                    envUrl,
                    status: response.status,
                    error: payload.errorCode || `env request failed with ${response.status}`,
                };
            }

            const env = payload.result || {};
            const addRuntimeParams = (url) => {
                const out = new URL(url);
                for (const [key, value] of Object.entries(env.applyUrlConfig || {})) {
                    if (value !== undefined && value !== null) out.searchParams.append(key, String(value));
                }
                out.searchParams.append("href", window.location.href);
                out.searchParams.append("preload", document.getElementById("SA_PRELOAD_ASSETS_IFRAME_ID") ? "1" : "0");
                out.searchParams.append("referrer", window.location.origin);
                out.searchParams.append("ms", String(Date.now()));
                out.searchParams.append("iststd", "1");
                for (const key of ["referrer", "href", "continueUrl"]) {
                    if (out.toString().length > 3500) out.searchParams.delete(key);
                }
                return out.toString();
            };

            const type = env.saResumeApplyType || "";
            if (type === "GET") {
                const applyUrl = addRuntimeParams(env.applyUrl);
                window.location.assign(applyUrl);
                return { ok: true, type, applyUrl, envUrl };
            }
            if (type === "SHORT_URL") {
                const applyUrl = addRuntimeParams(env.applyUrl);
                window.location.assign(applyUrl);
                return { ok: true, type, applyUrl, envUrl };
            }
            if (type === "POST") {
                const form = document.createElement("form");
                form.action = env.applyUrl;
                form.target = env.formStyle === "LETTERBOX" ? "_top" : "_blank";
                form.method = "POST";
                const params = {
                    ...(env.applyUrlConfig || {}),
                    href: window.location.href,
                    preload: document.getElementById("SA_PRELOAD_ASSETS_IFRAME_ID") ? "1" : "0",
                    referrer: window.location.origin,
                    ms: String(Date.now()),
                    iststd: "1",
                };
                for (const [key, value] of Object.entries(params)) {
                    if (value === undefined || value === null) continue;
                    const input = document.createElement("input");
                    input.type = "hidden";
                    input.name = key;
                    input.value = String(value);
                    form.appendChild(input);
                }
                document.body.appendChild(form);
                form.submit();
                return { ok: true, type, applyUrl: env.applyUrl, envUrl };
            }
            return { ok: false, type, envUrl, error: `Unsupported apply type: ${type}` };
        }
        """
    )

    if not isinstance(direct, dict):
        result.error = "Direct apply extraction returned an unexpected result."
        return result

    result.direct_apply_url = str(direct.get("applyUrl") or "")
    result.direct_apply_type = str(direct.get("type") or "")
    if direct.get("ok"):
        result.direct_apply_attempted = True
        page.wait_for_timeout(after_click_ms)
        result.after_url = page.url
        result.reacted = True
        result.reaction = f"direct {result.direct_apply_type} apply URL"
    else:
        result.error = str(direct.get("error") or "Direct apply URL was not available.")
    return result


def _click_locator(locator: Any) -> None:
    locator.scroll_into_view_if_needed(timeout=5_000)
    locator.click(timeout=10_000, delay=100)


def _mouse_click_locator(page: Any, locator: Any) -> None:
    locator.scroll_into_view_if_needed(timeout=5_000)
    box = locator.bounding_box(timeout=5_000)
    if not box:
        raise RuntimeError("Apply button has no clickable bounding box.")
    x = box["x"] + box["width"] / 2
    y = box["y"] + box["height"] / 2
    page.mouse.move(x, y)
    page.wait_for_timeout(250)
    try:
        page.mouse.down()
        page.wait_for_timeout(100)
    finally:
        page.mouse.up()
    page.wait_for_timeout(100)
    page.mouse.move(x + 12, y + 12)


def _js_click_locator(locator: Any) -> None:
    locator.evaluate(
        """
        element => {
            element.dispatchEvent(new PointerEvent("pointerup", { bubbles: true, cancelable: true }));
            element.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, cancelable: true }));
            element.click();
        }
        """
    )


def click_indeed_apply(page: Any, *, button_timeout_ms: int, after_click_ms: int) -> ApplyActionResult:
    result = ApplyActionResult()
    try:
        kind, button = _wait_for_apply_button(page, button_timeout_ms)
        result.button_kind = kind
        result.before_url = page.url

        if kind != "indeed" or button is None:
            return result

        direct_result = _open_direct_apply_url(page, after_click_ms=after_click_ms)
        direct_result.button_kind = kind
        if direct_result.direct_apply_attempted:
            return direct_result

        click_errors: list[str] = []
        for click_name, click_fn in (
            ("locator", lambda: _click_locator(button)),
            ("mouse", lambda: _mouse_click_locator(page, button)),
            ("js", lambda: _js_click_locator(button)),
        ):
            try:
                if click_name != "js":
                    _wait_for_indeed_apply_ready(page, 5_000)
                click_fn()
                result.click_attempted = True
                page.wait_for_timeout(after_click_ms)
                reacted, reaction = _has_apply_reaction(page, result.before_url)
                if reacted:
                    result.reacted = True
                    result.reaction = f"{click_name} click: {reaction}"
                    break
            except Exception as exc:
                click_errors.append(f"{click_name}: {exc}")
            finally:
                try:
                    page.mouse.up()
                except Exception:
                    pass

        result.after_url = page.url
        if result.click_attempted and not result.reacted:
            errors = " | ".join(click_errors)
            result.error = (
                f"Direct apply failed: {direct_result.error}. "
                f"No page reaction after click attempts. Errors: {errors}"
            )
        return result
    except Exception as exc:
        result.error = str(exc)
        return result


def _normalized(text: Any) -> str:
    return " ".join(str(text or "").strip().lower().replace("_", " ").split())


def _string_answer(value: Any) -> str:
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value).strip()


def load_truth_data(truth_path: Path) -> dict[str, Any]:
    if not truth_path.exists():
        print(f"  truth file not found ({truth_path}); question auto-answer will be skipped.")
        return {}
    try:
        parsed = json.loads(truth_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"  could not parse truth file {truth_path}: {exc}")
        return {}
    if not isinstance(parsed, dict):
        print(f"  invalid truth file format in {truth_path}; expected a JSON object at root.")
        return {}
    return parsed


def _collect_answer_pairs(truth: dict[str, Any]) -> dict[str, str]:
    answers: dict[str, str] = {}
    for key in ANSWER_MAPPING_KEYS:
        mapping = truth.get(key)
        if not isinstance(mapping, dict):
            continue
        for question, answer in mapping.items():
            norm = _normalized(question)
            if not norm:
                continue
            if isinstance(answer, (str, int, float, bool)):
                answers[norm] = _string_answer(answer)
    for key, value in truth.items():
        if key in ANSWER_MAPPING_KEYS:
            continue
        if isinstance(value, (str, int, float, bool)):
            norm = _normalized(key)
            if norm and norm not in answers:
                answers[norm] = _string_answer(value)
    return answers


def _resolve_existing_path(path_value: str, *, base_dirs: tuple[Path, ...]) -> Path | None:
    candidate = Path(path_value).expanduser()
    resolved_candidates: list[Path] = []
    if candidate.is_absolute():
        resolved_candidates.append(candidate.resolve())
    else:
        for base_dir in base_dirs:
            resolved_candidates.append((base_dir / candidate).resolve())

    for resolved in resolved_candidates:
        if resolved.exists():
            return resolved

    if resolved_candidates:
        print(f"  resume file not found: {resolved_candidates[0]}")
    return None


def _quoted(identifier: str) -> str:
    return f'"{identifier.replace(chr(34), chr(34) * 2)}"'


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({_quoted(table)})").fetchall()
    return {str(row[1]) for row in rows}


def _list_tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return [str(row[0]) for row in rows if row and row[0]]


def _looks_like_path(text: str) -> bool:
    value = text.strip()
    if not value or len(value) > 1200:
        return False
    lower = value.lower()
    if lower.startswith(("http://", "https://")):
        return False
    if lower.startswith("file://"):
        return True
    if lower.endswith((".pdf", ".doc", ".docx", ".rtf", ".txt")):
        return True
    return ("\\" in value or "/" in value) and "." in value


def _iter_strings_from_json(node: Any) -> list[str]:
    out: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            key_norm = _normalized(key)
            if any(token in key_norm for token in ("resume", "cv", "path", "file", "artifact", "output")):
                if isinstance(value, str) and value.strip():
                    out.append(value.strip())
            out.extend(_iter_strings_from_json(value))
    elif isinstance(node, list):
        for item in node:
            out.extend(_iter_strings_from_json(item))
    elif isinstance(node, str) and node.strip():
        out.append(node.strip())
    return out


def _extract_path_candidates(raw: str) -> list[str]:
    value = raw.strip()
    if not value:
        return []
    candidates: list[str] = []
    if _looks_like_path(value):
        candidates.append(value.removeprefix("file://"))

    if value[:1] in ("{", "["):
        try:
            parsed = json.loads(value)
        except Exception:
            parsed = None
        if parsed is not None:
            for nested in _iter_strings_from_json(parsed):
                if _looks_like_path(nested):
                    candidates.append(nested.removeprefix("file://"))

    seen: set[str] = set()
    deduped: list[str] = []
    for candidate in candidates:
        if candidate not in seen:
            seen.add(candidate)
            deduped.append(candidate)
    return deduped


def _resume_candidates_from_row(row: sqlite3.Row, columns: set[str]) -> list[tuple[int, str]]:
    marker_cols = [col for col in RESUME_MARKER_COLUMN_CANDIDATES if col in columns]
    marker_hit = False
    for marker_col in marker_cols:
        marker_val = row[marker_col]
        if isinstance(marker_val, str):
            normalized = _normalized(marker_val)
            if "resume" in normalized or normalized == "cv":
                marker_hit = True
                break

    ranked: list[tuple[int, str]] = []
    for column in columns:
        raw_value = row[column]
        if not isinstance(raw_value, str) or not raw_value.strip():
            continue
        for candidate in _extract_path_candidates(raw_value):
            score = 0
            col_norm = _normalized(column)
            if column in RESUME_PATH_COLUMN_CANDIDATES:
                score += 100
            if "resume" in col_norm or "cv" in col_norm:
                score += 60
            if "path" in col_norm or "file" in col_norm or "artifact" in col_norm:
                score += 40
            if marker_hit:
                score += 25
            if "resume" in candidate.lower() or "\\cv" in candidate.lower() or "/cv" in candidate.lower():
                score += 10
            ranked.append((score, candidate))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked


def _resume_path_from_table(
    conn: sqlite3.Connection,
    *,
    table: str,
    id_col: str,
    id_value: str,
    columns: set[str],
) -> str:
    order_cols = [col for col in ORDER_COLUMN_CANDIDATES if col in columns]
    order_clause = ""
    if order_cols:
        order_clause = " ORDER BY " + ", ".join(f"{_quoted(col)} DESC" for col in order_cols)

    table_name = _quoted(table)
    id_name = _quoted(id_col)
    query = f"SELECT * FROM {table_name} WHERE CAST({id_name} AS TEXT) = ?{order_clause} LIMIT 25"
    rows = conn.execute(query, [str(id_value)]).fetchall()
    for row in rows:
        for _, candidate in _resume_candidates_from_row(row, columns):
            return candidate
    return ""


def resolve_resume_file_for_job(job: ReadyJob, *, db_path: Path) -> Path | None:
    if not db_path.exists():
        print(f"  database not found for resume lookup: {db_path}")
        return None

    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        preferred_tables = ("project_artifacts", "projects", "scraped_jobs")
        available_tables = _list_tables(conn)
        ordered_tables = [table for table in preferred_tables if table in available_tables]
        ordered_tables.extend([table for table in available_tables if table not in ordered_tables])

        for table in ordered_tables:
            columns = _table_columns(conn, table)
            if not columns:
                continue
            id_cols = [col for col in IDENTIFIER_COLUMN_CANDIDATES if col in columns]
            if not id_cols:
                continue
            for id_col in id_cols:
                for id_value in (job.project_id, job.id):
                    if not str(id_value).strip():
                        continue
                    resume_value = _resume_path_from_table(
                        conn,
                        table=table,
                        id_col=id_col,
                        id_value=str(id_value),
                        columns=columns,
                    )
                    if resume_value:
                        resolved = _resolve_existing_path(
                            resume_value,
                            base_dirs=(AUTO_APPLY_DIR, db_path.parent, PROJECT_ROOT),
                        )
                        if resolved is not None:
                            return resolved
    return None


def _click_first_visible(page: Any, selectors: tuple[str, ...], *, timeout_ms: int = 2_000) -> bool:
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if locator.count() and locator.is_visible(timeout=min(1_500, timeout_ms)):
                locator.scroll_into_view_if_needed(timeout=5_000)
                locator.click(timeout=timeout_ms, delay=100)
                return True
        except Exception:
            continue
    return False


def _all_frames(page: Any) -> list[Any]:
    try:
        frames = list(page.frames)
    except Exception:
        return [page]
    return frames or [page]


def _set_input_files_on_target(target: Any, resume_file: Path) -> bool:
    try:
        uploaders = target.locator('input[type="file"]')
        count = uploaders.count()
    except Exception:
        return False
    for index in range(min(count, 8)):
        try:
            uploaders.nth(index).set_input_files(str(resume_file))
            return True
        except Exception:
            continue
    return False


def _upload_via_file_chooser(page: Any, resume_file: Path) -> bool:
    for target in _all_frames(page):
        for selector in FILE_CHOOSER_TRIGGER_SELECTORS:
            try:
                locator = target.locator(selector).first
                if not locator.count():
                    continue
                with page.expect_file_chooser(timeout=2_500) as chooser_info:
                    locator.scroll_into_view_if_needed(timeout=5_000)
                    locator.click(timeout=4_000, delay=80)
                chooser = chooser_info.value
                chooser.set_files(str(resume_file))
                page.wait_for_timeout(500)
                return True
            except Exception:
                continue
    return False


def _try_upload_resume(page: Any, resume_file: Path) -> bool:
    for target in _all_frames(page):
        if _set_input_files_on_target(target, resume_file):
            page.wait_for_timeout(500)
            return True
    if _upload_via_file_chooser(page, resume_file):
        return True
    for target in _all_frames(page):
        if _set_input_files_on_target(target, resume_file):
            page.wait_for_timeout(500)
            return True
    return False


def _handle_resume_step(page: Any, resume_file: Path | None) -> bool:
    if resume_file is None:
        return False

    if _try_upload_resume(page, resume_file):
        return True
    opened_options = _click_first_visible(page, RESUME_OPTIONS_SELECTORS)
    if opened_options:
        page.wait_for_timeout(300)
    _click_first_visible(page, UPLOAD_DIFFERENT_FILE_SELECTORS)
    page.wait_for_timeout(300)
    if _try_upload_resume(page, resume_file):
        return True
    _click_first_visible(page, FILE_CHOOSER_TRIGGER_SELECTORS)
    page.wait_for_timeout(300)
    return _try_upload_resume(page, resume_file)


def _answer_questions_from_truth(page: Any, answers: dict[str, str]) -> int:
    if not answers:
        return 0

    payload = page.evaluate(
        """
        ({ answers }) => {
            const normalize = (value) =>
                String(value ?? "")
                    .toLowerCase()
                    .replace(/_/g, " ")
                    .replace(/\\s+/g, " ")
                    .trim();
            const entries = Object.entries(answers || {}).map(([key, value]) => [normalize(key), String(value ?? "").trim()]);
            const visible = (el) => {
                if (!el) return false;
                const style = window.getComputedStyle(el);
                if (!style || style.visibility === "hidden" || style.display === "none") return false;
                return el.getClientRects().length > 0;
            };
            const boolFromAnswer = (value) => {
                const token = normalize(value);
                if (["yes", "true", "1", "y"].includes(token)) return true;
                if (["no", "false", "0", "n"].includes(token)) return false;
                return null;
            };
            const questionText = (el) => {
                const chunks = [];
                const own = normalize(el.getAttribute("aria-label") || el.getAttribute("name") || el.getAttribute("placeholder"));
                if (own) chunks.push(own);
                if (el.id) {
                    const linked = Array.from(document.querySelectorAll("label")).find((label) => label.htmlFor === el.id);
                    if (linked) chunks.push(normalize(linked.textContent));
                }
                const wrapper = el.closest("fieldset, section, form, div");
                if (wrapper) {
                    const legend = wrapper.querySelector("legend");
                    if (legend) chunks.push(normalize(legend.textContent));
                    const heading = wrapper.querySelector("h1,h2,h3,h4,label,p,span");
                    if (heading) chunks.push(normalize(heading.textContent));
                }
                return normalize(chunks.join(" "));
            };
            const pickAnswer = (question) => {
                const normQuestion = normalize(question);
                if (!normQuestion) return null;
                for (const [key, value] of entries) {
                    if (!key) continue;
                    if (normQuestion.includes(key) || key.includes(normQuestion)) return value;
                }
                return null;
            };
            const setValue = (el, value) => {
                const previous = el.value;
                el.focus();
                el.value = value;
                el.dispatchEvent(new Event("input", { bubbles: true }));
                el.dispatchEvent(new Event("change", { bubbles: true }));
                return previous !== value;
            };

            let changed = 0;

            for (const el of Array.from(document.querySelectorAll("textarea, input, select"))) {
                if (!visible(el) || el.disabled || el.readOnly) continue;
                const tag = el.tagName.toLowerCase();
                const type = normalize(el.type);
                const question = questionText(el);
                const answer = pickAnswer(question);
                if (!answer) continue;

                if (tag === "select") {
                    const normAnswer = normalize(answer);
                    let matched = null;
                    for (const option of Array.from(el.options || [])) {
                        const optionText = normalize(option.textContent);
                        const optionValue = normalize(option.value);
                        if (optionText === normAnswer || optionValue === normAnswer) {
                            matched = option;
                            break;
                        }
                        if (!matched && (optionText.includes(normAnswer) || normAnswer.includes(optionText))) {
                            matched = option;
                        }
                    }
                    if (matched && el.value !== matched.value) {
                        el.value = matched.value;
                        el.dispatchEvent(new Event("change", { bubbles: true }));
                        changed += 1;
                    }
                    continue;
                }

                if (
                    tag === "textarea"
                    || (tag === "input" && ["text", "email", "tel", "number", "url", "search"].includes(type))
                ) {
                    if (setValue(el, String(answer))) changed += 1;
                    continue;
                }

                if (tag === "input" && type === "checkbox") {
                    const asBool = boolFromAnswer(answer);
                    if (asBool !== null && el.checked !== asBool) {
                        el.click();
                        changed += 1;
                    }
                    continue;
                }
            }

            const grouped = {};
            for (const radio of Array.from(document.querySelectorAll('input[type="radio"]'))) {
                if (!visible(radio) || radio.disabled) continue;
                const name = radio.name || `__radio_${radio.id || Math.random()}`;
                if (!grouped[name]) grouped[name] = [];
                grouped[name].push(radio);
            }
            for (const radios of Object.values(grouped)) {
                if (!radios.length) continue;
                const question = questionText(radios[0]);
                const answer = pickAnswer(question);
                if (!answer) continue;
                const normAnswer = normalize(answer);
                let target = null;
                for (const radio of radios) {
                    const radioLabel = normalize(
                        (radio.id ? Array.from(document.querySelectorAll("label")).find((label) => label.htmlFor === radio.id)?.textContent : "")
                            || radio.getAttribute("aria-label")
                            || radio.value
                    );
                    if (radioLabel === normAnswer || normalize(radio.value) === normAnswer) {
                        target = radio;
                        break;
                    }
                    if (!target && (radioLabel.includes(normAnswer) || normAnswer.includes(radioLabel))) {
                        target = radio;
                    }
                }
                if (target && !target.checked) {
                    target.click();
                    changed += 1;
                }
            }

            return { changed };
        }
        """,
        {"answers": answers},
    )
    if isinstance(payload, dict):
        return int(payload.get("changed") or 0)
    return 0


def _application_submitted(page: Any) -> bool:
    for selector in SUBMITTED_SELECTORS:
        try:
            locator = page.locator(selector).first
            if locator.count() and locator.is_visible(timeout=500):
                return True
        except Exception:
            continue
    return False


def _click_progress(page: Any) -> bool:
    return _click_first_visible(page, PROGRESS_BUTTON_SELECTORS, timeout_ms=5_000)


ManualDecision = Literal["continue", "skip", "quit"]


def _manual_takeover(reason: str) -> ManualDecision:
    print(f"  manual takeover requested: {reason}")
    print("  take control in browser, then type continue | skip | quit")
    if not sys.stdin.isatty():
        print("  non-interactive session detected; skipping this job.")
        return "skip"
    while True:
        try:
            command = input("  command> ").strip().lower()
        except EOFError:
            return "skip"
        if command in {"c", "continue", "resume"}:
            return "continue"
        if command in {"s", "skip", "next"}:
            return "skip"
        if command in {"q", "quit", "exit", "stop"}:
            return "quit"
        print("  unknown command. valid options: continue | skip | quit")


def _pick_apply_page(current_page: Any) -> Any:
    try:
        pages = list(current_page.context.pages)
    except Exception:
        return current_page
    for candidate in reversed(pages):
        if candidate is current_page:
            continue
        try:
            if candidate.url and candidate.url != "about:blank":
                candidate.bring_to_front()
                return candidate
        except Exception:
            continue
    return current_page


def drive_indeed_apply_flow(
    page: Any,
    *,
    job: ReadyJob,
    resume_file: Path | None,
    answers: dict[str, str],
    max_steps: int,
    step_wait_ms: int,
    manual_takeover_enabled: bool,
) -> ApplyFlowResult:
    flow = ApplyFlowResult(status="in_progress")
    stale_cycles = 0
    resume_uploaded_once = False
    page = _pick_apply_page(page)
    prompted_for_missing_resume = False

    for step in range(1, max_steps + 1):
        flow.steps = step
        if _application_submitted(page):
            flow.status = "submitted"
            flow.resume_uploaded = resume_uploaded_once
            return flow

        changed = False
        if not resume_uploaded_once:
            if resume_file is None:
                if manual_takeover_enabled and not prompted_for_missing_resume:
                    decision = _manual_takeover(
                        f"{job.title or job.id} has no resume mapped in database. Upload manually, then continue."
                    )
                    prompted_for_missing_resume = True
                    if decision == "skip":
                        flow.status = "skipped"
                        flow.resume_uploaded = resume_uploaded_once
                        return flow
                    if decision == "quit":
                        flow.status = "quit"
                        flow.resume_uploaded = resume_uploaded_once
                        return flow
                    resume_uploaded_once = True
                    changed = True
            elif _handle_resume_step(page, resume_file):
                resume_uploaded_once = True
                changed = True

        if resume_uploaded_once:
            answers_count = _answer_questions_from_truth(page, answers)
            if answers_count > 0:
                flow.answers_applied += answers_count
                changed = True

            if _click_progress(page):
                changed = True

        page.wait_for_timeout(step_wait_ms)

        if _application_submitted(page):
            flow.status = "submitted"
            flow.resume_uploaded = resume_uploaded_once
            return flow

        stale_cycles = 0 if changed else stale_cycles + 1
        if stale_cycles >= 2:
            if not manual_takeover_enabled:
                flow.status = "stuck"
                flow.detail = "Bot is stuck and manual takeover is disabled."
                flow.resume_uploaded = resume_uploaded_once
                return flow
            decision = _manual_takeover(f"{job.title or job.id} appears stuck at step {step}")
            if decision == "skip":
                flow.status = "skipped"
                flow.resume_uploaded = resume_uploaded_once
                return flow
            if decision == "quit":
                flow.status = "quit"
                flow.resume_uploaded = resume_uploaded_once
                return flow
            stale_cycles = 0

    flow.status = "stuck"
    flow.resume_uploaded = resume_uploaded_once
    flow.detail = f"Reached max steps ({max_steps}) without submission."
    return flow


def process_jobs(
    jobs: list[ReadyJob],
    *,
    db_path: Path = DEFAULT_DB_PATH,
    profile_dir: Path = DEFAULT_PROFILE_DIR,
    truth_path: Path = DEFAULT_TRUTH_PATH,
    headless: bool = False,
    button_timeout_ms: int = 20_000,
    after_click_ms: int = 5_000,
    page_timeout_ms: int = 45_000,
    max_apply_steps: int = 20,
    step_wait_ms: int = 1_000,
    manual_takeover_enabled: bool = True,
    dry_run: bool = False,
) -> None:
    if not jobs:
        print("No ready not-applied jobs found.")
        return

    print(f"Found {len(jobs)} ready not-applied job(s).")
    if dry_run:
        for job in jobs:
            print(f"[dry-run] {job.id} | {job.title} @ {job.company} | {job.link}")
        return

    truth_data = load_truth_data(truth_path)
    answer_pairs = _collect_answer_pairs(truth_data)

    from scrapling.fetchers import StealthySession

    profile_dir.mkdir(parents=True, exist_ok=True)
    with StealthySession(
        headless=headless,
        user_data_dir=str(profile_dir),
        real_chrome=True,
    ) as session:
        for index, job in enumerate(jobs, start=1):
            label = f"{job.title or job.id} @ {job.company}".strip(" @")
            print(f"[{index}/{len(jobs)}] Opening {label}")
            resume_file = resolve_resume_file_for_job(job, db_path=db_path)
            if resume_file is None:
                print("  no mapped resume file found for this job in database.")

            result = ApplyActionResult()
            flow_result = ApplyFlowResult()

            def page_action(page: Any) -> None:
                nonlocal result, flow_result
                result = click_indeed_apply(
                    page,
                    button_timeout_ms=button_timeout_ms,
                    after_click_ms=after_click_ms,
                )
                if result.reacted:
                    flow_result = drive_indeed_apply_flow(
                        page,
                        job=job,
                        resume_file=resume_file,
                        answers=answer_pairs,
                        max_steps=max_apply_steps,
                        step_wait_ms=step_wait_ms,
                        manual_takeover_enabled=manual_takeover_enabled,
                    )

            try:
                session.fetch(
                    job.link,
                    timeout=page_timeout_ms,
                    wait=0,
                    network_idle=False,
                    google_search=False,
                    page_action=page_action,
                )
            except Exception as exc:
                print(f"  failed to load page: {exc}")
                continue

            if result.reacted:
                if result.direct_apply_attempted:
                    print(
                        "  opened direct Indeed apply URL "
                        f"({result.direct_apply_type}): {result.direct_apply_url}"
                    )
                else:
                    print(f"  clicked Indeed apply button; reaction detected ({result.reaction})")
                if flow_result.status == "submitted":
                    print("  apply flow complete: application appears submitted.")
                elif flow_result.status in {"stuck", "skipped", "quit"}:
                    suffix = f": {flow_result.detail}" if flow_result.detail else ""
                    print(f"  apply flow ended with status={flow_result.status}{suffix}")
                elif flow_result.status == "in_progress":
                    print("  apply flow ended without clear completion state.")
            elif result.click_attempted:
                print(
                    "  click attempted, but no page reaction was detected "
                    f"(before={result.before_url}, after={result.after_url})"
                )
                if result.error:
                    print(f"  details: {result.error}")
            elif result.button_kind == "company":
                print("  skipped: only company-site apply button was found")
            elif result.error:
                print(f"  skipped: button handling failed: {result.error}")
            else:
                print("  skipped: no supported apply button found before timeout")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Open ready not-applied Indeed jobs and click only the Indeed apply button."
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--profile-dir", type=Path, default=DEFAULT_PROFILE_DIR)
    parser.add_argument("--truth-file", type=Path, default=DEFAULT_TRUTH_PATH)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--include-running-projects",
        action="store_true",
        help="Include jobs linked to projects that are not completed yet.",
    )
    parser.add_argument("--button-timeout-ms", type=int, default=20_000)
    parser.add_argument("--page-timeout-ms", type=int, default=45_000)
    parser.add_argument("--after-click-ms", type=int, default=5_000)
    parser.add_argument("--max-apply-steps", type=int, default=20)
    parser.add_argument("--step-wait-ms", type=int, default=1_000)
    parser.add_argument(
        "--disable-manual-takeover",
        action="store_true",
        help="Do not pause for manual browser control when bot gets stuck.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    jobs = get_ready_jobs(
        db_path=args.db,
        require_completed_project=not args.include_running_projects,
        limit=args.limit,
    )
    process_jobs(
        jobs,
        db_path=args.db,
        profile_dir=args.profile_dir,
        truth_path=args.truth_file,
        headless=args.headless,
        button_timeout_ms=args.button_timeout_ms,
        after_click_ms=args.after_click_ms,
        page_timeout_ms=args.page_timeout_ms,
        max_apply_steps=args.max_apply_steps,
        step_wait_ms=args.step_wait_ms,
        manual_takeover_enabled=not args.disable_manual_takeover,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
