import { useEffect, useState, useMemo } from "react";
import { useNavigate } from "react-router-dom";

const API = "/api";

interface ScrapedJob {
  id: string;
  title: string;
  company: string;
  location: string;
  link: string;
  pay: string;
  posted_date: string;
  description: string;
  technical_skills: string[];
  metadata: string[];
  snippet: string[];
  raw_attributes: string[];
  applying_for: string;
  required_skills: string[];
  preferred_skills: string[];
  key_responsibilities: string[];
  keywords: string[];
  experience_years: number | null;
  seniority_level: string;
  status: string;
  scrape_session: string;
  project_id: string;
  resume_error_project_id: string;
  resume_error_path: string;
  resume_error_message: string;
  applied: boolean;
  created_at: string;
  scrape_source: string;
}

interface Artifact {
  id: number;
  file_name: string;
  artifact_type: string;
  storage_path: string;
  mime_type: string;
  size_bytes: number | null;
}

const FALLBACK_DOWNLOAD_NAME = "resume";

function sanitizeFileNamePart(value: string, fallback: string): string {
  const cleaned = value
    .trim()
    .replace(/[<>:"/\\|?*]/g, " ")
    .replace(/\s+/g, " ")
    .replace(/\.+$/g, "")
    .trim();
  return cleaned || fallback;
}

function getArtifactExtension(artifact: Artifact): string {
  const fromName = artifact.file_name.match(/(\.[a-zA-Z0-9]+)$/)?.[1];
  if (fromName) return fromName.toLowerCase();
  if (artifact.mime_type === "application/pdf") return ".pdf";
  if (artifact.mime_type === "text/markdown") return ".md";
  return "";
}

function getJobDownloadFileName(job: ScrapedJob, artifact: Artifact): string {
  const title = sanitizeFileNamePart(job.title || "", "job");
  const company = sanitizeFileNamePart(job.company || "", "company");
  const extension = getArtifactExtension(artifact);
  return sanitizeFileNamePart(
    `${title} - ${company}${extension}`,
    `${FALLBACK_DOWNLOAD_NAME}${extension}`,
  );
}

function formatSeniorityLabel(seniorityLevel: string): string {
  if (!seniorityLevel.trim()) return "—";
  return seniorityLevel
    .split("_")
    .filter(Boolean)
    .map((part) => part[0].toUpperCase() + part.slice(1).toLowerCase())
    .join(" ");
}

export default function JobLibraryPage() {
  const navigate = useNavigate();
  const [jobs, setJobs] = useState<ScrapedJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedUid, setSelectedUid] = useState<string>("");

  // Filters
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [resumeFilter, setResumeFilter] = useState<"" | "has" | "none">("");
  const [appliedFilter, setAppliedFilter] = useState<
    "" | "applied" | "not_applied"
  >("not_applied");
  const [companyFilter, setCompanyFilter] = useState("");
  const [hasDescFilter, setHasDescFilter] = useState(false);
  const [hasSkillsFilter, setHasSkillsFilter] = useState(false);
  const [hasSalaryFilter, setHasSalaryFilter] = useState(false);
  const [sortBy, setSortBy] = useState<"date" | "company" | "title">(
    "date",
  );

  // Selection
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);

  // Artifacts
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [artifactsLoading, setArtifactsLoading] = useState(false);

  useEffect(() => {
    fetchUsers();
    fetchJobs();
  }, []);

  useEffect(() => {
    if (selectedUid && selectedJobId) {
      const job = jobs.find((j) => j.id === selectedJobId);
      if (job?.project_id) loadArtifacts(job.project_id);
      else setArtifacts([]);
    }
  }, [selectedJobId, selectedUid, jobs]);

  async function fetchUsers() {
    try {
      const res = await fetch(`${API}/users`);
      const data: { id: string }[] = await res.json();
      if (data.length > 0) setSelectedUid(data[0].id);
    } catch {
      /* ignore */
    }
  }

  async function fetchJobs() {
    setLoading(true);
    try {
      const res = await fetch(`${API}/jobs`);
      setJobs(await res.json());
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  }

  async function loadArtifacts(projectId: string) {
    if (!selectedUid) return;
    setArtifactsLoading(true);
    try {
      const res = await fetch(
        `${API}/users/${selectedUid}/projects/${projectId}/artifacts`,
      );
      setArtifacts(await res.json());
    } catch {
      setArtifacts([]);
    } finally {
      setArtifactsLoading(false);
    }
  }

  async function deleteJob(id: string) {
    if (!confirm("Delete this job listing entirely?")) return;
    try {
      await fetch(`${API}/jobs/${id}`, { method: "DELETE" });
      if (selectedJobId === id) setSelectedJobId(null);
      fetchJobs();
    } catch {
      /* ignore */
    }
  }

  async function toggleApplied(job: ScrapedJob) {
    try {
      const newApplied = !job.applied;
      await fetch(`${API}/jobs/${job.id}/apply`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ applied: newApplied }),
      });
      fetchJobs();
    } catch {
      /* ignore */
    }
  }

  async function deleteResume(job: ScrapedJob) {
    if (
      !confirm(
        "Delete this job's resume? It will re-appear in Batch Processing.",
      )
    )
      return;
    try {
      if (job.project_id && selectedUid)
        await fetch(`${API}/users/${selectedUid}/projects/${job.project_id}`, {
          method: "DELETE",
        });
      await fetch(`${API}/jobs/${job.id}/project`, { method: "DELETE" });
      setArtifacts([]);
      fetchJobs();
    } catch {
      /* ignore */
    }
  }

  function remakeResume(job: ScrapedJob) {
    navigate(`/generate?job_id=${encodeURIComponent(job.id)}&remake=1`);
  }

  async function downloadArtifact(artifact: Artifact, filename: string) {
    const url = `${API}/artifacts/download?path=${encodeURIComponent(
      artifact.storage_path,
    )}&filename=${encodeURIComponent(filename)}`;
    const res = await fetch(url);
    if (!res.ok) {
      alert(`Download failed (${res.status}). The artifact may be missing.`);
      return;
    }
    const blob = await res.blob();
    const objectUrl = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = objectUrl;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(objectUrl);
  }

  // Unique companies for filter dropdown
  const companies = useMemo(
    () => [...new Set(jobs.map((j) => j.company).filter(Boolean))].sort(),
    [jobs],
  );

  const filteredJobs = useMemo(() => {
    let result = jobs.filter((job) => {
      if (statusFilter && job.status !== statusFilter) return false;
      if (resumeFilter === "has" && !job.project_id) return false;
      if (resumeFilter === "none" && job.project_id) return false;
      if (appliedFilter === "applied" && !job.applied) return false;
      if (appliedFilter === "not_applied" && job.applied) return false;
      if (companyFilter && job.company !== companyFilter) return false;
      if (hasSalaryFilter && !job.pay) return false;
      if (hasDescFilter && !job.description) return false;
      if (hasSkillsFilter && !job.technical_skills?.length) return false;
      if (searchQuery) {
        const q = searchQuery.toLowerCase();
        const text = [
          job.title,
          job.company,
          job.location,
          job.description,
          job.applying_for,
          job.seniority_level,
          job.experience_years?.toString() || "",
          ...(job.technical_skills || []),
          ...(job.required_skills || []),
          ...(job.preferred_skills || []),
          ...(job.key_responsibilities || []),
          ...(job.keywords || []),
          ...(job.metadata || []),
          ...(job.snippet || []),
          ...(job.raw_attributes || []),
        ]
          .filter(Boolean)
          .join(" ")
          .toLowerCase();
        if (!text.includes(q)) return false;
      }
      return true;
    });

    result.sort((a, b) => {
      if (sortBy === "company")
        return (a.company || "").localeCompare(b.company || "");
      if (sortBy === "title")
        return (a.title || "").localeCompare(b.title || "");
      return (b.created_at || "").localeCompare(a.created_at || "");
    });

    return result;
  }, [
    jobs,
    searchQuery,
    statusFilter,
    resumeFilter,
    appliedFilter,
    companyFilter,
    hasSalaryFilter,
    hasDescFilter,
    hasSkillsFilter,
    sortBy,
  ]);

  const selectedJob = useMemo(
    () => jobs.find((j) => j.id === selectedJobId) || null,
    [jobs, selectedJobId],
  );

  useEffect(() => {
    if (
      filteredJobs.length > 0 &&
      (!selectedJobId || !filteredJobs.find((j) => j.id === selectedJobId))
    ) {
      setSelectedJobId(filteredJobs[0].id);
    }
  }, [filteredJobs, selectedJobId]);

  const bestArtifact =
    artifacts.find((a) => a.artifact_type === "final_pdf") ??
    artifacts.find((a) => a.mime_type === "application/pdf") ??
    artifacts[0] ??
    null;

  const activeFilterCount = [
    statusFilter,
    resumeFilter,
    appliedFilter,
    companyFilter,
    hasSalaryFilter,
    hasDescFilter,
    hasSkillsFilter,
  ].filter(Boolean).length;

  function resetFilters() {
    setStatusFilter("");
    setResumeFilter("");
    setAppliedFilter("");
    setCompanyFilter("");
    setHasSalaryFilter(false);
    setHasDescFilter(false);
    setHasSkillsFilter(false);
    setSearchQuery("");
    setSortBy("date");
  }

  return (
    <div style={{ display: "flex", height: "100%", overflow: "hidden" }}>
      {/* ── Left Panel ─────────────────────────────────────────────────── */}
      <div
        style={{
          width: 400,
          flexShrink: 0,
          display: "flex",
          flexDirection: "column",
          height: "100%",
          borderRight: "1px solid var(--line)",
        }}
      >
        {/* Filter header */}
        <div
          style={{
            flexShrink: 0,
            background: "var(--bg-panel)",
            borderBottom: "1px solid var(--line)",
          }}
        >
          <div
            style={{
              padding: "10px 14px",
              display: "flex",
              flexDirection: "column",
              gap: 8,
            }}
          >
            {/* Title row */}
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
              }}
            >
              <span className="bp-label">
                LIBRARY ({filteredJobs.length}/{jobs.length})
              </span>
              <div style={{ display: "flex", gap: 6 }}>
                {activeFilterCount > 0 && (
                  <button
                    className="btn-ghost"
                    style={{ height: 22, padding: "0 8px", fontSize: 9 }}
                    onClick={resetFilters}
                  >
                    CLEAR ({activeFilterCount})
                  </button>
                )}
                <button
                  className="btn-ghost"
                  style={{ height: 22, padding: "0 8px", fontSize: 9 }}
                  onClick={fetchJobs}
                >
                  ↻
                </button>
              </div>
            </div>

            {/* Search */}
            <input
              type="text"
              placeholder="Search title, company, skills, description..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              style={inputStyle}
            />

            {/* Row 1: Status + Resume + Applied */}
            <div style={{ display: "flex", gap: 8 }}>
              <select
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                style={{ ...selectStyle, flex: 1 }}
              >
                <option value="">Status</option>
                <option value="nlp_done">NLP Done</option>
                <option value="enriched">Enriched</option>
                <option value="basic">Basic</option>
              </select>
              <select
                value={resumeFilter}
                onChange={(e) =>
                  setResumeFilter(e.target.value as "" | "has" | "none")
                }
                style={{ ...selectStyle, flex: 1 }}
              >
                <option value="">Resume</option>
                <option value="has">Has Resume</option>
                <option value="none">No Resume</option>
              </select>
              <select
                value={appliedFilter}
                onChange={(e) =>
                  setAppliedFilter(
                    e.target.value as "" | "applied" | "not_applied",
                  )
                }
                style={{ ...selectStyle, flex: 1 }}
              >
                <option value="">Application</option>
                <option value="applied">Applied</option>
                <option value="not_applied">Not Applied</option>
              </select>
            </div>

            {/* Row 2: Company + Sort */}
            <div style={{ display: "flex", gap: 8 }}>
              <select
                value={companyFilter}
                onChange={(e) => setCompanyFilter(e.target.value)}
                style={{ ...selectStyle, flex: 2 }}
              >
                <option value="">All Companies</option>
                {companies.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
              <select
                value={sortBy}
                onChange={(e) => setSortBy(e.target.value as typeof sortBy)}
                style={{ ...selectStyle, flex: 1 }}
              >
                <option value="date">Newest</option>
                <option value="company">Company</option>
                <option value="title">Title</option>
              </select>
            </div>

            {/* Row 3: Toggle chips */}
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              {(
                [
                  [
                    "hasSalaryFilter",
                    "HAS PAY",
                    hasSalaryFilter,
                    () => setHasSalaryFilter((v) => !v),
                  ],
                  [
                    "hasDescFilter",
                    "HAS DESC",
                    hasDescFilter,
                    () => setHasDescFilter((v) => !v),
                  ],
                  [
                    "hasSkillsFilter",
                    "HAS SKILLS",
                    hasSkillsFilter,
                    () => setHasSkillsFilter((v) => !v),
                  ],
                ] as [string, string, boolean, () => void][]
              ).map(([key, label, active, toggle]) => (
                <button
                  key={key}
                  onClick={toggle}
                  style={{
                    fontFamily: "var(--font-mono)",
                    fontSize: 9,
                    fontWeight: 700,
                    letterSpacing: "0.08em",
                    padding: "3px 8px",
                    height: 22,
                    cursor: "pointer",
                    border: `1px solid ${active ? "var(--cyan-bright)" : "var(--line)"}`,
                    background: active
                      ? "rgba(43,125,233,0.15)"
                      : "transparent",
                    color: active ? "var(--cyan-bright)" : "var(--muted)",
                  }}
                >
                  {active ? "✓ " : ""}
                  {label}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Job list */}
        <div style={{ flex: 1, overflowY: "auto" }}>
          {loading && (
            <div
              style={{
                padding: 24,
                textAlign: "center",
                color: "var(--muted)",
                fontSize: 11,
              }}
            >
              LOADING...
            </div>
          )}
          {!loading && filteredJobs.length === 0 && (
            <div
              style={{
                padding: 40,
                textAlign: "center",
                color: "var(--muted)",
                fontSize: 11,
              }}
            >
              NO JOBS MATCH YOUR FILTERS
              {activeFilterCount > 0 && (
                <div style={{ marginTop: 10 }}>
                  <button
                    className="btn-ghost"
                    style={{ fontSize: 10 }}
                    onClick={resetFilters}
                  >
                    CLEAR FILTERS
                  </button>
                </div>
              )}
            </div>
          )}
          {filteredJobs.map((job) => {
            const isSel = selectedJobId === job.id;
            return (
              <div
                key={job.id}
                onClick={() => setSelectedJobId(job.id)}
                className={`library-job-card ${isSel ? "selected" : ""}`}
              >
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "flex-start",
                    marginBottom: 3,
                  }}
                >
                  <div
                    style={{
                      fontWeight: 600,
                      color: isSel ? "var(--cyan-bright)" : "var(--white)",
                      fontSize: 12,
                      flex: 1,
                      minWidth: 0,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {job.title || "Untitled"}
                  </div>
                  <div style={{ display: "flex", gap: 4, flexShrink: 0 }}>
                    {job.applied && (
                      <span
                        style={{
                          fontSize: 8,
                          padding: "1px 5px",
                          background: "rgba(58,201,122,0.12)",
                          color: "var(--green)",
                          border: "1px solid var(--green)",
                          fontWeight: 700,
                        }}
                      >
                        ✓ APPLIED
                      </span>
                    )}
                    {job.project_id && (
                      <span
                        style={{
                          fontSize: 8,
                          padding: "1px 5px",
                          background: "rgba(43,125,233,0.12)",
                          color: "var(--cyan-bright)",
                          border: "1px solid var(--cyan-bright)",
                          fontWeight: 700,
                        }}
                      >
                        ✓ RESUME
                      </span>
                    )}
                    {!job.project_id && job.resume_error_path && (
                      <span
                        style={{
                          fontSize: 8,
                          padding: "1px 5px",
                          background: "rgba(224,82,99,0.10)",
                          color: "var(--red)",
                          border: "1px solid var(--red)",
                          fontWeight: 700,
                        }}
                      >
                        FAILED
                      </span>
                    )}
                  </div>
                </div>
                <div
                  style={{
                    color: "var(--white-dim)",
                    fontSize: 11,
                    marginBottom: 5,
                  }}
                >
                  {job.company || "Unknown"}
                </div>
                <div
                  style={{
                    display: "flex",
                    gap: 6,
                    flexWrap: "wrap",
                    alignItems: "center",
                  }}
                >
                  <span style={{ color: "var(--muted)", fontSize: 10 }}>
                    {job.location || "No location"}
                  </span>
                  {job.pay && (
                    <span
                      style={{
                        color: "var(--green)",
                        fontSize: 10,
                        fontWeight: 700,
                      }}
                    >
                      • {job.pay}
                    </span>
                  )}
                  {job.technical_skills?.length > 0 && (
                    <span style={{ color: "var(--cyan-bright)", fontSize: 9 }}>
                      • {job.technical_skills.length} skills
                    </span>
                  )}
                  <span
                    style={{
                      marginLeft: "auto",
                      fontSize: 8,
                      padding: "1px 5px",
                      color:
                        job.status === "nlp_done"
                          ? "var(--green)"
                          : "var(--muted)",
                      border: `1px solid ${job.status === "nlp_done" ? "var(--green)" : "var(--line)"}`,
                    }}
                  >
                    {job.status.toUpperCase()}
                  </span>
                  <span
                    style={{
                      fontSize: 8,
                      padding: "1px 5px",
                      color: job.scrape_source === 'linkedin' ? '#0a66c2' : 'var(--muted)',
                      border: `1px solid ${job.scrape_source === 'linkedin' ? '#0a66c2' : 'var(--line)'}`,
                      fontWeight: 700,
                    }}
                  >
                    {job.scrape_source === 'linkedin' ? 'LI' : 'IN'}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* ── Right: Detail ───────────────────────────────────────────────── */}
      <div
        style={{
          flex: 1,
          display: "flex",
          flexDirection: "column",
          height: "100%",
          overflow: "hidden",
          background: "var(--bg-panel)",
        }}
      >
        {selectedJob ? (
          <>
            {/* Sticky header */}
            <div
              style={{
                flexShrink: 0,
                padding: "18px 28px",
                borderBottom: "1px solid var(--line)",
              }}
            >
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "flex-start",
                  gap: 16,
                }}
              >
                <div style={{ minWidth: 0 }}>
                  <h1 style={{ margin: "0 0 5px 0", fontSize: 20 }}>
                    {selectedJob.title}
                  </h1>
                  <div
                    style={{
                      fontSize: 14,
                      color: "var(--cyan-bright)",
                      fontWeight: 600,
                      marginBottom: 3,
                    }}
                  >
                    {selectedJob.company}
                  </div>
                  <div style={{ fontSize: 11, color: "var(--muted)" }}>
                    {selectedJob.location}
                    {selectedJob.posted_date &&
                      ` • Posted ${selectedJob.posted_date}`}
                  </div>
                </div>
                <div
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    gap: 6,
                    flexShrink: 0,
                  }}
                >
                  <button
                    className="btn-ghost"
                    style={{
                      color: selectedJob.applied
                        ? "var(--green)"
                        : "var(--white)",
                      borderColor: selectedJob.applied
                        ? "var(--green)"
                        : "var(--line)",
                      fontSize: 11,
                    }}
                    onClick={() => toggleApplied(selectedJob)}
                  >
                    {selectedJob.applied ? "✓ APPLIED" : "MARK APPLIED"}
                  </button>
                  <a
                    href={selectedJob.link}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{ textDecoration: "none" }}
                  >
                    <button
                      className="btn-ghost"
                      style={{
                        width: "100%",
                        justifyContent: "center",
                        fontSize: 11,
                      }}
                    >
                      OPEN IN {selectedJob.scrape_source === 'linkedin' ? 'LINKEDIN' : 'INDEED'} ↗
                    </button>
                  </a>
                  <button
                    className="btn-ghost"
                    style={{
                      color: "var(--red)",
                      borderColor: "var(--red)",
                      fontSize: 11,
                    }}
                    onClick={() => deleteJob(selectedJob.id)}
                  >
                    DELETE JOB
                  </button>
                </div>
              </div>
            </div>

            {/* Scrollable body */}
            <div
              style={{
                flex: 1,
                overflowY: "auto",
                padding: "20px 28px",
                display: "flex",
                flexDirection: "column",
                gap: 20,
              }}
            >
              {/* ── Metadata grid ── */}
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))",
                  gap: 1,
                  border: "1px solid var(--line)",
                }}
              >
                {[
                  ["Status", selectedJob.status.toUpperCase()],
                  ["Scrape Session", selectedJob.scrape_session || "—"],
                  ["Posted", selectedJob.posted_date || "—"],
                  [
                    "Added",
                    selectedJob.created_at
                      ? new Date(selectedJob.created_at).toLocaleDateString(
                          "en-GB",
                        )
                      : "—",
                  ],
                  ["Pay (Raw)", selectedJob.pay || "—"],
                  ["Job ID", selectedJob.id],
                ].map(([label, value]) => (
                  <div
                    key={label}
                    style={{
                      padding: "10px 14px",
                      background: "var(--bg-input)",
                      borderRight: "1px solid var(--line-dim)",
                      borderBottom: "1px solid var(--line-dim)",
                    }}
                  >
                    <div
                      style={{
                        fontSize: 9,
                        color: "var(--muted)",
                        fontWeight: 700,
                        letterSpacing: "0.1em",
                        marginBottom: 4,
                      }}
                    >
                      {label}
                    </div>
                    <div
                      style={{
                        fontSize: 11,
                        color: "var(--white)",
                        wordBreak: "break-all",
                      }}
                    >
                      {value}
                    </div>
                  </div>
                ))}
              </div>

              {/* ── Pay tags + metadata chips ── */}
              {(selectedJob.pay ||
                selectedJob.metadata?.length > 0 ||
                selectedJob.raw_attributes?.length > 0) && (
                <div>
                  <div className="bp-label" style={{ marginBottom: 8 }}>
                    JOB ATTRIBUTES
                  </div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                    {selectedJob.pay && (
                      <span
                        className="detail-tag"
                        style={{
                          color: "var(--green)",
                          borderColor: "var(--green)",
                          background: "rgba(30,165,88,0.05)",
                        }}
                      >
                        {selectedJob.pay}
                      </span>
                    )}
                    {selectedJob.metadata?.map((m, i) => (
                      <span key={`m-${i}`} className="detail-tag">
                        {m}
                      </span>
                    ))}
                    {selectedJob.raw_attributes?.map((r, i) => (
                      <span
                        key={`r-${i}`}
                        className="detail-tag"
                        style={{
                          color: "var(--white-dim)",
                          borderColor: "var(--line)",
                        }}
                      >
                        {r}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* ── Snippet ── */}
              {selectedJob.snippet?.length > 0 && (
                <div>
                  <div className="bp-label" style={{ marginBottom: 8 }}>
                    SNIPPET
                  </div>
                  <div
                    style={{ display: "flex", flexDirection: "column", gap: 4 }}
                  >
                    {selectedJob.snippet.map((s, i) => (
                      <div
                        key={i}
                        style={{
                          fontSize: 12,
                          color: "var(--white-dim)",
                          lineHeight: 1.5,
                          padding: "6px 12px",
                          background: "var(--bg-input)",
                          borderLeft: "2px solid var(--cyan-dim)",
                        }}
                      >
                        {s}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* ── Agent Analysis ── */}
              {(selectedJob.applying_for ||
                selectedJob.experience_years != null ||
                selectedJob.seniority_level ||
                selectedJob.required_skills?.length > 0 ||
                selectedJob.preferred_skills?.length > 0 ||
                selectedJob.key_responsibilities?.length > 0 ||
                selectedJob.keywords?.length > 0) && (
                <div>
                  <div className="bp-label" style={{ marginBottom: 8 }}>
                    AGENT JOB ANALYSIS
                  </div>
                  <div
                    style={{
                      display: "grid",
                      gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))",
                      gap: 1,
                      border: "1px solid var(--line)",
                      marginBottom: 10,
                    }}
                  >
                    {[
                      ["Role", selectedJob.applying_for || "—"],
                      [
                        "Experience",
                        selectedJob.experience_years != null
                          ? `${selectedJob.experience_years}+ years`
                          : "—",
                      ],
                      [
                        "Seniority",
                        formatSeniorityLabel(selectedJob.seniority_level),
                      ],
                    ].map(([label, value]) => (
                      <div
                        key={label}
                        style={{
                          padding: "10px 12px",
                          background: "var(--bg-input)",
                          borderRight: "1px solid var(--line-dim)",
                          borderBottom: "1px solid var(--line-dim)",
                        }}
                      >
                        <div
                          style={{
                            fontSize: 9,
                            color: "var(--muted)",
                            fontWeight: 700,
                            letterSpacing: "0.1em",
                            marginBottom: 4,
                          }}
                        >
                          {label}
                        </div>
                        <div style={{ fontSize: 11, color: "var(--white)" }}>
                          {value}
                        </div>
                      </div>
                    ))}
                  </div>

                  {selectedJob.required_skills?.length > 0 && (
                    <div style={{ marginBottom: 8 }}>
                      <div className="bp-label" style={{ marginBottom: 6 }}>
                        REQUIRED SKILLS ({selectedJob.required_skills.length})
                      </div>
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                        {selectedJob.required_skills.map((s) => (
                          <span key={`req-${s}`} className="skill-chip">
                            {s}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  {selectedJob.preferred_skills?.length > 0 && (
                    <div style={{ marginBottom: 8 }}>
                      <div className="bp-label" style={{ marginBottom: 6 }}>
                        PREFERRED SKILLS ({selectedJob.preferred_skills.length})
                      </div>
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                        {selectedJob.preferred_skills.map((s) => (
                          <span
                            key={`pref-${s}`}
                            className="detail-tag"
                            style={{
                              color: "var(--white-dim)",
                              borderColor: "var(--line)",
                            }}
                          >
                            {s}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  {selectedJob.key_responsibilities?.length > 0 && (
                    <div style={{ marginBottom: 8 }}>
                      <div className="bp-label" style={{ marginBottom: 6 }}>
                        KEY RESPONSIBILITIES
                      </div>
                      <div
                        style={{ display: "flex", flexDirection: "column", gap: 4 }}
                      >
                        {selectedJob.key_responsibilities.map((item, i) => (
                          <div
                            key={`resp-${i}`}
                            style={{
                              fontSize: 12,
                              color: "var(--white-dim)",
                              lineHeight: 1.5,
                              padding: "6px 12px",
                              background: "var(--bg-input)",
                              borderLeft: "2px solid var(--line-dim)",
                            }}
                          >
                            {item}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {selectedJob.keywords?.length > 0 && (
                    <div>
                      <div className="bp-label" style={{ marginBottom: 6 }}>
                        KEYWORDS ({selectedJob.keywords.length})
                      </div>
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                        {selectedJob.keywords.map((k) => (
                          <span key={`kw-${k}`} className="detail-tag">
                            {k}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* ── Technical Skills ── */}
              {selectedJob.technical_skills?.length > 0 && (
                <div>
                  <div className="bp-label" style={{ marginBottom: 8 }}>
                    TECHNICAL SKILLS ({selectedJob.technical_skills.length})
                  </div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                    {selectedJob.technical_skills.map((s) => (
                      <span key={s} className="skill-chip">
                        {s}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* ── Resume ── */}
              <div
                style={{
                  padding: "14px 18px",
                  border: "1px solid var(--line)",
                  background: "var(--bg-input)",
                }}
              >
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    marginBottom: selectedJob.project_id ? 12 : 0,
                  }}
                >
                  <span className="bp-label">GENERATED RESUME</span>
                  {selectedJob.project_id && (
                    <div style={{ display: "flex", gap: 6 }}>
                      <button
                        className="btn-ghost"
                        style={{ height: 26, padding: "0 10px", fontSize: 10 }}
                        onClick={() => remakeResume(selectedJob)}
                      >
                        REMAKE RESUME
                      </button>
                      {bestArtifact && (
                        <button
                          className="btn-ghost"
                          style={{
                            height: 26,
                            padding: "0 10px",
                            fontSize: 10,
                          }}
                          onClick={() =>
                            downloadArtifact(
                              bestArtifact,
                              getJobDownloadFileName(selectedJob, bestArtifact),
                            )
                          }
                        >
                          ↓ DOWNLOAD PDF
                        </button>
                      )}
                      <button
                        className="btn-ghost"
                        style={{
                          height: 26,
                          padding: "0 10px",
                          fontSize: 10,
                          color: "var(--red)",
                          borderColor: "var(--red)",
                        }}
                        onClick={() => deleteResume(selectedJob)}
                      >
                        DELETE RESUME
                      </button>
                    </div>
                  )}
                  {!selectedJob.project_id && (
                    <button
                      className="btn-ghost"
                      style={{ height: 26, padding: "0 10px", fontSize: 10 }}
                      onClick={() => remakeResume(selectedJob)}
                    >
                      MAKE RESUME
                    </button>
                  )}
                </div>
                {!selectedJob.project_id && (
                  <div style={{ color: "var(--muted)", fontSize: 11 }}>
                    {selectedJob.resume_error_path
                      ? selectedJob.resume_error_message || "Resume generation failed."
                      : "No resume generated. Use Batch Processing or the Generate page."}
                    {selectedJob.resume_error_path && (
                      <div style={{ marginTop: 10 }}>
                        <button
                          className="btn-ghost"
                          style={{ height: 26, padding: "0 10px", fontSize: 10 }}
                          onClick={() => {
                            const artifact = {
                              id: 0,
                              file_name: "error.md",
                              artifact_type: "error_md",
                              storage_path: selectedJob.resume_error_path,
                              mime_type: "text/markdown",
                              size_bytes: null,
                            };
                            downloadArtifact(
                              artifact,
                              getJobDownloadFileName(selectedJob, artifact),
                            );
                          }}
                        >
                          DOWNLOAD ERROR
                        </button>
                      </div>
                    )}
                  </div>
                )}
                {selectedJob.project_id && artifactsLoading && (
                  <div style={{ color: "var(--muted)", fontSize: 11 }}>
                    Loading...
                  </div>
                )}
                {selectedJob.project_id &&
                  !artifactsLoading &&
                  artifacts.length === 0 && (
                    <div style={{ color: "var(--yellow)", fontSize: 11 }}>
                      Project linked but no artifacts (generation may have
                      failed).
                    </div>
                  )}
                {selectedJob.project_id &&
                  !artifactsLoading &&
                  artifacts.length > 0 && (
                    <div
                      style={{
                        display: "flex",
                        flexDirection: "column",
                        gap: 5,
                      }}
                    >
                      <select
                        onChange={(e) => {
                          const a = artifacts.find(
                            (x) => x.id.toString() === e.target.value,
                          );
                          if (a) {
                            downloadArtifact(a, getJobDownloadFileName(selectedJob, a));
                            e.target.value = "";
                          }
                        }}
                        style={{
                          fontFamily: "var(--font-mono)",
                          fontSize: 11,
                          fontWeight: 600,
                          color: "var(--white)",
                          background: "var(--bg-panel)",
                          border: "1px solid var(--line-dim)",
                          padding: "6px 8px",
                          height: 30,
                          outline: "none",
                          width: "100%",
                          borderRadius: 0,
                          cursor: "pointer",
                        }}
                        defaultValue=""
                      >
                        <option value="" disabled>
                          Select an artifact to download...
                        </option>
                        {artifacts.map((a) => (
                          <option key={a.id} value={a.id}>
                            {a.file_name}{" "}
                            {a.size_bytes
                              ? `(${Math.round(a.size_bytes / 1024)} KB)`
                              : ""}
                          </option>
                        ))}
                      </select>

                      {/* PDF Preview */}
                      {bestArtifact && (
                        <div
                          style={{
                            marginTop: 12,
                            borderTop: "1px solid var(--line)",
                            paddingTop: 12,
                          }}
                        >
                          <div className="bp-label" style={{ marginBottom: 8 }}>
                            PREVIEW
                          </div>
                          <iframe
                            src={`${API}/artifacts/download?path=${encodeURIComponent(bestArtifact.storage_path)}&disposition=inline`}
                            style={{
                              width: "100%",
                              height: "500px",
                              border: "1px solid var(--line)",
                              background: "var(--bg)",
                            }}
                            title="Resume Preview"
                          />
                        </div>
                      )}
                    </div>
                  )}
              </div>

              {/* ── Full Description ── */}
              <div>
                <div className="bp-label" style={{ marginBottom: 10 }}>
                  FULL DESCRIPTION
                </div>
                <div
                  style={{
                    fontSize: 13,
                    color: "var(--white)",
                    lineHeight: 1.7,
                    whiteSpace: "pre-wrap",
                    fontFamily: "system-ui, -apple-system, sans-serif",
                  }}
                >
                  {selectedJob.description || (
                    <span style={{ color: "var(--muted)" }}>
                      No description (Phase 2 scrape required).
                    </span>
                  )}
                </div>
              </div>
            </div>
          </>
        ) : (
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              height: "100%",
              color: "var(--muted)",
              fontSize: 12,
            }}
          >
            {jobs.length > 0
              ? "SELECT A JOB TO VIEW DETAILS"
              : "NO SCRAPED JOBS YET"}
          </div>
        )}
      </div>
    </div>
  );
}

const inputStyle: React.CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: 11,
  fontWeight: 600,
  color: "var(--white)",
  background: "var(--bg-input)",
  border: "1px solid var(--line)",
  padding: "6px 8px",
  height: 30,
  outline: "none",
  width: "100%",
  borderRadius: 0,
};
const selectStyle: React.CSSProperties = {
  ...inputStyle,
  cursor: "pointer",
  appearance: "none",
  WebkitAppearance: "none",
  backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M0 0l5 6 5-6z' fill='%236a9cc8'/%3E%3C/svg%3E")`,
  backgroundRepeat: "no-repeat",
  backgroundPosition: "right 8px center",
  paddingRight: "24px",
};
