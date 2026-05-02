// TypeScript types matching the FastAPI response schemas

export interface User {
  id: string;
  display_name: string;
  created_at: string;
}

export interface Project {
  id: string;
  job_id: string;
  name: string;
  status: "running" | "completed" | "failed" | string;
  job_description: string;
  error_message: string;
  created_at: string;
  updated_at: string;
}

export interface Artifact {
  id: number;
  project_id: string;
  artifact_type: string;
  iteration: number | null;
  storage_path: string;
  file_name: string;
  mime_type: string;
  size_bytes: number | null;
  created_at: string;
}

export interface RunStatus {
  state: "idle" | "starting" | "running" | "completed" | "failed" | "stopping" | "stopped" | string;
  model: string;
  current_step: string;
  active_agent: string;
  active_task: string;
  iteration: string;
  output_dir: string;
  final_pdf: string;
  project_id: string;
  project_name: string;
  run_started_at: number | null;
  run_finished_at: number | null;
  exit_code: number | null;
}

export interface LogEntry {
  ts: number;
  stream: string;
  text: string;
  level: "info" | "warn" | "error" | "success" | "event" | string;
}

export interface Job {
  id: string;
  source: string;
  source_job_key: string;
  title: string;
  company: string;
  location: string;
  url: string;
  salary_raw: string;
  min_pay_yearly: number | null;
  max_pay_yearly: number | null;
  job_type: string;
  status: "new" | "interested" | "skipped" | "queued" | "generated" | string;
  scrape_status: "pending" | "scraped" | "failed" | string;
  relative_time: string;
  description: string;
  attributes: string[];
  posted_at: number | null;
  experience_required: number | null;
  requires_experience: number | null;
  apply_url: string;
  resume_count: number;
  created_at: string;
  updated_at: string;
  // backward compat
  source_url: string;
  salary: string;
}

export interface JobAnalysis {
  role_type: string;
  domain: string;
  experience: string;
}

export interface ScrapeStatus {
  has_driver: boolean;
  awaiting_verification: boolean;
}

export interface Batch {
  id: string;
  name: string;
  status: "draft" | "running" | "paused" | "completed" | "cancelled" | string;
  preferences: Record<string, unknown>;
  global_settings: Record<string, unknown>;
  item_count: number;
  completed_count: number;
  failed_count: number;
  created_at: string;
  updated_at: string;
}

export interface BatchItem {
  id: string;
  batch_id: string;
  job_id: string;
  project_id: string;
  status: "queued" | "running" | "completed" | "failed" | "cancelled" | string;
  error_message: string;
  title: string;
  company: string;
  location: string;
  salary: string;
  description: string;
  description_status: string;
  source_url: string;
  apply_url: string;
  settings_override: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface BatchRun {
  id: string;
  batch_id: string;
  model: string;
  api_key_env: string;
  max_iterations: number;
  parallel_runs: number;
  status: "running" | "completed" | "failed" | "cancelled" | string;
  created_at: string;
  updated_at: string;
}

export interface CompletedResume {
  id: string;
  batch_item_id: string;
  job_id: string;
  project_id: string;
  title: string;
  company: string;
  apply_url: string;
  resume_path: string;
  status: "ready" | "applied" | string;
  job_url: string;
  location: string;
  created_at: string;
}

export interface ModelPreset {
  label: string;
  model: string;
  api_key_env: string;
}
