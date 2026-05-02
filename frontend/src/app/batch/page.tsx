"use client";
import { useState, useEffect } from "react";
import useSWR from "swr";
import { api } from "@/lib/api";
import { useUser } from "@/lib/user-context";
import { StatusBadge } from "@/components/ui/StatusBadge";
import LogViewer from "@/components/ui/LogViewer";
import { useLogStream } from "@/lib/ws";
import type { Batch, BatchItem, Job, ModelPreset, CompletedResume } from "@/lib/types";

type Tab = "builder" | "queue" | "results";

export default function BatchPage() {
  const { activeUser } = useUser();
  const uid = activeUser?.id ?? "";
  const [activeTab, setActiveTab] = useState<Tab>("builder");

  const { data: jobs } = useSWR<Job[]>(uid ? `jobs/${uid}` : null, () => api.listJobs(uid), { refreshInterval: 5000 });
  const { data: batches, mutate: mutateBatches } = useSWR<Batch[]>(uid ? `batches/${uid}` : null, () => api.listBatches(uid), { refreshInterval: 3000 });
  const { data: models } = useSWR<ModelPreset[]>("models", api.models);
  const { data: completedResumes, mutate: mutateResumes } = useSWR<CompletedResume[]>(
    uid ? `completed-resumes/${uid}` : null,
    () => api.listCompletedResumes(),
    { refreshInterval: 5000 }
  );

  // ── Builder state ──
  const [batchName, setBatchName] = useState(() => `batch_${new Date().toISOString().slice(0, 10)}`);
  const [includeExisting, setIncludeExisting] = useState(false);
  const [shortlisted, setShortlisted] = useState<string[]>([]);
  const [reviewIdx, setReviewIdx] = useState(0);
  const [buildMsg, setBuildMsg] = useState("");
  const [creating, setCreating] = useState(false);

  // ── Queue state ──
  const [selectedBatchId, setSelectedBatchId] = useState<string | null>(null);
  const [batchItems, setBatchItems] = useState<BatchItem[]>([]);
  const [queueMsg, setQueueMsg] = useState("");
  const [modelLabel, setModelLabel] = useState("");
  const [maxIter, setMaxIter] = useState(10);
  const [parallel, setParallel] = useState(1);
  const [namePattern, setNamePattern] = useState("{company}_{title}");
  const [starting, setStarting] = useState(false);
  const [stopping, setStopping] = useState(false);

  const { logs: batchLogs } = useLogStream(
    uid && selectedBatchId ? `/api/batches/${uid}/${selectedBatchId}/logs/ws` : null
  );

  const selectedBatch = batches?.find(b => b.id === selectedBatchId) ?? null;

  // Auto-refresh items when viewing a running batch
  useEffect(() => {
    if (!selectedBatchId || !uid) return;
    const interval = setInterval(async () => {
      const items = await api.getBatchItems(uid, selectedBatchId);
      setBatchItems(items);
      mutateBatches();
    }, 4000);
    return () => clearInterval(interval);
  }, [selectedBatchId, uid]);

  // ── Builder helpers ──
  const readyJobs = (jobs ?? []).filter(j =>
    j.scrape_status === "scraped" &&
    !["queued", "generated"].includes(j.status) &&
    (includeExisting || j.resume_count === 0)
  );
  const currentJob = readyJobs[Math.min(reviewIdx, readyJobs.length - 1)] ?? null;
  const isShortlisted = currentJob ? shortlisted.includes(currentJob.id) : false;

  const toggleShortlist = (id: string) =>
    setShortlisted(p => p.includes(id) ? p.filter(x => x !== id) : [...p, id]);
  const addAndNext = () => {
    if (currentJob && !isShortlisted) toggleShortlist(currentJob.id);
    setReviewIdx(i => Math.min(readyJobs.length - 1, i + 1));
  };

  const createBatch = async () => {
    if (!uid || shortlisted.length === 0) { setBuildMsg("Add at least one job."); return; }
    setBuildMsg(""); setCreating(true);
    try {
      await api.createBatch(uid, { name: batchName, job_ids: shortlisted, global_settings: { name_pattern: namePattern } });
      setBuildMsg(`Batch "${batchName}" created with ${shortlisted.length} jobs.`);
      setShortlisted([]); mutateBatches(); setActiveTab("queue");
    } catch (e: unknown) { setBuildMsg(e instanceof Error ? e.message : String(e)); }
    finally { setCreating(false); }
  };

  // ── Queue helpers ──
  const selectBatch = async (b: Batch) => {
    setSelectedBatchId(b.id); setQueueMsg("");
    const items = await api.getBatchItems(uid, b.id);
    setBatchItems(items);
    const s = b.global_settings ?? {};
    if (s.max_iterations) setMaxIter(Number(s.max_iterations));
    if (s.parallel_runs) setParallel(Number(s.parallel_runs));
    if (s.name_pattern) setNamePattern(String(s.name_pattern));
    const m = models?.find(m => m.model === s.model);
    if (m) setModelLabel(m.label);
    else if (models?.length) setModelLabel(models[0].label);
  };

  const handleStart = async () => {
    if (!uid || !selectedBatchId) return;
    const preset = models?.find(m => m.label === modelLabel) ?? models?.[0];
    if (!preset) { setQueueMsg("Select a model first."); return; }
    setStarting(true); setQueueMsg("");
    try {
      await api.startBatch(uid, selectedBatchId, {
        model: preset.model,
        api_key_env: preset.api_key_env,
        max_iterations: maxIter,
        parallel_runs: parallel,
        name_pattern: namePattern,
      });
      setQueueMsg("Batch started — items are being processed automatically.");
      mutateBatches();
    } catch (e: unknown) { setQueueMsg(e instanceof Error ? e.message : String(e)); }
    finally { setStarting(false); }
  };

  const handleStop = async () => {
    if (!uid || !selectedBatchId || !confirm("Stop this batch and return all unfinished jobs back to the pool?")) return;
    setStopping(true); setQueueMsg("");
    try {
      await api.stopBatch(uid, selectedBatchId);
      setQueueMsg("Batch cancelled. Unfinished jobs returned to pool.");
      mutateBatches();
      const items = await api.getBatchItems(uid, selectedBatchId);
      setBatchItems(items);
    } catch (e: unknown) { setQueueMsg(e instanceof Error ? e.message : String(e)); }
    finally { setStopping(false); }
  };

  const handleDelete = async () => {
    if (!uid || !selectedBatchId || !confirm("Delete this batch? Generated projects are kept.")) return;
    await api.deleteBatch(uid, selectedBatchId);
    setSelectedBatchId(null); setBatchItems([]); mutateBatches();
  };

  if (!uid) return <p className="text-neutral-500 text-sm p-4">Select a profile first.</p>;

  const batchStatusColor: Record<string, string> = {
    draft: "text-neutral-400",
    running: "text-blue-400",
    completed: "text-green-400",
    failed: "text-red-400",
    cancelled: "text-orange-400",
  };

  const canStart = selectedBatch && ["draft", "cancelled", "failed"].includes(selectedBatch.status ?? "");
  const isRunning = selectedBatch?.status === "running";

  return (
    <div className="flex flex-col gap-4">
      {/* Tabs */}
      <div className="flex border-b border-neutral-800">
        {(["builder", "queue", "results"] as Tab[]).map(t => (
          <button key={t}
            className={`text-sm px-5 py-2.5 border-b-2 font-medium transition-colors ${activeTab === t ? "border-blue-500 text-blue-300" : "border-transparent text-neutral-500 hover:text-neutral-300"}`}
            onClick={() => setActiveTab(t)}>
            {t === "builder" ? "Batch Builder" : t === "queue" ? "Batch Queue" : "Completed Resumes"}
          </button>
        ))}
      </div>

      {/* ── BUILDER ── */}
      {activeTab === "builder" && (
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-4">
            <section className="border border-neutral-800 rounded-lg overflow-hidden">
              <div className="px-4 py-3 bg-neutral-900 border-b border-neutral-800 flex items-center justify-between">
                <span className="text-sm font-semibold text-neutral-200">Job Review</span>
                <span className="text-xs text-neutral-500">{readyJobs.length} available</span>
              </div>
              <div className="p-4 space-y-3">
                <label className="flex items-center gap-2 text-sm text-neutral-400 cursor-pointer">
                  <input type="checkbox" checked={includeExisting} onChange={e => setIncludeExisting(e.target.checked)} />
                  Include jobs with existing resumes
                </label>
                {readyJobs.length === 0 ? (
                  <p className="text-sm text-neutral-600 py-4 text-center">No ready jobs. Import and scrape from Find Jobs first.</p>
                ) : currentJob ? (
                  <div className="border border-neutral-700 rounded-lg p-3 space-y-2">
                    <div className="flex items-center justify-between text-xs text-neutral-500">
                      <span>{reviewIdx + 1} / {readyJobs.length}</span>
                      <span className="text-blue-400">{shortlisted.length} shortlisted</span>
                    </div>
                    <div>
                      <p className="text-sm font-semibold text-neutral-100">{currentJob.title}</p>
                      <p className="text-xs text-neutral-400">{currentJob.company} · {currentJob.location}</p>
                      {currentJob.salary_raw && <p className="text-xs text-green-400 mt-0.5">{currentJob.salary_raw}</p>}
                    </div>
                    {currentJob.description && (
                      <p className="text-xs text-neutral-500 line-clamp-4 leading-relaxed border-l-2 border-neutral-700 pl-3">
                        {currentJob.description.slice(0, 400)}{currentJob.description.length > 400 ? "…" : ""}
                      </p>
                    )}
                    <div className="grid grid-cols-2 gap-2 pt-1">
                      <button
                        className={`text-sm py-2 rounded-md border font-medium transition-colors ${isShortlisted ? "bg-green-900 border-green-700 text-green-200" : "bg-neutral-800 border-neutral-700 text-neutral-200 hover:bg-green-950 hover:border-green-800"}`}
                        onClick={addAndNext}>
                        {isShortlisted ? "✓ Added" : "✓ Add & Next →"}
                      </button>
                      <button className="text-sm py-2 rounded-md border border-neutral-700 bg-neutral-900 text-neutral-400 hover:bg-neutral-800 transition-colors"
                        onClick={() => setReviewIdx(i => Math.min(readyJobs.length - 1, i + 1))}>
                        Skip →
                      </button>
                    </div>
                    <div className="flex gap-2">
                      <button className="flex-1 text-xs py-1.5 rounded border border-neutral-800 text-neutral-600 hover:text-neutral-400 transition-colors"
                        onClick={() => setReviewIdx(i => Math.max(0, i - 1))} disabled={reviewIdx === 0}>
                        ← Back
                      </button>
                    </div>
                  </div>
                ) : null}
              </div>
            </section>

            {shortlisted.length > 0 && (
              <section className="border border-neutral-800 rounded-lg overflow-hidden">
                <div className="px-4 py-3 bg-neutral-900 border-b border-neutral-800 flex items-center justify-between">
                  <span className="text-sm font-semibold text-neutral-200">Shortlist ({shortlisted.length})</span>
                  <button className="text-xs text-red-400 hover:text-red-300" onClick={() => setShortlisted([])}>Clear all</button>
                </div>
                <div className="divide-y divide-neutral-900 max-h-48 overflow-auto">
                  {shortlisted.map(id => {
                    const j = jobs?.find(j => j.id === id);
                    return j ? (
                      <div key={id} className="flex items-center gap-3 px-4 py-2">
                        <div className="flex-1 min-w-0">
                          <p className="text-sm text-neutral-300 truncate">{j.title}</p>
                          <p className="text-xs text-neutral-600 truncate">{j.company}</p>
                        </div>
                        <button className="text-xs text-neutral-600 hover:text-red-400" onClick={() => toggleShortlist(id)}>✕</button>
                      </div>
                    ) : null;
                  })}
                </div>
              </section>
            )}
          </div>

          <div className="space-y-4">
            <section className="border border-neutral-800 rounded-lg overflow-hidden">
              <div className="px-4 py-3 bg-neutral-900 border-b border-neutral-800">
                <span className="text-sm font-semibold text-neutral-200">Create Batch</span>
              </div>
              <div className="p-4 space-y-4">
                <label className="block text-sm text-neutral-500">
                  Batch name
                  <input className="mt-1.5 w-full bg-neutral-900 border border-neutral-700 rounded-md px-3 py-2 text-sm text-neutral-100 focus:outline-none focus:border-neutral-500"
                    value={batchName} onChange={e => setBatchName(e.target.value)} />
                </label>
                <label className="block text-sm text-neutral-500">
                  Name pattern
                  <input className="mt-1.5 w-full bg-neutral-900 border border-neutral-700 rounded-md px-3 py-2 text-sm text-neutral-100 focus:outline-none focus:border-neutral-500"
                    value={namePattern} onChange={e => setNamePattern(e.target.value)} placeholder="{company}_{title}" />
                  <span className="text-xs text-neutral-600 mt-1 block">Variables: {"{company}"}, {"{title}"}, {"{job_id}"}</span>
                </label>
                {buildMsg && <p className="text-xs text-neutral-400 bg-neutral-900 rounded-md px-3 py-2">{buildMsg}</p>}
                <button
                  className="w-full text-sm py-2.5 bg-blue-800 text-white rounded-md hover:bg-blue-700 disabled:opacity-40 transition-colors font-medium"
                  onClick={createBatch} disabled={shortlisted.length === 0 || creating}>
                  {creating ? "Creating…" : `Create Batch (${shortlisted.length} jobs)`}
                </button>
              </div>
            </section>
          </div>
        </div>
      )}

      {/* ── QUEUE ── */}
      {activeTab === "queue" && (
        <div className="grid grid-cols-[260px_1fr] gap-4">
          {/* Batch list */}
          <section className="border border-neutral-800 rounded-lg overflow-hidden self-start">
            <div className="px-4 py-3 bg-neutral-900 border-b border-neutral-800 text-sm font-semibold text-neutral-200">Batches</div>
            <div className="divide-y divide-neutral-900 max-h-[600px] overflow-auto">
              {!batches?.length && <p className="text-sm text-neutral-600 px-4 py-4">No batches yet.</p>}
              {batches?.map(b => (
                <button key={b.id}
                  className={`w-full text-left px-4 py-3 flex flex-col gap-1 hover:bg-neutral-800 transition-colors ${selectedBatchId === b.id ? "bg-neutral-800" : ""}`}
                  onClick={() => selectBatch(b)}>
                  <div className="flex items-center gap-2">
                    <StatusBadge status={b.status} />
                    <span className={`text-xs font-medium ${batchStatusColor[b.status] ?? "text-neutral-400"}`}>{b.status}</span>
                  </div>
                  <span className="text-sm text-neutral-200 truncate">{b.name}</span>
                  <span className="text-xs text-neutral-600">{b.item_count} jobs · {b.completed_count} done · {b.failed_count} failed</span>
                </button>
              ))}
            </div>
          </section>

          {selectedBatch ? (
            <div className="space-y-4">
              {/* Settings + Controls */}
              <section className="border border-neutral-800 rounded-lg overflow-hidden">
                <div className="px-4 py-3 bg-neutral-900 border-b border-neutral-800 flex items-center gap-3">
                  <span className="text-sm font-semibold text-neutral-200">{selectedBatch.name}</span>
                  <span className={`text-xs font-medium ml-auto ${batchStatusColor[selectedBatch.status] ?? "text-neutral-400"}`}>
                    {selectedBatch.status} · {selectedBatch.item_count} items · {selectedBatch.completed_count} done · {selectedBatch.failed_count} failed
                  </span>
                </div>
                <div className="p-4 space-y-4">
                  {/* Only show settings if not running/completed */}
                  {!isRunning && (
                    <>
                      <p className="text-xs font-semibold text-neutral-400 uppercase tracking-wide">Generation Settings</p>
                      <div className="grid grid-cols-2 gap-3">
                        <label className="block text-xs text-neutral-500">
                          Model
                          <select className="mt-1.5 w-full bg-neutral-900 border border-neutral-700 rounded-md px-3 py-2 text-sm text-neutral-100"
                            value={modelLabel} onChange={e => setModelLabel(e.target.value)}>
                            {models?.map(m => <option key={m.model} value={m.label}>{m.label}</option>)}
                          </select>
                        </label>
                        <label className="block text-xs text-neutral-500">
                          Name pattern
                          <input className="mt-1.5 w-full bg-neutral-900 border border-neutral-700 rounded-md px-3 py-2 text-sm text-neutral-100"
                            value={namePattern} onChange={e => setNamePattern(e.target.value)} />
                        </label>
                        <label className="block text-xs text-neutral-500">
                          Iterations: <span className="text-neutral-300">{maxIter}</span>
                          <input type="range" min={1} max={20} value={maxIter} onChange={e => setMaxIter(Number(e.target.value))} className="w-full mt-1 accent-blue-500" />
                        </label>
                        <label className="block text-xs text-neutral-500">
                          Parallel runs: <span className="text-neutral-300">{parallel}</span>
                          <input type="range" min={1} max={6} value={parallel} onChange={e => setParallel(Number(e.target.value))} className="w-full mt-1 accent-blue-500" />
                        </label>
                      </div>
                    </>
                  )}

                  <div className="flex flex-wrap gap-2 pt-1">
                    {canStart && (
                      <button
                        className="text-sm px-5 py-2 bg-green-900 border border-green-700 rounded-md text-green-200 hover:bg-green-800 disabled:opacity-40 transition-colors font-medium"
                        onClick={handleStart} disabled={starting}>
                        {starting ? "Starting…" : "▶ Start Batch"}
                      </button>
                    )}
                    {isRunning && (
                      <button
                        className="text-sm px-5 py-2 bg-red-950 border border-red-800 rounded-md text-red-300 hover:bg-red-900 disabled:opacity-40 transition-colors font-medium"
                        onClick={handleStop} disabled={stopping}>
                        {stopping ? "Stopping…" : "⏹ Cancel & Return to Pool"}
                      </button>
                    )}
                    {!isRunning && (
                      <button
                        className="text-sm px-4 py-2 bg-neutral-900 border border-red-900/50 rounded-md text-red-400 hover:bg-red-950 transition-colors"
                        onClick={handleDelete}>
                        🗑 Delete Batch
                      </button>
                    )}
                  </div>
                  {queueMsg && <p className="text-xs text-neutral-400 bg-neutral-900 rounded-md px-3 py-2">{queueMsg}</p>}
                </div>
              </section>

              {/* Items table */}
              <section className="border border-neutral-800 rounded-lg overflow-hidden">
                <div className="px-4 py-3 bg-neutral-900 border-b border-neutral-800 text-sm font-semibold text-neutral-200">Items</div>
                <div className="overflow-auto max-h-64">
                  <table className="w-full text-sm">
                    <thead><tr className="border-b border-neutral-800 text-xs text-neutral-500 bg-neutral-950/50">
                      <th className="px-4 py-2 text-left">Company</th>
                      <th className="px-4 py-2 text-left">Title</th>
                      <th className="px-4 py-2 text-left">Status</th>
                      <th className="px-4 py-2 text-left">Error</th>
                    </tr></thead>
                    <tbody>
                      {batchItems.map(item => (
                        <tr key={item.id} className="border-b border-neutral-900">
                          <td className="px-4 py-2 text-neutral-400 text-xs">{item.company}</td>
                          <td className="px-4 py-2 text-neutral-200 text-xs truncate max-w-[180px]">{item.title}</td>
                          <td className="px-4 py-2"><StatusBadge status={item.status} /></td>
                          <td className="px-4 py-2 text-xs text-red-400 max-w-[200px]">
                            {item.error_message ? <span className="cursor-help truncate block" title={item.error_message}>{item.error_message}</span> : "—"}
                          </td>
                        </tr>
                      ))}
                      {batchItems.length === 0 && <tr><td colSpan={4} className="px-4 py-4 text-neutral-600 text-center text-sm">No items.</td></tr>}
                    </tbody>
                  </table>
                </div>
              </section>

              {/* Logs */}
              <section className="border border-neutral-800 rounded-lg overflow-hidden">
                <div className="px-4 py-3 bg-neutral-900 border-b border-neutral-800 text-sm font-semibold text-neutral-200">Live Logs</div>
                <div className="p-3"><LogViewer logs={batchLogs} height="h-40" /></div>
              </section>
            </div>
          ) : (
            <div className="flex items-center justify-center h-40 text-neutral-600 text-sm border border-neutral-800 rounded-lg">
              Select a batch to manage it.
            </div>
          )}
        </div>
      )}

      {/* ── RESULTS ── */}
      {activeTab === "results" && (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <p className="text-sm text-neutral-400">{completedResumes?.length ?? 0} completed resumes</p>
            <button onClick={() => mutateResumes()} className="text-xs text-neutral-500 hover:text-neutral-300">↻ Refresh</button>
          </div>
          {!completedResumes?.length && (
            <p className="text-sm text-neutral-600 py-8 text-center border border-neutral-800 rounded-lg">
              No completed resumes yet. Run a batch to generate them.
            </p>
          )}
          <div className="space-y-2">
            {completedResumes?.map(r => (
              <div key={r.id} className="border border-neutral-800 rounded-lg p-4 flex items-center gap-4 hover:bg-neutral-900/50 transition-colors">
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-neutral-200 truncate">{r.title}</p>
                  <p className="text-xs text-neutral-500">{r.company}{r.location ? ` · ${r.location}` : ""}</p>
                </div>
                <div className="flex items-center gap-3 shrink-0">
                  {r.apply_url && (
                    <a href={r.apply_url} target="_blank" className="text-xs px-3 py-1.5 bg-blue-900 border border-blue-700 rounded text-blue-200 hover:bg-blue-800">
                      Apply ↗
                    </a>
                  )}
                  {r.resume_path && (
                    <a href={`/api/projects/${uid}/${r.project_id}/artifacts/download-best`} target="_blank"
                      className="text-xs px-3 py-1.5 bg-neutral-800 border border-neutral-700 rounded text-neutral-300 hover:bg-neutral-700">
                      ↓ Resume
                    </a>
                  )}
                  <span className="text-xs text-neutral-600">{new Date(r.created_at).toLocaleDateString()}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
