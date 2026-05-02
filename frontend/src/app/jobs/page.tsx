"use client";
import { useState, useRef } from "react";
import useSWR from "swr";
import { api } from "@/lib/api";
import { useUser } from "@/lib/user-context";
import { StatusBadge } from "@/components/ui/StatusBadge";
import type { Job, ScrapeStatus } from "@/lib/types";

// ── Frontend-only NLP job analyzer ────────────────────────────────────────────
type JobCategory = {
  roleType: "Internship" | "Full-time" | "Part-time" | "Contract" | "Unknown";
  workMode: "Remote" | "Hybrid" | "On-site" | "Unknown";
  salaryBand: "High" | "Mid" | "Low" | "Unknown";
  domain: string;
  experience: string; // e.g. "0-1 yrs", "2-3 yrs", "5+ yrs", "Any"
};

const DOMAIN_MAP: Record<string, string[]> = {
  "AI/ML":       ["machine learning","deep learning","nlp","llm","ai engineer","data scientist","genai","computer vision","neural","transformer","diffusion"],
  "VLSI":        ["vlsi","rtl","verilog","fpga","asic","embedded","firmware","soc","eda","synthesis","timing"],
  "UI/UX":       ["ui/ux","figma","wireframe","user experience","user interface","interaction design","prototyping","usability"],
  "Frontend":    ["react","nextjs","vue","angular","svelte","frontend","ui developer","css","html","tailwind"],
  "Backend":     ["backend","node.js","django","fastapi","spring","golang","rust","flask","express","rest api","graphql"],
  "DevOps":      ["devops","kubernetes","docker","ci/cd","aws","azure","gcp","cloud","terraform","ansible","jenkins"],
  "Data":        ["data analyst","analytics","tableau","power bi","etl","sql","spark","hadoop","data warehouse","dbt"],
  "Full Stack":  ["full stack","fullstack","mern","mean","t3","next.js"],
  "Mobile":      ["android","ios","flutter","react native","swift","kotlin","mobile app"],
  "Cybersecurity":["security","penetration","soc analyst","siem","vulnerability","firewall","devsecops"],
};

function extractExperience(text: string): string {
  // Match patterns like "2-4 years", "3+ years", "minimum 1 year", "0-1 year"
  const patterns: [RegExp, (m: RegExpMatchArray) => string][] = [
    [/(\d+)\s*[-–]\s*(\d+)\s*(?:years?|yrs?)/i, m => `${m[1]}-${m[2]} yrs`],
    [/(\d+)\s*\+\s*(?:years?|yrs?)/i,            m => `${m[1]}+ yrs`],
    [/(?:minimum|min\.?|at\s+least)\s*(\d+)\s*(?:years?|yrs?)/i, m => `${m[1]}+ yrs`],
    [/(\d+)\s*(?:years?|yrs?)\s*(?:of\s+)?(?:experience|exp)/i,  m => `${m[1]}+ yrs`],
  ];
  for (const [re, fmt] of patterns) {
    const m = text.match(re);
    if (m) return fmt(m);
  }
  if (/fresher|entry.?level|no experience|0 years/i.test(text)) return "0 yrs / Fresher";
  if (/intern/i.test(text)) return "0-1 yrs";
  return "Not specified";
}

function categorizeJob(job: Job): JobCategory {
  const text = `${job.title} ${job.description} ${job.location} ${job.salary}`.toLowerCase();

  const roleType: JobCategory["roleType"] =
    /intern|internship|trainee|apprentice|co-?op/.test(text) ? "Internship"
    : /part.?time/.test(text) ? "Part-time"
    : /contract|freelance|consultant/.test(text) ? "Contract"
    : /full.?time|permanent/.test(text) ? "Full-time"
    : "Unknown";

  const workMode: JobCategory["workMode"] =
    /remote|work from home|wfh/.test(text) ? "Remote"
    : /hybrid/.test(text) ? "Hybrid"
    : /on.?site|in.?office|in person/.test(text) ? "On-site"
    : "Unknown";

  let domain = "General";
  let best = 0;
  for (const [d, kws] of Object.entries(DOMAIN_MAP)) {
    const score = kws.filter(k => text.includes(k)).length;
    if (score > best) { best = score; domain = d; }
  }

  const nums = (job.salary || "").match(/[\d,]+/g)
    ?.map(n => parseInt(n.replace(/,/g, ""), 10)).filter(n => n > 0) ?? [];
  const maxVal = nums.length ? Math.max(...nums) : 0;
  const salaryBand: JobCategory["salaryBand"] = maxVal > 1_000_000 ? "High"
    : maxVal > 300_000 ? "Mid"
    : maxVal > 0 ? "Low"
    : "Unknown";

  const experience = extractExperience(`${job.title} ${job.description}`);

  return { roleType, workMode, salaryBand, domain, experience };
}

// Memoized per-job (avoids re-running NLP on every render)
const _catCache = new WeakMap<Job, JobCategory>();
function getCat(job: Job): JobCategory {
  if (!_catCache.has(job)) _catCache.set(job, categorizeJob(job));
  return _catCache.get(job)!;
}

const ROLE_COLOR: Record<string, string> = {
  Internship: "bg-purple-900 text-purple-300",
  "Full-time": "bg-blue-900 text-blue-300",
  "Part-time": "bg-yellow-900 text-yellow-300",
  Contract:   "bg-orange-900 text-orange-300",
  Unknown:    "bg-neutral-800 text-neutral-500",
};
const MODE_COLOR: Record<string, string> = {
  Remote:   "bg-green-900 text-green-300",
  Hybrid:   "bg-teal-900 text-teal-300",
  "On-site":"bg-neutral-800 text-neutral-400",
  Unknown:  "bg-neutral-900 text-neutral-600",
};

function CategoryPills({ job }: { job: Job }) {
  const cat = getCat(job);
  return (
    <div className="flex flex-wrap gap-1 mt-1">
      <span className={`text-xs px-1.5 py-0.5 rounded font-mono ${ROLE_COLOR[cat.roleType]}`}>{cat.roleType}</span>
      {cat.workMode !== "Unknown" && (
        <span className={`text-xs px-1.5 py-0.5 rounded font-mono ${MODE_COLOR[cat.workMode]}`}>{cat.workMode}</span>
      )}
      <span className="text-xs px-1.5 py-0.5 rounded font-mono bg-neutral-800 text-neutral-400">{cat.domain}</span>
      {cat.experience !== "Not specified" && (
        <span className="text-xs px-1.5 py-0.5 rounded font-mono bg-neutral-800 text-neutral-500">{cat.experience}</span>
      )}
      {cat.salaryBand !== "Unknown" && (
        <span className={`text-xs px-1.5 py-0.5 rounded font-mono ${
          cat.salaryBand === "High" ? "bg-green-900 text-green-300"
          : cat.salaryBand === "Mid" ? "bg-yellow-900 text-yellow-300"
          : "bg-neutral-800 text-neutral-400"}`}>
          {cat.salaryBand} pay
        </span>
      )}
    </div>
  );
}

// ── Constants ──────────────────────────────────────────────────────────────────
const ROLE_FILTERS  = ["All", "Internship", "Full-time", "Part-time", "Contract"];
const MODE_FILTERS  = ["All", "Remote", "Hybrid", "On-site"];
const DOMAIN_FILTERS = ["All", ...Object.keys(DOMAIN_MAP), "General"];
const EXP_FILTERS   = ["All", "0 yrs / Fresher", "0-1 yrs", "1+ yrs", "2+ yrs", "3+ yrs", "5+ yrs"];
const APP_FILTERS   = ["all", "new", "saved", "queued", "generating", "generated", "applied", "skipped", "failed"] as const;
const DESC_FILTERS  = ["all", "ready", "missing", "failed"] as const;
const JOB_ACTIONS   = [
  { status: "saved",   label: "Interested" },
  { status: "applied", label: "Applied" },
  { status: "skipped", label: "Not Interested" },
  { status: "new",     label: "Reset" },
] as const;


export default function JobsPage() {
  const { activeUser } = useUser();
  const uid = activeUser?.id ?? "";

  const [descFilter, setDescFilter] = useState("all");
  const [appFilter, setAppFilter] = useState("all");
  const [roleFilter, setRoleFilter] = useState("All");
  const [modeFilter, setModeFilter] = useState("All");
  const [domainFilter, setDomainFilter] = useState("All");
  const [expFilter, setExpFilter] = useState("All");
  const [search, setSearch] = useState("");
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [deleteConfirm, setDeleteConfirm] = useState(false);
  const [notes, setNotes] = useState("");
  const [htmlMode, setHtmlMode] = useState<"path" | "upload">("path");
  const [htmlPath, setHtmlPath] = useState("");
  const [importMsg, setImportMsg] = useState("");
  const [importing, setImporting] = useState(false);
  const [waitSecs, setWaitSecs] = useState(120);
  const [scrapeMsg, setScrapeMsg] = useState("");
  const [scraping, setScraping] = useState(false);
  const [massSelected, setMassSelected] = useState<Set<string>>(new Set());
  const [massAction, setMassAction] = useState("skipped");
  const [massWorking, setMassWorking] = useState(false);
  const [massMsg, setMassMsg] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  const { data: allJobs, mutate: mutateJobs } = useSWR<Job[]>(
    uid ? `jobs/${uid}` : null,
    () => api.listJobs(uid),
    { refreshInterval: 4000 }
  );
  const { data: scrapeStatus, mutate: mutateScrapeStatus } = useSWR<ScrapeStatus>(
    uid ? `scrape-status/${uid}` : null,
    () => api.scrapeStatus(uid),
    { refreshInterval: 3000 }
  );

  // Frontend-only filtering + NLP categorization
  const jobs = (allJobs ?? []).filter(job => {
    if (descFilter !== "all" && job.scrape_status !== descFilter) return false;
    if (appFilter !== "all" && job.status !== appFilter) return false;
    if (search.trim()) {
      const h = `${job.title} ${job.company} ${job.location} ${job.salary}`.toLowerCase();
      if (!h.includes(search.trim().toLowerCase())) return false;
    }
    if (roleFilter !== "All" || modeFilter !== "All" || domainFilter !== "All" || expFilter !== "All") {
      const cat = getCat(job);
      if (roleFilter !== "All" && cat.roleType !== roleFilter) return false;
      if (modeFilter !== "All" && cat.workMode !== modeFilter) return false;
      if (domainFilter !== "All" && cat.domain !== domainFilter) return false;
      if (expFilter !== "All") {
        // Match experience prefix: "2+ yrs" matches jobs with "2-3 yrs", "2+ yrs", etc.
        const expNum = parseInt(expFilter);
        if (!isNaN(expNum)) {
          const jobExpNum = parseInt(cat.experience);
          if (isNaN(jobExpNum) || jobExpNum < expNum) return false;
        } else if (cat.experience !== expFilter) {
          return false;
        }
      }
    }
    return true;
  });

  const selectedJob = jobs.find(j => j.id === selectedJobId) ?? null;

  const handleAction = async (status: string) => {
    if (!uid || !selectedJobId) return;
    await api.updateJobState(uid, selectedJobId, status);
    mutateJobs();
  };

  // Serialize to avoid SQLite lock contention from concurrent writes
  const handleMassAction = async () => {
    if (!uid || massSelected.size === 0 || massWorking) return;
    setMassWorking(true); setMassMsg("");
    const ids = [...massSelected];
    let done = 0;
    try {
      for (const id of ids) {
        await api.updateJobState(uid, id, massAction);
        done++;
        setMassMsg(`${done}/${ids.length}…`);
      }
      setMassSelected(new Set());
      setMassMsg("");
      mutateJobs();
    } catch (e: unknown) {
      setMassMsg(`Failed after ${done}/${ids.length}: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setMassWorking(false);
    }
  };

  const handleMassDelete = async () => {
    if (!uid || massSelected.size === 0 || massWorking) return;
    if (!confirm(`Delete ${massSelected.size} job(s) from the database? This cannot be undone.`)) return;
    setMassWorking(true); setMassMsg("");
    const ids = [...massSelected];
    let done = 0;
    try {
      for (const id of ids) {
        await api.deleteJob(uid, id);
        done++;
        setMassMsg(`Deleting ${done}/${ids.length}…`);
      }
      setMassSelected(new Set());
      setMassMsg("");
      mutateJobs();
    } catch (e: unknown) {
      setMassMsg(`Failed after ${done}/${ids.length}: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setMassWorking(false);
    }
  };

  const toggleMass = (id: string) => setMassSelected(prev => {
    const n = new Set(prev);
    n.has(id) ? n.delete(id) : n.add(id);
    return n;
  });

  const selectAllVisible = () => setMassSelected(new Set(jobs.map(j => j.id)));
  const clearSelection = () => setMassSelected(new Set());

  const handleImport = async () => {
    setImporting(true); setImportMsg("");
    try {
      let r;
      if (htmlMode === "path") {
        r = await api.importJobsFromPath(uid, htmlPath);
      } else {
        const file = fileRef.current?.files?.[0];
        if (!file) { setImportMsg("No file selected."); setImporting(false); return; }
        r = await api.importJobsFromFile(uid, file);
      }
      setImportMsg(`Parsed ${r.parsed} jobs. Inserted: ${r.upsert.inserted}, Updated: ${r.upsert.updated}, Skipped: ${r.upsert.skipped}.`);
      mutateJobs();
    } catch (e: unknown) {
      setImportMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setImporting(false);
    }
  };

  const handleScrapeStart = async () => {
    setScrapeMsg(""); setScraping(true);
    try {
      await api.scrapeStart(uid);
      setScrapeMsg("Browser opened. Complete any CAPTCHA, then click 'Scrape & Save'.");
      mutateScrapeStatus();
    } catch (e: unknown) { setScrapeMsg(e instanceof Error ? e.message : String(e)); }
    finally { setScraping(false); }
  };

  const handleScrapeRun = async () => {
    setScrapeMsg("Scraping…"); setScraping(true);
    try {
      const r = await api.scrapeRun(uid, waitSecs);
      setScrapeMsg(`Done. Scraped: ${r.scraped}, Failed: ${r.failed}. Inserted: ${r.upsert?.inserted ?? 0}, Updated: ${r.upsert?.updated ?? 0}.`);
      mutateJobs(); mutateScrapeStatus();
    } catch (e: unknown) { setScrapeMsg(e instanceof Error ? e.message : String(e)); }
    finally { setScraping(false); }
  };

  const handleDelete = async () => {
    if (!uid || !selectedJobId) return;
    await api.deleteJob(uid, selectedJobId);
    setSelectedJobId(null); setDeleteConfirm(false); mutateJobs();
  };

  const stats = { total: allJobs?.length ?? 0, ready: allJobs?.filter(j => j.scrape_status === "scraped").length ?? 0, generated: allJobs?.filter(j => j.resume_count > 0).length ?? 0, applied: allJobs?.filter(j => j.status === "generated").length ?? 0 };

  if (!uid) return <p className="text-neutral-500 text-sm p-4">Select a profile first.</p>;

  return (
    <div className="flex flex-col gap-4">
      {/* Import + Scrape */}
      <div className="grid grid-cols-2 gap-4">
        <section className="border border-neutral-800 rounded-lg overflow-hidden">
          <div className="px-4 py-3 bg-neutral-900 border-b border-neutral-800">
            <span className="text-sm font-semibold text-neutral-200">Step 1 — Parse Job List from HTML</span>
          </div>
          <div className="p-4 space-y-3">
            <div className="flex gap-4 text-sm">
              {(["path", "upload"] as const).map(m => (
                <label key={m} className="flex items-center gap-2 cursor-pointer text-neutral-400">
                  <input type="radio" checked={htmlMode === m} onChange={() => setHtmlMode(m)} />
                  {m === "path" ? "File path" : "Upload file"}
                </label>
              ))}
            </div>
            {htmlMode === "path" ? (
              <input
                key="path-input"
                className="w-full bg-neutral-900 border border-neutral-700 rounded-md px-3 py-2 text-sm text-neutral-100 focus:outline-none focus:border-neutral-500"
                value={htmlPath} onChange={e => setHtmlPath(e.target.value)} placeholder="e.g. C:\Users\...\jobs.html" />
            ) : (
              <input
                key="file-input"
                ref={fileRef} type="file" accept=".html,.htm"
                className="text-sm text-neutral-400 block w-full" />
            )}
            <button className="text-sm px-4 py-2 bg-neutral-800 border border-neutral-700 rounded-md text-neutral-300 hover:bg-neutral-700 disabled:opacity-50 transition-colors w-full"
              onClick={handleImport} disabled={importing}>
              {importing ? "Parsing…" : "Parse Jobs"}
            </button>
            {importMsg && <p className="text-xs text-neutral-400 bg-neutral-900 rounded-md px-3 py-2">{importMsg}</p>}
          </div>
        </section>

        <section className="border border-neutral-800 rounded-lg overflow-hidden">
          <div className="px-4 py-3 bg-neutral-900 border-b border-neutral-800 flex items-center justify-between">
            <span className="text-sm font-semibold text-neutral-200">Step 2 — Scrape Descriptions</span>
            <div className="flex items-center gap-2 text-xs">
              <span className={`w-2 h-2 rounded-full ${scrapeStatus?.has_driver ? "bg-green-400" : "bg-neutral-600"}`} />
              <span className="text-neutral-500">{scrapeStatus?.has_driver ? "Browser active" : "No browser"}</span>
            </div>
          </div>
          <div className="p-4 space-y-3">
            {scrapeStatus?.awaiting_verification && (
              <p className="text-xs text-yellow-400 bg-yellow-950/30 border border-yellow-900 rounded-md px-3 py-2">⚠ Complete CAPTCHA in browser, then click Scrape &amp; Save.</p>
            )}
            <label className="block text-xs text-neutral-500">
              Max wait per job: <span className="text-neutral-300">{waitSecs}s</span>
              <input type="range" min={20} max={300} value={waitSecs} onChange={e => setWaitSecs(Number(e.target.value))} className="w-full mt-1 accent-blue-500" />
            </label>
            <div className="grid grid-cols-3 gap-2">
              <button className="text-xs px-3 py-2 bg-neutral-800 border border-neutral-700 rounded-md text-neutral-300 hover:bg-neutral-700 disabled:opacity-50 transition-colors"
                onClick={handleScrapeStart} disabled={scraping}>Open Browser</button>
              <button className="text-xs px-3 py-2 bg-blue-900 border border-blue-700 rounded-md text-blue-200 hover:bg-blue-800 disabled:opacity-50 transition-colors"
                onClick={handleScrapeRun} disabled={scraping || !scrapeStatus?.has_driver}>Scrape &amp; Save</button>
              <button className="text-xs px-3 py-2 bg-neutral-800 border border-neutral-700 rounded-md text-neutral-400 hover:bg-neutral-700 transition-colors"
                onClick={() => api.scrapeClose(uid).then(() => mutateScrapeStatus())}>Close</button>
            </div>
            {scrapeMsg && <p className="text-xs text-neutral-400 bg-neutral-900 rounded-md px-3 py-2 whitespace-pre-wrap">{scrapeMsg}</p>}
          </div>
        </section>
      </div>

      {/* Job Library */}
      <section className="border border-neutral-800 rounded-lg overflow-hidden">
        <div className="px-4 py-3 bg-neutral-900 border-b border-neutral-800 flex items-center gap-6">
          <span className="text-sm font-semibold text-neutral-200">Job Library</span>
          <div className="flex gap-4 text-xs text-neutral-500">
            <span>Total: <b className="text-neutral-300">{stats.total}</b></span>
            <span>Ready: <b className="text-green-400">{stats.ready}</b></span>
            <span>Generated: <b className="text-blue-400">{stats.generated}</b></span>
            <span>Applied: <b className="text-neutral-200">{stats.applied}</b></span>
          </div>
        </div>

        {/* Filters — row 1 */}
        <div className="flex flex-wrap gap-2 px-4 py-3 border-b border-neutral-800 bg-neutral-950/50">
          <select className="text-xs bg-neutral-900 border border-neutral-700 rounded-md px-2 py-1.5 text-neutral-300"
            value={descFilter} onChange={e => setDescFilter(e.target.value)}>
            {DESC_FILTERS.map(f => <option key={f} value={f}>{f === "all" ? "Any description" : `Desc: ${f}`}</option>)}
          </select>
          <select className="text-xs bg-neutral-900 border border-neutral-700 rounded-md px-2 py-1.5 text-neutral-300"
            value={appFilter} onChange={e => setAppFilter(e.target.value)}>
            {APP_FILTERS.map(f => <option key={f} value={f}>{f === "all" ? "Any status" : f}</option>)}
          </select>
          <select className="text-xs bg-neutral-900 border border-neutral-700 rounded-md px-2 py-1.5 text-neutral-300"
            value={roleFilter} onChange={e => setRoleFilter(e.target.value)}>
            {ROLE_FILTERS.map(f => <option key={f} value={f}>{f === "All" ? "Any role type" : f}</option>)}
          </select>
          <select className="text-xs bg-neutral-900 border border-neutral-700 rounded-md px-2 py-1.5 text-neutral-300"
            value={modeFilter} onChange={e => setModeFilter(e.target.value)}>
            {MODE_FILTERS.map(f => <option key={f} value={f}>{f === "All" ? "Any work mode" : f}</option>)}
          </select>
          <select className="text-xs bg-neutral-900 border border-neutral-700 rounded-md px-2 py-1.5 text-neutral-300"
            value={domainFilter} onChange={e => setDomainFilter(e.target.value)}>
            {DOMAIN_FILTERS.map(f => <option key={f} value={f}>{f === "All" ? "Any domain" : f}</option>)}
          </select>
          <select className="text-xs bg-neutral-900 border border-neutral-700 rounded-md px-2 py-1.5 text-neutral-300"
            value={expFilter} onChange={e => setExpFilter(e.target.value)}>
            {EXP_FILTERS.map(f => <option key={f} value={f}>{f === "All" ? "Any experience" : f}</option>)}
          </select>
          <input className="text-xs bg-neutral-900 border border-neutral-700 rounded-md px-3 py-1.5 text-neutral-100 w-40 focus:outline-none focus:border-neutral-500"
            placeholder="Search…" value={search} onChange={e => setSearch(e.target.value)} />
          <button className="text-xs text-neutral-600 hover:text-neutral-400 ml-auto self-center"
            onClick={() => { setDescFilter("all"); setAppFilter("all"); setRoleFilter("All"); setModeFilter("All"); setDomainFilter("All"); setExpFilter("All"); setSearch(""); }}>
            Reset filters
          </button>
          <span className="text-xs text-neutral-600 self-center">{jobs.length} shown</span>
        </div>

        {/* Mass actions */}
        {massSelected.size > 0 && (
          <div className="flex flex-wrap items-center gap-3 px-4 py-2 bg-blue-950/30 border-b border-blue-900/50">
            <span className="text-xs text-blue-300 font-medium">{massSelected.size} selected</span>
            <select className="text-xs bg-neutral-900 border border-neutral-700 rounded px-2 py-1 text-neutral-300"
              value={massAction} onChange={e => setMassAction(e.target.value)} disabled={massWorking}>
              <option value="skipped">Mark Not Interested</option>
              <option value="saved">Mark Interested</option>
              <option value="new">Reset status</option>
              <option value="applied">Mark Applied</option>
            </select>
            <button className="text-xs px-3 py-1.5 bg-blue-800 text-white rounded hover:bg-blue-700 disabled:opacity-50 transition-colors"
              onClick={handleMassAction} disabled={massWorking}>
              {massWorking ? massMsg || "Working…" : `Apply to ${massSelected.size}`}
            </button>
            <button className="text-xs px-3 py-1.5 bg-red-950 border border-red-800 text-red-300 rounded hover:bg-red-900 disabled:opacity-50 transition-colors"
              onClick={handleMassDelete} disabled={massWorking}>
              🗑 Delete {massSelected.size}
            </button>
            <button className="text-xs text-neutral-500 hover:text-neutral-300" onClick={clearSelection} disabled={massWorking}>Clear</button>
            {massMsg && !massWorking && <span className="text-xs text-red-400">{massMsg}</span>}
          </div>
        )}

        <div className="flex items-center gap-3 px-4 py-2 border-b border-neutral-800 bg-neutral-950/20">
          <button className="text-xs text-neutral-500 hover:text-neutral-300" onClick={selectAllVisible}>Select all visible</button>
          <span className="text-neutral-700">|</span>
          <button className="text-xs text-neutral-500 hover:text-neutral-300" onClick={clearSelection}>Clear selection</button>
        </div>

        {/* Table */}
        <div className="overflow-auto max-h-72">
          <table className="w-full text-sm text-left">
            <thead>
              <tr className="border-b border-neutral-800 text-xs text-neutral-500 bg-neutral-950/50">
                <th className="px-4 py-2 w-8"><input type="checkbox" onChange={e => e.target.checked ? selectAllVisible() : clearSelection()} checked={massSelected.size === jobs.length && jobs.length > 0} /></th>
                <th className="px-4 py-2">Title / Company</th>
                <th className="px-4 py-2">Location</th>
                <th className="px-4 py-2">Desc</th>
                <th className="px-4 py-2">Status</th>
                <th className="px-4 py-2 text-center">Resumes</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map(job => (
                <tr key={job.id}
                  className={`border-b border-neutral-900 cursor-pointer hover:bg-neutral-800/50 transition-colors ${selectedJobId === job.id ? "bg-neutral-800" : ""} ${massSelected.has(job.id) ? "bg-blue-950/20" : ""}`}
                  onClick={() => { setSelectedJobId(job.id); setNotes(""); setDeleteConfirm(false); }}>
                  <td className="px-4 py-2" onClick={e => { e.stopPropagation(); toggleMass(job.id); }}>
                    <input type="checkbox" checked={massSelected.has(job.id)} readOnly />
                  </td>
                  <td className="px-4 py-2.5">
                    <p className="text-neutral-200 truncate max-w-[200px] text-sm">{job.title}</p>
                    <p className="text-xs text-neutral-500 truncate max-w-[200px]">{job.company}</p>
                  </td>
                  <td className="px-4 py-2 text-xs text-neutral-500 truncate max-w-[120px]">{job.location}</td>
                  <td className="px-4 py-2"><StatusBadge status={job.scrape_status} /></td>
                  <td className="px-4 py-2"><StatusBadge status={job.status} /></td>
                  <td className="px-4 py-2 text-xs text-neutral-500 text-center">{job.resume_count || "—"}</td>
                </tr>
              ))}
              {!jobs.length && <tr><td colSpan={6} className="px-4 py-6 text-neutral-600 text-center text-sm">No jobs match filters.</td></tr>}
            </tbody>
          </table>
        </div>

        {/* Detail panel */}
        {selectedJob && (
          <div className="border-t border-neutral-800 grid grid-cols-2 gap-4 p-4">
            <div>
              <div className="flex items-start justify-between mb-2">
                <div>
                  <p className="text-sm font-semibold text-neutral-200">{selectedJob.title}</p>
                  <p className="text-xs text-neutral-500">{selectedJob.company} · {selectedJob.location}</p>
                  {selectedJob.salary_raw && <p className="text-xs text-green-400 mt-0.5">{selectedJob.salary_raw}{selectedJob.min_pay_yearly ? ` (₹${(selectedJob.min_pay_yearly/1000).toFixed(0)}K - ₹${(selectedJob.max_pay_yearly!/1000).toFixed(0)}K /yr)` : ""}</p>}
                </div>
                <CategoryPills job={selectedJob} />
              </div>
              <div className="flex gap-3 mb-2">
                {(selectedJob.url || selectedJob.source_url) && <a href={selectedJob.url || selectedJob.source_url} target="_blank" className="text-xs text-blue-400 hover:underline">View Job ↗</a>}
                {selectedJob.apply_url && <a href={selectedJob.apply_url} target="_blank" className="text-xs text-blue-400 hover:underline">Apply Link ↗</a>}
              </div>
              <textarea className="w-full bg-neutral-950 border border-neutral-800 rounded-md p-3 text-xs text-neutral-400 h-32 resize-none"
                value={selectedJob.description || "No description scraped yet."} readOnly />
            </div>
            <div className="space-y-3">
              <div className="flex flex-wrap gap-2">
                {JOB_ACTIONS.map(({ status, label }) => (
                  <button key={status} className="text-xs px-3 py-1.5 bg-neutral-800 border border-neutral-700 rounded-md text-neutral-300 hover:bg-neutral-700 transition-colors"
                    onClick={() => handleAction(status)}>{label}</button>
                ))}
              </div>
              <textarea className="w-full bg-neutral-950 border border-neutral-800 rounded-md p-3 text-sm text-neutral-300 h-24 resize-none focus:outline-none focus:border-neutral-600"
                placeholder="Notes about this job…" value={notes} onChange={e => setNotes(e.target.value)} />
              <button className="text-sm px-4 py-1.5 bg-neutral-800 border border-neutral-700 rounded-md text-neutral-300 hover:bg-neutral-700 transition-colors"
                onClick={() => api.updateJobState(uid, selectedJob.id, selectedJob.status).then(() => mutateJobs())}>
                Save Notes
              </button>
              <div className="border-t border-neutral-800 pt-3">
                <label className="flex items-center gap-2 text-sm text-neutral-500 cursor-pointer mb-2">
                  <input type="checkbox" checked={deleteConfirm} onChange={e => setDeleteConfirm(e.target.checked)} />
                  Confirm delete job
                </label>
                <button className="text-sm px-4 py-1.5 bg-red-950 border border-red-800 rounded-md text-red-300 hover:bg-red-900 disabled:opacity-40 transition-colors"
                  onClick={handleDelete} disabled={!deleteConfirm}>Delete Job</button>
              </div>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
