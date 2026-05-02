"use client";
import { useState, useEffect, useCallback } from "react";
import useSWR from "swr";
import { api } from "@/lib/api";
import { useUser } from "@/lib/user-context";
import { useLogStream } from "@/lib/ws";
import { StatusBadge } from "@/components/ui/StatusBadge";
import LogViewer from "@/components/ui/LogViewer";
import type { Project, Artifact, RunStatus, ModelPreset } from "@/lib/types";

const SECTIONS = [
  ["no_objective",    "Objective"],
  ["no_skills",       "Skills"],
  ["no_experience",   "Experience"],
  ["no_projects",     "Projects"],
  ["no_education",    "Education"],
  ["no_activities",   "Activities"],
  ["no_applying_for", "Applying For"],
  ["no_photo",        "Photo"],
] as const;

export default function StudioPage() {
  const { activeUser } = useUser();
  const uid = activeUser?.id ?? "";

  const { data: projects, mutate: mutateProjects } = useSWR<Project[]>(
    uid ? `projects/${uid}` : null,
    () => api.listProjects(uid),
    { refreshInterval: 3000 }
  );
  const { data: status, mutate: mutateStatus } = useSWR<RunStatus>(
    uid ? `run-status/${uid}` : null,
    () => api.getRunStatus(uid),
    { refreshInterval: 1500 }
  );
  const { data: models } = useSWR<ModelPreset[]>("models", api.models);
  const { logs, clear: clearLogs } = useLogStream(uid ? `/api/runs/${uid}/logs/ws` : null);

  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [selectedArtifact, setSelectedArtifact] = useState<Artifact | null>(null);
  const [deleteConfirm, setDeleteConfirm] = useState(false);
  const [rerendering, setRerendering] = useState(false);
  const [rerenderMsg, setRerenderMsg] = useState("");
  const [omissions, setOmissions] = useState<Record<string, boolean>>({});
  const [jdText, setJdText] = useState("");
  const [runName, setRunName] = useState(() => `run_${Date.now().toString(36)}`);
  const [modelLabel, setModelLabel] = useState("");
  const [maxIter, setMaxIter] = useState(10);
  const [runError, setRunError] = useState("");
  const [starting, setStarting] = useState(false);

  const isRunning = status?.state === "running" || status?.state === "starting";

  useEffect(() => {
    if (!uid || !selectedProjectId) { setArtifacts([]); setSelectedArtifact(null); return; }
    api.listArtifacts(uid, selectedProjectId).then((arts) => {
      setArtifacts(arts);
      const best = arts.filter(a => a.mime_type === "application/pdf").sort((a,b) => (b.iteration??-1)-(a.iteration??-1))[0] ?? arts[arts.length-1] ?? null;
      if (!selectedArtifact) setSelectedArtifact(best);
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [uid, selectedProjectId]);

  useEffect(() => {
    if (status?.state === "completed" && status.project_id && status.project_id !== "-") {
      setSelectedProjectId(status.project_id);
      mutateProjects();
    }
  }, [status?.state, status?.project_id, mutateProjects]);

  useEffect(() => {
    if (models?.length && !modelLabel) setModelLabel(models[0].label);
  }, [models, modelLabel]);

  const startRun = async () => {
    if (!uid || !jdText.trim()) { setRunError("Job description is required."); return; }
    const preset = models?.find(m => m.label === modelLabel) ?? models?.[0];
    if (!preset) { setRunError("Select a model."); return; }
    setRunError(""); setStarting(true);
    try {
      const { project_id } = await api.startRun(uid, {
        jd_text: jdText.trim(),
        run_name: runName.trim() || "manual_run",
        model: preset.model,
        api_key_env: preset.api_key_env,
        max_iterations: maxIter,
        omissions,
      });
      setSelectedProjectId(project_id);
      setSelectedArtifact(null);
      clearLogs();
      mutateStatus();
    } catch (e: unknown) {
      setRunError(e instanceof Error ? e.message : String(e));
    } finally {
      setStarting(false);
    }
  };

  const stopRun = () => { api.stopRun(uid); mutateStatus(); };

  const deleteProject = async () => {
    if (!uid || !selectedProjectId) return;
    await api.deleteProject(uid, selectedProjectId);
    setSelectedProjectId(null); setArtifacts([]); setSelectedArtifact(null); setDeleteConfirm(false);
    mutateProjects();
  };

  const doRerender = async () => {
    if (!uid || !selectedProjectId) return;
    setRerendering(true); setRerenderMsg("");
    try {
      await api.rerenderProject(uid, selectedProjectId, omissions);
      setRerenderMsg("Re-rendered.");
      const arts = await api.listArtifacts(uid, selectedProjectId);
      setArtifacts(arts);
      const best = arts.filter(a => a.mime_type === "application/pdf").sort((a,b) => (b.iteration??-1)-(a.iteration??-1))[0] ?? null;
      if (best) setSelectedArtifact(best);
    } catch (e: unknown) {
      setRerenderMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setRerendering(false);
    }
  };

  const previewUrl = selectedArtifact ? api.artifactPreviewUrl(uid, selectedArtifact.project_id, selectedArtifact.id) : null;
  const downloadUrl = selectedArtifact ? api.artifactDownloadUrl(uid, selectedArtifact.project_id, selectedArtifact.id) : null;

  if (!uid) return <p className="text-neutral-500 text-sm p-4">Select a profile first.</p>;

  return (
    <div className="grid grid-cols-2 gap-4 h-full">
      {/* LEFT */}
      <div className="flex flex-col gap-4 overflow-auto">
        {/* Projects */}
        <section className="border border-neutral-800 rounded-lg overflow-hidden">
          <div className="px-4 py-3 bg-neutral-900 border-b border-neutral-800 flex items-center justify-between">
            <span className="text-sm font-semibold text-neutral-200">Projects</span>
            <span className="text-xs text-neutral-600">{projects?.length ?? 0} total</span>
          </div>
          <div className="max-h-48 overflow-y-auto divide-y divide-neutral-900">
            {!projects?.length && <p className="text-xs text-neutral-600 px-4 py-3">No projects yet. Run the pipeline to create one.</p>}
            {projects?.map(p => (
              <button key={p.id}
                className={`w-full text-left px-4 py-2.5 flex items-center gap-3 hover:bg-neutral-800/70 transition-colors ${selectedProjectId === p.id ? "bg-neutral-800" : ""}`}
                onClick={() => { setSelectedProjectId(p.id); setSelectedArtifact(null); setDeleteConfirm(false); setRerenderMsg(""); }}>
                <StatusBadge status={p.status} />
                <span className="flex-1 truncate text-sm text-neutral-200">{p.name}</span>
                <span className="text-xs text-neutral-600 shrink-0">{p.created_at.slice(0, 10)}</span>
              </button>
            ))}
          </div>
        </section>

        {/* Artifact browser */}
        {selectedProjectId && (
          <section className="border border-neutral-800 rounded-lg overflow-hidden">
            <div className="px-4 py-3 bg-neutral-900 border-b border-neutral-800 flex items-center justify-between">
              <span className="text-sm font-semibold text-neutral-200">Artifacts</span>
              {downloadUrl && (
                <a href={downloadUrl} download className="text-xs text-blue-400 hover:underline">↓ Download</a>
              )}
            </div>
            <div className="flex flex-wrap gap-2 p-3">
              {artifacts.map(a => (
                <button key={a.id} onClick={() => setSelectedArtifact(a)}
                  className={`text-xs px-3 py-1.5 rounded-md border transition-colors ${selectedArtifact?.id === a.id ? "border-blue-500 bg-blue-950 text-blue-200" : "border-neutral-700 text-neutral-400 hover:border-neutral-500 hover:text-neutral-200"}`}>
                  {a.file_name}
                </button>
              ))}
              {artifacts.length === 0 && <p className="text-xs text-neutral-600">No artifacts yet.</p>}
            </div>
          </section>
        )}

        {/* PDF Preview */}
        {previewUrl && selectedArtifact?.mime_type === "application/pdf" && (
          <section className="border border-neutral-800 rounded-lg overflow-hidden flex-1 min-h-0">
            <div className="px-4 py-3 bg-neutral-900 border-b border-neutral-800">
              <span className="text-sm font-semibold text-neutral-200">{selectedArtifact.file_name}</span>
            </div>
            <iframe src={previewUrl} className="w-full h-96 bg-white" title="PDF Preview" />
          </section>
        )}

        {/* Re-render + Delete */}
        {selectedProjectId && (
          <section className="border border-neutral-800 rounded-lg p-4 space-y-4">
            <div>
              <p className="text-sm font-semibold text-neutral-300 mb-3">Re-render with Section Changes</p>
              <div className="grid grid-cols-2 gap-x-6 gap-y-2 mb-3">
                {SECTIONS.map(([key, label]) => (
                  <label key={key} className="flex items-center gap-2 text-sm text-neutral-400 cursor-pointer hover:text-neutral-200">
                    <input type="checkbox" className="rounded" checked={!!omissions[key]} onChange={e => setOmissions(o => ({ ...o, [key]: e.target.checked }))} />
                    Hide {label}
                  </label>
                ))}
              </div>
              <div className="flex items-center gap-2">
                <button className="text-sm px-4 py-1.5 bg-neutral-800 border border-neutral-700 rounded-md text-neutral-300 hover:bg-neutral-700 disabled:opacity-50 transition-colors"
                  onClick={doRerender} disabled={rerendering}>
                  {rerendering ? "Re-rendering…" : "Re-render PDF"}
                </button>
                {rerenderMsg && <span className="text-xs text-neutral-400">{rerenderMsg}</span>}
              </div>
            </div>
            <div className="border-t border-neutral-800 pt-3">
              <label className="flex items-center gap-2 text-sm text-neutral-500 cursor-pointer mb-2">
                <input type="checkbox" checked={deleteConfirm} onChange={e => setDeleteConfirm(e.target.checked)} />
                Confirm delete this project
              </label>
              <button className="text-sm px-4 py-1.5 bg-red-950 border border-red-800 rounded-md text-red-300 hover:bg-red-900 disabled:opacity-40 transition-colors"
                onClick={deleteProject} disabled={!deleteConfirm}>
                Delete Project
              </button>
            </div>
          </section>
        )}
      </div>

      {/* RIGHT */}
      <div className="flex flex-col gap-4 overflow-auto">
        {/* Status */}
        <section className="border border-neutral-800 rounded-lg p-4">
          <div className="flex items-center gap-3 mb-2">
            <StatusBadge status={status?.state ?? "idle"} />
            <span className="text-sm text-neutral-300 font-medium">{status?.project_name || "No active run"}</span>
          </div>
          {isRunning && (
            <div className="grid grid-cols-3 gap-2 mt-2">
              {[["Agent", status?.active_agent], ["Step", status?.current_step], ["Iteration", status?.iteration]].map(([k, v]) => (
                <div key={k} className="bg-neutral-900 rounded-md px-3 py-2">
                  <p className="text-xs text-neutral-600 mb-0.5">{k}</p>
                  <p className="text-xs text-neutral-200 truncate">{v || "—"}</p>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* Logs */}
        <section className="border border-neutral-800 rounded-lg overflow-hidden flex-1 min-h-0">
          <div className="px-4 py-3 bg-neutral-900 border-b border-neutral-800 flex items-center justify-between">
            <span className="text-sm font-semibold text-neutral-200">Run Logs</span>
            <button onClick={clearLogs} className="text-xs text-neutral-500 hover:text-neutral-300">Clear</button>
          </div>
          <div className="p-3">
            <LogViewer logs={logs} height="h-52" />
          </div>
        </section>

        {/* Run Controls */}
        <section className="border border-neutral-800 rounded-lg p-4 space-y-4">
          <p className="text-sm font-semibold text-neutral-200 border-b border-neutral-800 pb-3">Run Pipeline</p>

          <div className="grid grid-cols-2 gap-3">
            <label className="block text-xs text-neutral-500">
              Run Name
              <input className="mt-1.5 w-full bg-neutral-900 border border-neutral-700 rounded-md px-3 py-2 text-sm text-neutral-100 focus:outline-none focus:border-neutral-500"
                value={runName} onChange={e => setRunName(e.target.value)} disabled={isRunning} />
            </label>
            <label className="block text-xs text-neutral-500">
              Model
              <select className="mt-1.5 w-full bg-neutral-900 border border-neutral-700 rounded-md px-3 py-2 text-sm text-neutral-100 focus:outline-none focus:border-neutral-500"
                value={modelLabel} onChange={e => setModelLabel(e.target.value)} disabled={isRunning}>
                {models?.map(m => <option key={m.model} value={m.label}>{m.label}</option>)}
              </select>
            </label>
          </div>

          <label className="block text-xs text-neutral-500">
            Max Iterations: <span className="text-neutral-300 font-medium">{maxIter}</span>
            <input type="range" min={1} max={20} value={maxIter} onChange={e => setMaxIter(Number(e.target.value))}
              className="w-full mt-1.5 accent-blue-500" disabled={isRunning} />
          </label>

          <label className="block text-xs text-neutral-500">
            Job Description
            <textarea className="mt-1.5 w-full bg-neutral-900 border border-neutral-700 rounded-md px-3 py-2 text-sm text-neutral-100 h-28 resize-none focus:outline-none focus:border-neutral-500"
              value={jdText} onChange={e => setJdText(e.target.value)} placeholder="Paste the full job description here…" disabled={isRunning} />
          </label>

          {runError && <p className="text-sm text-red-400 bg-red-950/30 border border-red-900 rounded-md px-3 py-2">{runError}</p>}

          <div className="flex gap-3 pt-1">
            <button className="flex-1 text-sm px-4 py-2 bg-blue-800 text-white rounded-md hover:bg-blue-700 disabled:opacity-40 transition-colors font-medium"
              onClick={startRun} disabled={isRunning || starting}>
              {starting ? "Starting…" : "▶  Run Pipeline"}
            </button>
            <button className="text-sm px-4 py-2 bg-neutral-800 border border-neutral-700 text-neutral-300 rounded-md hover:bg-neutral-700 disabled:opacity-40 transition-colors"
              onClick={stopRun} disabled={!isRunning}>
              ⏹ Stop
            </button>
          </div>
        </section>
      </div>
    </div>
  );
}
