"use client";
import { useState } from "react";
import useSWR from "swr";
import { api } from "@/lib/api";
import { useUser } from "@/lib/user-context";
import { StatusBadge } from "@/components/ui/StatusBadge";
import type { Job, Project, Artifact } from "@/lib/types";

export default function TrackerPage() {
  const { activeUser } = useUser();
  const uid = activeUser?.id ?? "";

  const [statusFilter, setStatusFilter] = useState<"all" | "applied" | "not applied">("not applied");
  const [search, setSearch] = useState("");
  const [toggling, setToggling] = useState<string | null>(null);

  const { data: jobs, mutate: mutateJobs } = useSWR<Job[]>(
    uid ? `/api/jobs/${uid}/tracker` : null,
    () => api.listJobs(uid),
    { refreshInterval: 5000 }
  );

  const { data: projects } = useSWR<Project[]>(
    uid ? `/api/projects/${uid}` : null,
    () => api.listProjects(uid),
    { refreshInterval: 10000 }
  );

  const projectsByJob: Record<string, Project[]> = {};
  for (const p of projects ?? []) {
    if (p.job_id) {
      (projectsByJob[p.job_id] ??= []).push(p);
    }
  }

  const searchLower = search.trim().toLowerCase();
  const visible = (jobs ?? [])
    .filter((j) => j.resume_count > 0)
    .filter((j) => {
      const applied = j.status === "applied";
      if (statusFilter === "applied" && !applied) return false;
      if (statusFilter === "not applied" && applied) return false;
      if (searchLower) {
        const h = `${j.title} ${j.company} ${j.location} ${j.salary}`.toLowerCase();
        return h.includes(searchLower);
      }
      return true;
    });

  const getBestProject = (job: Job) => {
    const list = projectsByJob[job.id] ?? [];
    if (job.id) {
      const p = list.find((p) => p.id === job.id);
      if (p) return p;
    }
    return list.sort((a, b) => b.created_at.localeCompare(a.created_at))[0] ?? null;
  };

  const toggleApplied = async (job: Job) => {
    setToggling(job.id);
    const newStatus = job.status === "applied" ? "generated" : "applied";
    await api.updateJobState(uid, job.id, newStatus);
    await mutateJobs();
    setToggling(null);
  };

  const DownloadButton = ({ project }: { project: Project | null }) => {
    const [artifact, setArtifact] = useState<Artifact | null>(null);
    const [loaded, setLoaded] = useState(false);

    const load = async () => {
      if (loaded || !project) return;
      const arts = await api.listArtifacts(uid, project.id);
      const best = arts
        .filter((a) => a.mime_type === "application/pdf")
        .sort((a, b) => (b.iteration ?? -1) - (a.iteration ?? -1))[0] ?? null;
      setArtifact(best);
      setLoaded(true);
    };

    if (!project) return <span className="text-xs text-neutral-600">No project</span>;
    if (!loaded) return (
      <button className="text-xs text-blue-400 hover:underline" onClick={load}>Load resume</button>
    );
    if (!artifact) return <span className="text-xs text-neutral-600">No PDF</span>;

    const url = api.artifactDownloadUrl(uid, project.id, artifact.id);
    return (
      <a href={url} download className="text-xs text-blue-400 hover:underline">
        ↓ {artifact.file_name}
      </a>
    );
  };

  if (!uid) return <p className="text-neutral-500 text-sm">Select a profile first.</p>;

  return (
    <div className="flex flex-col gap-3">
      {/* Filters */}
      <div className="flex gap-2 flex-wrap items-center">
        <select
          className="text-xs bg-neutral-900 border border-neutral-700 rounded px-2 py-1 text-neutral-300"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as typeof statusFilter)}
        >
          <option value="all">All statuses</option>
          <option value="not applied">Not applied</option>
          <option value="applied">Applied</option>
        </select>
        <input
          className="text-xs bg-neutral-900 border border-neutral-700 rounded px-2 py-1 text-neutral-100 w-44"
          placeholder="Search…" value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <span className="text-xs text-neutral-600">{visible.length} jobs</span>
      </div>

      {/* Job cards */}
      {visible.length === 0 && (
        <p className="text-xs text-neutral-600">
          No jobs with generated resumes. Use Batch Processing to generate resumes first.
        </p>
      )}
      <div className="space-y-2">
        {visible.map((job) => {
          const project = getBestProject(job);
          const isApplied = job.status === "applied";
          const applyLink = job.apply_url || job.url || job.source_url;
          return (
            <div key={job.id} className="border border-neutral-800 rounded p-3 flex items-center gap-3">
              <div className="flex-1 min-w-0">
                <p className="text-xs font-semibold text-neutral-200 truncate">
                  {job.title}
                  <span className="text-neutral-500 font-normal ml-1">@ {job.company}</span>
                </p>
                {(job.location || job.salary) && (
                  <p className="text-xs text-neutral-600">
                    {[job.location, job.salary].filter(Boolean).join(" · ")}
                  </p>
                )}
              </div>
              <div className="flex items-center gap-3 shrink-0">
                {applyLink ? (
                  <a href={applyLink} target="_blank" className="text-xs px-2 py-1 bg-blue-900 border border-blue-700 rounded text-blue-200 hover:bg-blue-800">
                    Apply Now ↗
                  </a>
                ) : (
                  <span className="text-xs text-neutral-600">No apply link</span>
                )}
                <DownloadButton project={project} />
                <label className="flex items-center gap-1.5 text-xs text-neutral-400 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={isApplied}
                    disabled={toggling === job.id}
                    onChange={() => toggleApplied(job)}
                  />
                  Applied
                </label>
                <StatusBadge status={job.status} />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
