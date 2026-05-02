// API base URL — reads from env or falls back to localhost:8000
export const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
export const WS_BASE = API_BASE.replace(/^http/, "ws");

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {}
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

import type {
  User, Project, Artifact, RunStatus, LogEntry, Job,
  Batch, BatchItem, BatchRun, CompletedResume, ScrapeStatus
} from "./types";

export const api = {
  // Health
  health: () => apiFetch<{ status: string }>("/api/health"),

  // Models
  models: () => apiFetch<{ label: string; model: string; api_key_env: string }[]>("/api/models"),

  // Users (backward compat — returns single profile)
  listUsers: () => apiFetch<User[]>("/api/users"),
  createUser: (display_name: string) =>
    apiFetch<User>("/api/users", { method: "POST", body: JSON.stringify({ display_name }) }),
  activateUser: (user_id: string) =>
    apiFetch<User>(`/api/users/${user_id}/activate`, { method: "POST" }),

  // Profiles
  getProfile: (uid: string) => apiFetch<{ uid: string; truth_json: Record<string, unknown> }>(`/api/profiles/${uid}`),
  getSampleProfile: () => apiFetch<{ uid: string; truth_json: Record<string, unknown> }>("/api/profiles/sample"),
  saveProfile: (uid: string, truth_json: Record<string, unknown>) =>
    apiFetch<{ uid: string; truth_json: Record<string, unknown> }>(`/api/profiles/${uid}`, {
      method: "PUT", body: JSON.stringify({ truth_json }),
    }),
  validateProfile: (uid: string, truth_json: Record<string, unknown>) =>
    apiFetch<{ syntax_ok: boolean; is_dict: boolean; warnings: string[]; error?: string }>(
      `/api/profiles/${uid}/validate`,
      { method: "POST", body: JSON.stringify({ truth_json }) }
    ),

  // Projects
  listProjects: (uid: string) => apiFetch<Project[]>(`/api/projects/${uid}`),
  deleteProject: (uid: string, project_id: string) =>
    apiFetch<{ ok: boolean }>(`/api/projects/${uid}/${project_id}`, { method: "DELETE" }),
  listArtifacts: (uid: string, project_id: string) =>
    apiFetch<Artifact[]>(`/api/projects/${uid}/${project_id}/artifacts`),
  artifactDownloadUrl: (uid: string, project_id: string, artifact_id: number) =>
    `${API_BASE}/api/projects/${uid}/${project_id}/artifacts/${artifact_id}/download`,
  artifactPreviewUrl: (uid: string, project_id: string, artifact_id: number) =>
    `${API_BASE}/api/projects/${uid}/${project_id}/artifacts/${artifact_id}/preview`,
  artifactDownloadBestUrl: (uid: string, project_id: string) =>
    `${API_BASE}/api/projects/${uid}/${project_id}/artifacts/download-best`,
  rerenderProject: (uid: string, project_id: string, omissions: Record<string, boolean>) =>
    apiFetch<{ ok: boolean }>(`/api/projects/${uid}/${project_id}/rerender`, {
      method: "POST", body: JSON.stringify({ omissions }),
    }),

  // Runs
  startRun: (uid: string, payload: {
    jd_text?: string; jd_path?: string; run_name: string; model: string;
    api_key_env: string; max_iterations: number; omissions: Record<string, boolean>;
    job_id?: string;
  }) => apiFetch<{ project_id: string; run_name: string }>(`/api/runs/${uid}/start`, {
    method: "POST", body: JSON.stringify(payload),
  }),
  stopRun: (uid: string) => apiFetch<{ ok: boolean }>(`/api/runs/${uid}/stop`, { method: "POST" }),
  getRunStatus: (uid: string) => apiFetch<RunStatus>(`/api/runs/${uid}/status`),
  getRunLogs: (uid: string) => apiFetch<LogEntry[]>(`/api/runs/${uid}/logs`),

  // Jobs
  listJobs: (uid: string) => apiFetch<Job[]>(`/api/jobs/${uid}`),
  getJob: (uid: string, job_id: string) => apiFetch<Job>(`/api/jobs/${uid}/${job_id}`),
  updateJobState: (uid: string, job_id: string, status: string) =>
    apiFetch<{ ok: boolean }>(`/api/jobs/${uid}/${job_id}/state`, {
      method: "PUT", body: JSON.stringify({ status }),
    }),
  deleteJob: (uid: string, job_id: string) =>
    apiFetch<{ ok: boolean }>(`/api/jobs/${uid}/${job_id}`, { method: "DELETE" }),
  importJobsFromPath: (uid: string, html_path: string, source = "indeed") =>
    apiFetch<{ parsed: number; stats: Record<string, number>; upsert: Record<string, number> }>(
      `/api/jobs/${uid}/import/path`,
      { method: "POST", body: JSON.stringify({ html_path, source }) }
    ),
  importJobsFromFile: async (uid: string, file: File, source = "indeed") => {
    const form = new FormData();
    form.append("file", file);
    form.append("source", source);
    const res = await fetch(`${API_BASE}/api/jobs/${uid}/import/upload?source=${source}`, {
      method: "POST", body: form,
    });
    if (!res.ok) throw new Error((await res.json()).detail ?? res.statusText);
    return res.json();
  },
  scrapeStart: (uid: string) =>
    apiFetch<{ ok: boolean; logs: string[] }>(`/api/jobs/${uid}/scrape/start`, { method: "POST" }),
  scrapeRun: (uid: string, wait_seconds = 120) =>
    apiFetch<{ ok: boolean; scraped: number; failed: number; upsert: Record<string, number>; logs: string[] }>(
      `/api/jobs/${uid}/scrape/run`, { method: "POST", body: JSON.stringify({ wait_seconds }) }
    ),
  scrapeClose: (uid: string) =>
    apiFetch<{ ok: boolean }>(`/api/jobs/${uid}/scrape/close`, { method: "POST" }),
  scrapeStatus: (uid: string) => apiFetch<ScrapeStatus>(`/api/jobs/${uid}/scrape/status`),

  // Batches
  listBatches: (uid: string) => apiFetch<Batch[]>(`/api/batches/${uid}`),
  createBatch: (uid: string, payload: { name: string; job_ids: string[]; preferences?: Record<string, unknown>; global_settings?: Record<string, unknown> }) =>
    apiFetch<Batch>(`/api/batches/${uid}`, { method: "POST", body: JSON.stringify(payload) }),
  getBatch: (uid: string, batch_id: string) => apiFetch<Batch>(`/api/batches/${uid}/${batch_id}`),
  getBatchItems: (uid: string, batch_id: string) =>
    apiFetch<BatchItem[]>(`/api/batches/${uid}/${batch_id}/items`),
  updateBatchSettings: (uid: string, batch_id: string, global_settings: Record<string, unknown>) =>
    apiFetch<{ ok: boolean }>(`/api/batches/${uid}/${batch_id}/settings`, {
      method: "PUT", body: JSON.stringify({ global_settings }),
    }),
  startBatch: (uid: string, batch_id: string, global_settings: Record<string, unknown>) =>
    apiFetch<{ ok: boolean }>(`/api/batches/${uid}/${batch_id}/start`, { method: "POST", body: JSON.stringify({ global_settings }) }),
  stopBatch: (uid: string, batch_id: string) =>
    apiFetch<{ ok: boolean }>(`/api/batches/${uid}/${batch_id}/stop`, { method: "POST" }),
  returnToPool: (uid: string, batch_id: string) =>
    apiFetch<{ ok: boolean; reset: number }>(`/api/batches/${uid}/${batch_id}/return-to-pool`, { method: "POST" }),
  resetBatchInterested: (uid: string, batch_id: string) =>
    apiFetch<{ ok: boolean; reset: number }>(`/api/batches/${uid}/${batch_id}/reset-interested`, { method: "POST" }),
  rerenderBatch: (uid: string, batch_id: string, omissions: Record<string, boolean>, project_ids: string[]) =>
    apiFetch<{ ok: number; errors: string[] }>(`/api/batches/${uid}/${batch_id}/rerender`, {
      method: "POST", body: JSON.stringify({ omissions, project_ids }),
    }),
  deleteBatch: (uid: string, batch_id: string) =>
    apiFetch<{ ok: boolean }>(`/api/batches/${uid}/${batch_id}`, { method: "DELETE" }),
  tickBatch: (uid: string, batch_id: string) =>
    apiFetch<{ launched: number }>(`/api/batches/${uid}/${batch_id}/tick`, { method: "POST" }),
  getBatchRunStatus: (uid: string, batch_id: string) =>
    apiFetch<{ run_id: string; meta: Record<string, string>; status: RunStatus; is_running: boolean }[]>(
      `/api/batches/${uid}/${batch_id}/run-status`
    ),

  // Batch Runs
  createBatchRun: (uid: string, batch_id: string, payload: { model: string; api_key_env: string; max_iterations?: number; parallel_runs?: number }) =>
    apiFetch<BatchRun>(`/api/batches/${uid}/${batch_id}/runs`, { method: "POST", body: JSON.stringify(payload) }),
  listBatchRuns: (uid: string, batch_id: string) =>
    apiFetch<BatchRun[]>(`/api/batches/${uid}/${batch_id}/runs`),

  // Completed Resumes
  listCompletedResumes: () =>
    apiFetch<CompletedResume[]>("/api/batches/completed-resumes"),
};
