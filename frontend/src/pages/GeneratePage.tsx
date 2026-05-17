import { useCallback, useEffect, useRef, useState } from 'react'
import { SECTIONS, DEFAULT_OMISSIONS, type Omissions } from './ProfilesPage'

// ── Types ──────────────────────────────────────────────────────────────────
interface User {
  id: string
  display_name: string
}
interface Project {
  id: string
  name: string
  status: string
  job_description: string
  created_at: string
}
interface ParsedJob {
  id: string
  title: string
  company: string
  project_id?: string | null
  description?: string
  technical_skills?: string[]
  required_skills?: string[]
  preferred_skills?: string[]
  keywords?: string[]
}
interface Artifact {
  id: number
  file_name: string
  artifact_type: string
  storage_path: string
  mime_type: string
  size_bytes: number | null
}
interface LogEntry {
  ts: number
  stream: string
  text: string
  level: string
}
interface RunStatus {
  state: string
  model: string
  current_step: string
  active_agent: string
  active_task: string
  iteration: string
  output_dir: string
  final_pdf: string
  run_started_at: number | null
  run_finished_at: number | null
  exit_code: number | null
}

const API = '/api'
const MIN_SIDEBAR = 280
const MAX_SIDEBAR = 900
const DEFAULT_SIDEBAR = 420
const MAX_ITERATIONS = 5

const MODEL_PRESETS: Record<string, { model: string; key_env: string }> = {
  'Mistral Large':         { model: 'mistral/mistral-large-latest',              key_env: 'MISTRAL_API_KEY' },
  'Mistral Medium':        { model: 'mistral/mistral-medium-latest',             key_env: 'MISTRAL_API_KEY' },
  'Gemini 3 Flash':        { model: 'gemini/gemini-3-flash-preview',             key_env: 'GEMINI_KEY' },
  'Gemini 3.1 Flash lite': { model: 'gemini/gemini-3.1-flash-lite-preview',      key_env: 'GEMINI_KEY' },
  'Gemma 4 31B':           { model: 'gemini/gemma-4-31b-it',                     key_env: 'GEMINI_KEY' },
}

// ── Component ──────────────────────────────────────────────────────────────
export default function GeneratePage() {
  const clampIterations = useCallback((value: number) => {
    if (!Number.isFinite(value)) return 1
    return Math.max(1, Math.min(MAX_ITERATIONS, Math.trunc(value)))
  }, [])

  // Resize
  const [sidebarW, setSidebarW] = useState(DEFAULT_SIDEBAR)
  const dragging = useRef(false)
  const dragHandleRef = useRef<HTMLDivElement>(null)

  // User
  const [users, setUsers] = useState<User[]>([])
  const [selectedUid, setSelectedUid] = useState<string>('')

  // Form inputs
  const [jd, setJd] = useState('')
  const [jobLabel, setJobLabel] = useState('')
  const [selectedPreset, setSelectedPreset] = useState('Mistral Large')
  const [maxIter, setMaxIter] = useState(MAX_ITERATIONS)
  const [omissions, setOmissions] = useState<Omissions>({ ...DEFAULT_OMISSIONS })
  const [mandatoryWords, setMandatoryWords] = useState<string[]>([])
  const [customWordInput, setCustomWordInput] = useState('')
  const [agentInstructions, setAgentInstructions] = useState('')
  const [parsedJobs, setParsedJobs] = useState<ParsedJob[]>([])
  const [selectedParsedJobId, setSelectedParsedJobId] = useState<string>('')
  const [suggestedWords, setSuggestedWords] = useState<string[]>([])

  // Run state
  const [activeProjectId, setActiveProjectId] = useState<string | null>(null)
  const [runStatus, setRunStatus] = useState<RunStatus | null>(null)
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [isRunning, setIsRunning] = useState(false)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const logEndRef = useRef<HTMLDivElement>(null)

  // Projects & artifacts
  const [projects, setProjects] = useState<Project[]>([])
  const [selectedProjectId, setSelectedProjectId] = useState<string>('')
  const [artifacts, setArtifacts] = useState<Artifact[]>([])
  const [selectedArtifactId, setSelectedArtifactId] = useState<string>('')

  const selectedProject = projects.find(p => p.id === selectedProjectId) ?? null
  const previewArtifact = artifacts.find(a => String(a.id) === selectedArtifactId) ?? null

  // ── Drag-to-resize ────────────────────────────────────────────────────────
  const onMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    dragging.current = true
    dragHandleRef.current?.classList.add('dragging')

    const onMove = (ev: MouseEvent) => {
      if (!dragging.current) return
      // sidebar is on the right; x from right edge
      const newW = window.innerWidth - ev.clientX
      setSidebarW(Math.max(MIN_SIDEBAR, Math.min(MAX_SIDEBAR, newW)))
    }
    const onUp = () => {
      dragging.current = false
      dragHandleRef.current?.classList.remove('dragging')
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }, [])

  // ── Init ──────────────────────────────────────────────────────────────────
  useEffect(() => { fetchUsers(); fetchParsedJobs() }, [])
  useEffect(() => { if (selectedUid) { fetchProjects(); fetchPreferences() } }, [selectedUid])

  // ── Auto-scroll logic ─────────────────────────────────────────────────────
  const logContainerRef = useRef<HTMLDivElement>(null)
  const isScrolledUp = useRef(false)

  const handleLogScroll = useCallback(() => {
    const el = logContainerRef.current
    if (!el) return
    // If we are more than 30px away from the bottom, consider it "scrolled up"
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 30
    isScrolledUp.current = !atBottom
  }, [])

  useEffect(() => {
    if (!isScrolledUp.current && logEndRef.current) {
      logEndRef.current.scrollIntoView({ behavior: 'smooth' })
    }
  }, [logs])

  // ── API ───────────────────────────────────────────────────────────────────
  async function fetchUsers() {
    const res = await fetch(`${API}/users`)
    const data: User[] = await res.json()
    setUsers(data)
    if (data.length > 0) setSelectedUid(data[0].id)
  }

  async function fetchProjects() {
    if (!selectedUid) return
    const res = await fetch(`${API}/users/${selectedUid}/projects`)
    const data: Project[] = await res.json()
    setProjects(data)
  }

  async function fetchPreferences() {
    if (!selectedUid) return
    try {
      const res = await fetch(`${API}/users/${selectedUid}/preferences`)
      const data = await res.json()
      setOmissions({ ...DEFAULT_OMISSIONS, ...data })
    } catch { /* keep defaults */ }
  }

  async function fetchParsedJobs() {
    try {
      const res = await fetch(`${API}/jobs`)
      const data: ParsedJob[] = await res.json()
      setParsedJobs(data)
    } catch { /* ignore */ }
  }

  function normalizeWordList(values: string[] | undefined): string[] {
    if (!values) return []
    const seen = new Set<string>()
    const cleaned: string[] = []
    for (const value of values) {
      const item = value.trim()
      if (!item) continue
      const key = item.toLowerCase()
      if (seen.has(key)) continue
      seen.add(key)
      cleaned.push(item)
    }
    return cleaned
  }

  function buildSuggestedWords(job: ParsedJob): string[] {
    return normalizeWordList([
      ...(job.required_skills ?? []),
      ...(job.preferred_skills ?? []),
      ...(job.keywords ?? []),
      ...(job.technical_skills ?? []),
    ])
  }

  function handleParsedJobChange(e: React.ChangeEvent<HTMLSelectElement>) {
    const id = e.target.value
    setSelectedParsedJobId(id)
    if (!id) {
      setSuggestedWords([])
      return
    }
    const job = parsedJobs.find(j => j.id === id)
    if (job) {
      if (job.description) setJd(job.description)
      setJobLabel(`${job.company} - ${job.title}`)
      setSuggestedWords(buildSuggestedWords(job))
    }
  }

  function regenerateFromSelectedProject() {
    if (!selectedProject) return

    setJobLabel(selectedProject.name)
    setJd(selectedProject.job_description || '')

    const linkedJob = parsedJobs.find(j => j.project_id === selectedProject.id)
    if (!linkedJob) {
      setSelectedParsedJobId('')
      setSuggestedWords([])
      setMandatoryWords([])
      return
    }

    setSelectedParsedJobId(linkedJob.id)
    setSuggestedWords(buildSuggestedWords(linkedJob))
    setMandatoryWords(
      normalizeWordList([
        ...(linkedJob.required_skills ?? []),
        ...(linkedJob.keywords ?? []),
      ])
    )
  }

  function addMandatoryWord(w: string) {
    if (!w.trim() || mandatoryWords.includes(w.trim())) return
    setMandatoryWords(prev => [...prev, w.trim()])
  }

  function removeMandatoryWord(w: string) {
    setMandatoryWords(prev => prev.filter(x => x !== w))
  }

  async function fetchArtifacts(projectId: string) {
    const res = await fetch(`${API}/users/${selectedUid}/projects/${projectId}/artifacts`)
    const data: Artifact[] = await res.json()
    setArtifacts(data)
    const best = data.find(a => a.artifact_type === 'final_pdf') ?? data.find(a => a.mime_type === 'application/pdf')
    setSelectedArtifactId(best ? String(best.id) : '')
  }

  function handleProjectChange(e: React.ChangeEvent<HTMLSelectElement>) {
    const id = e.target.value
    setSelectedProjectId(id)
    setArtifacts([])
    setSelectedArtifactId('')
    if (id) fetchArtifacts(id)
  }

  async function startGenerate() {
    if (!selectedUid || !jd.trim()) return
    const preset = MODEL_PRESETS[selectedPreset]
    const res = await fetch(`${API}/users/${selectedUid}/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        job_description: jd,
        job_label: jobLabel,
        model: preset.model,
        api_key_env: preset.key_env,
        max_iterations: clampIterations(maxIter),
        omissions: omissions,
        mandatory_words: mandatoryWords,
        agent_instructions: agentInstructions,
      }),
    })
    if (!res.ok) return
    const data = await res.json()
    setActiveProjectId(data.project_id)
    setIsRunning(true)
    setLogs([])
    setRunStatus(null)
    startPolling(data.project_id)
    fetchProjects()
  }

  function startPolling(projectId: string) {
    if (pollRef.current) clearInterval(pollRef.current)
    pollRef.current = setInterval(async () => {
      try {
        const [statusRes, logsRes] = await Promise.all([
          fetch(`${API}/users/${selectedUid}/projects/${projectId}/status`),
          fetch(`${API}/users/${selectedUid}/projects/${projectId}/logs?limit=300`),
        ])
        const status: RunStatus = await statusRes.json()
        const logData: LogEntry[] = await logsRes.json()
        setRunStatus(status)
        setLogs(logData)

        if (['completed', 'failed', 'stopped'].includes(status.state)) {
          setIsRunning(false)
          clearInterval(pollRef.current!)
          await fetchProjects()
          setSelectedProjectId(projectId)
          await fetchArtifacts(projectId)
        }
      } catch { /* keep polling */ }
    }, 1500)
  }

  async function stopRun() {
    if (!activeProjectId) return
    await fetch(`${API}/users/${selectedUid}/projects/${activeProjectId}/stop`, { method: 'POST' })
  }

  async function deleteProject(projectId: string) {
    await fetch(`${API}/users/${selectedUid}/projects/${projectId}`, { method: 'DELETE' })
    if (selectedProjectId === projectId) {
      setSelectedProjectId('')
      setArtifacts([])
      setSelectedArtifactId('')
    }
    fetchProjects()
  }

  function fmtTime(iso: string) {
    return new Date(iso).toLocaleString('en-GB', { dateStyle: 'short', timeStyle: 'short' })
  }

  const preset = MODEL_PRESETS[selectedPreset]

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div style={{ display: 'flex', height: '100%', overflow: 'hidden', userSelect: dragging.current ? 'none' : 'auto' }}>

      {/* ── Left column ─────────────────────────────────────────────── */}
      <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>

        {/* Config bar */}
        <div style={{ flexShrink: 0, borderBottom: '1px solid var(--line)', background: 'var(--bg-panel)' }}>
          {/* Row 1 */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 110px 110px', borderBottom: '1px solid var(--line)' }}>
            <Cell label="PROFILE">
              <select value={selectedUid} onChange={e => setSelectedUid(e.target.value)} style={selectStyle}>
                {users.map(u => <option key={u.id} value={u.id}>{u.display_name}</option>)}
              </select>
            </Cell>
            <Cell label="MODEL">
              <select value={selectedPreset} onChange={e => setSelectedPreset(e.target.value)} style={selectStyle}>
                {Object.keys(MODEL_PRESETS).map(k => <option key={k}>{k}</option>)}
              </select>
            </Cell>
            <Cell label="MAX ITER">
              <input
                type="number" value={maxIter} min={1} max={MAX_ITERATIONS}
                onChange={e => setMaxIter(clampIterations(Number(e.target.value)))}
                style={inputStyle}
              />
            </Cell>
            <Cell label="KEY ENV" noBorder>
              <span style={{ fontSize: 10, color: 'var(--muted)', padding: '4px 0' }}>{preset.key_env}</span>
            </Cell>
          </div>
          {/* Row 2 */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr auto' }}>
            <div style={{ padding: '8px 12px' }}>
              <div className="bp-label" style={{ marginBottom: 4 }}>JOB LABEL</div>
              <input
                type="text" placeholder="e.g. Google – Senior SWE"
                value={jobLabel} onChange={e => setJobLabel(e.target.value)}
                style={{ ...inputStyle, height: 32, fontSize: 12 }}
              />
            </div>
            <div style={{ display: 'flex', alignItems: 'center', padding: '0 12px', gap: 8 }}>
              {isRunning
                ? <button className="btn-danger" onClick={stopRun}>■ STOP</button>
                : <button className="btn-primary" onClick={startGenerate} disabled={!jd.trim() || !selectedUid}>▶ GENERATE</button>
              }
            </div>
          </div>

          {/* Row 3: Section toggles */}
          <div style={{ borderTop: '1px solid var(--line)', padding: '8px 12px', display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center' }}>
            <span className="bp-label" style={{ marginRight: 4 }}>SECTIONS</span>
            {SECTIONS.map(({ key, label }) => {
              const included = !omissions[key]
              return (
                <button
                  key={key}
                  onClick={() => setOmissions(prev => ({ ...prev, [key]: !prev[key] }))}
                  style={{
                    fontFamily: 'var(--font-mono)',
                    fontSize: 10,
                    fontWeight: 700,
                    letterSpacing: '0.08em',
                    textTransform: 'uppercase',
                    padding: '3px 10px',
                    height: 24,
                    cursor: 'pointer',
                    border: `1px solid ${included ? 'var(--cyan-bright)' : 'var(--line)'}`,
                    background: included ? 'rgba(43,125,233,0.15)' : 'transparent',
                    color: included ? 'var(--cyan-bright)' : 'var(--muted)',
                    borderRadius: 0,
                  }}
                >
                  {included ? '✓' : '✕'} {label}
                </button>
              )
            })}
          </div>
        </div>

        {/* JD textarea */}
        <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
          {/* SCRAPED JOBS & MANDATORY WORDS */}
          <div style={{ borderBottom: '1px solid var(--line-dim)', background: 'var(--bg-panel)', padding: '8px 12px', display: 'flex', flexDirection: 'column', gap: 12 }}>
            <div style={{ display: 'flex', gap: 12 }}>
              <div style={{ flex: 1 }}>
                <div className="bp-label" style={{ marginBottom: 4 }}>LOAD SCRAPED JOB</div>
                <select value={selectedParsedJobId} onChange={handleParsedJobChange} style={selectStyle}>
                  <option value="">— manual entry —</option>
                  {parsedJobs.map(j => <option key={j.id} value={j.id}>{j.company} - {j.title}</option>)}
                </select>
              </div>
              <div style={{ flex: 2 }}>
                <div className="bp-label" style={{ marginBottom: 4 }}>MANDATORY WORDS</div>
                <div style={{ display: 'flex', gap: 8 }}>
                  <input 
                    type="text" 
                    placeholder="Type and press Enter..." 
                    value={customWordInput} 
                    onChange={e => setCustomWordInput(e.target.value)}
                    onKeyDown={e => {
                      if (e.key === 'Enter') {
                        e.preventDefault();
                        addMandatoryWord(customWordInput);
                        setCustomWordInput('');
                      }
                    }}
                    style={inputStyle} 
                  />
                  <button className="btn-primary" onClick={() => { addMandatoryWord(customWordInput); setCustomWordInput(''); }}>ADD</button>
                </div>
              </div>
            </div>
            
            {mandatoryWords.length > 0 && (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                <span className="bp-label" style={{ marginTop: 4 }}>REQUIRED:</span>
                {mandatoryWords.map(w => (
                  <div key={w} style={{ display: 'flex', alignItems: 'center', background: 'rgba(43,125,233,0.15)', color: 'var(--cyan-bright)', border: '1px solid var(--cyan-bright)', padding: '2px 8px', fontSize: 10, fontFamily: 'var(--font-mono)', fontWeight: 600 }}>
                    {w}
                    <button onClick={() => removeMandatoryWord(w)} style={{ background: 'transparent', border: 'none', color: 'var(--cyan-bright)', marginLeft: 6, cursor: 'pointer', padding: 0 }}>✕</button>
                  </div>
                ))}
              </div>
            )}
            
            {suggestedWords.length > 0 && (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                <span className="bp-label" style={{ marginTop: 4 }}>SUGGESTED:</span>
                {suggestedWords.filter(w => !mandatoryWords.includes(w)).map(w => (
                  <button key={w} onClick={() => addMandatoryWord(w)} style={{ background: 'var(--bg-input)', color: 'var(--white)', border: '1px solid var(--line)', padding: '2px 8px', fontSize: 10, fontFamily: 'var(--font-mono)', cursor: 'pointer' }}>
                    + {w}
                  </button>
                ))}
              </div>
            )}

            <div>
              <div className="bp-label" style={{ marginBottom: 4 }}>MODEL INSTRUCTIONS</div>
              <textarea
                value={agentInstructions}
                onChange={e => setAgentInstructions(e.target.value)}
                placeholder='Optional: "Add XYZ project for sure", "Do not mention ABC experience"...'
                style={{
                  ...inputStyle,
                  height: 68,
                  resize: 'vertical',
                  minHeight: 54,
                  paddingTop: 6,
                  paddingBottom: 6,
                }}
              />
            </div>
          </div>

          <div style={{ padding: '6px 12px', borderBottom: '1px solid var(--line-dim)', display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
            <span className="bp-label">JOB DESCRIPTION</span>
            <span style={{ color: 'var(--muted)', fontSize: 10, marginLeft: 'auto' }}>{jd.length} CHARS</span>
          </div>
          <textarea
            value={jd} onChange={e => setJd(e.target.value)}
            placeholder="Paste the job description here..."
            style={{ flex: 1, resize: 'none', border: 'none', padding: 14 }}
          />
        </div>

        {/* Terminal */}
        <div style={{ height: 240, flexShrink: 0, borderTop: '1px solid var(--line)', display: 'flex', flexDirection: 'column' }}>
          <div style={{
            height: 34, flexShrink: 0, display: 'flex', alignItems: 'center',
            gap: 8, padding: '0 12px', borderBottom: '1px solid var(--line)',
            background: 'var(--bg-panel)',
          }}>
            <span className="bp-label">TERMINAL</span>
            {runStatus ? (
              <>
                <div className={`status-dot ${runStatus.state}`} />
                <span style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase' }}>{runStatus.state}</span>
                {runStatus.iteration !== '-' && <span style={{ fontSize: 10, color: 'var(--muted)' }}>· ITER {runStatus.iteration}</span>}
                {runStatus.current_step !== '-' && (
                  <span style={{ fontSize: 10, color: 'var(--muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    · {runStatus.current_step}
                  </span>
                )}
              </>
            ) : (
              <span style={{ fontSize: 10, color: 'var(--muted)' }}>IDLE — WAITING FOR RUN</span>
            )}
          </div>
          <div className="log-terminal" style={{ flex: 1 }} ref={logContainerRef} onScroll={handleLogScroll}>
            {logs.length === 0 && !isRunning && (
              <span style={{ color: 'var(--muted)' }}>&gt; Start a generation run to see live output.</span>
            )}
            {logs.map((l, i) => (
              <div key={i} className={`log-${l.level}`}>
                <span style={{ color: 'var(--muted)' }}>{new Date(l.ts * 1000).toLocaleTimeString('en-GB')}</span>
                {' '}{l.text}
              </div>
            ))}
            {isRunning && <span style={{ color: 'var(--cyan-bright)' }}>&gt; <Blinker /></span>}
            <div ref={logEndRef} />
          </div>
        </div>
      </div>

      {/* ── Drag handle ──────────────────────────────────────────────── */}
      <div ref={dragHandleRef} className="resize-handle" onMouseDown={onMouseDown} />

      {/* ── Right sidebar ─────────────────────────────────────────────── */}
      <div style={{ width: sidebarW, flexShrink: 0, display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>

        {/* Projects header */}
        <div style={{ flexShrink: 0, background: 'var(--bg-panel)', borderBottom: '1px solid var(--line)' }}>
          <div style={{ height: 36, display: 'flex', alignItems: 'center', padding: '0 12px', gap: 8, borderBottom: '1px solid var(--line)' }}>
            <span className="bp-label">PROJECTS</span>
            <span style={{ color: 'var(--muted)', fontSize: 10, marginLeft: 'auto' }}>{projects.length} RUNS</span>
            {selectedProjectId && (
              <>
                <button
                  className="btn-ghost"
                  style={{ height: 24, padding: '0 8px', fontSize: 10 }}
                  onClick={regenerateFromSelectedProject}
                >
                  REGENERATE PREFILL
                </button>
                <button
                  className="btn-ghost"
                  style={{ height: 24, padding: '0 8px', fontSize: 10 }}
                  onClick={() => deleteProject(selectedProjectId)}
                >
                  ✕ DELETE
                </button>
              </>
            )}
          </div>
          {/* Project dropdown */}
          <div style={{ padding: '8px 12px' }}>
            <select
              value={selectedProjectId}
              onChange={handleProjectChange}
              style={{ ...selectStyle, width: '100%' }}
            >
              <option value="">— select a project —</option>
              {projects.map(p => (
                <option key={p.id} value={p.id}>
                  [{p.status.toUpperCase()}] {p.name} · {fmtTime(p.created_at)}
                </option>
              ))}
            </select>
          </div>

          {/* Artifact dropdown */}
          {selectedProject && (
            <div style={{ padding: '0 12px 8px' }}>
              <div className="bp-label" style={{ marginBottom: 4 }}>ARTIFACT</div>
              <select
                value={selectedArtifactId}
                onChange={e => setSelectedArtifactId(e.target.value)}
                style={{ ...selectStyle, width: '100%' }}
                disabled={artifacts.length === 0}
              >
                {artifacts.length === 0
                  ? <option value="">— no artifacts yet —</option>
                  : <>
                    <option value="">— select artifact —</option>
                    {artifacts.map(a => (
                      <option key={a.id} value={String(a.id)}>
                        {a.file_name}{a.size_bytes ? ` (${Math.round(a.size_bytes / 1024)}KB)` : ''}
                      </option>
                    ))}
                  </>
                }
              </select>
            </div>
          )}
        </div>

        {/* Preview pane */}
        <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
          {!selectedProject && (
            <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--muted)', fontSize: 11 }}>
              SELECT A PROJECT ABOVE
            </div>
          )}
          {selectedProject && !previewArtifact && (
            <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--muted)', fontSize: 11 }}>
              {artifacts.length === 0 ? 'AWAITING ARTIFACTS...' : 'SELECT AN ARTIFACT ABOVE'}
            </div>
          )}
          {previewArtifact && (
            <>
              <div style={{
                height: 32, flexShrink: 0, display: 'flex', alignItems: 'center',
                padding: '0 12px', gap: 10, borderBottom: '1px solid var(--line-dim)',
                background: 'var(--bg-panel)',
              }}>
                <span style={{ fontSize: 10, color: 'var(--muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {previewArtifact.file_name}
                </span>
                <a
                  href={`${API}/artifacts/download?path=${encodeURIComponent(previewArtifact.storage_path)}`}
                  download={previewArtifact.file_name}
                  style={{ marginLeft: 'auto', textDecoration: 'none', flexShrink: 0 }}
                >
                  <button className="btn-ghost" style={{ height: 24, padding: '0 10px', fontSize: 10 }}>↓ DOWNLOAD</button>
                </a>
              </div>
              {previewArtifact.mime_type === 'application/pdf'
                ? <iframe
                    src={`${API}/artifacts/download?path=${encodeURIComponent(previewArtifact.storage_path)}`}
                    style={{ flex: 1, border: 'none', background: '#fff', width: '100%' }}
                    title={previewArtifact.file_name}
                  />
                : <MarkdownViewer path={previewArtifact.storage_path} />
              }
            </>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Sub-components ─────────────────────────────────────────────────────────

function Cell({ label, children, noBorder }: { label: string; children: React.ReactNode; noBorder?: boolean }) {
  return (
    <div style={{
      padding: '8px 12px',
      borderRight: noBorder ? 'none' : '1px solid var(--line)',
      display: 'flex', flexDirection: 'column', gap: 4,
    }}>
      <div className="bp-label">{label}</div>
      {children}
    </div>
  )
}

const selectStyle: React.CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: 11,
  fontWeight: 600,
  color: 'var(--white)',
  background: 'var(--bg-input)',
  border: '1px solid var(--line)',
  padding: '4px 8px',
  height: 30,
  outline: 'none',
  borderRadius: 0,
}

const inputStyle: React.CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: 11,
  fontWeight: 600,
  color: 'var(--white)',
  background: 'var(--bg-input)',
  border: '1px solid var(--line)',
  padding: '4px 8px',
  height: 30,
  outline: 'none',
  width: '100%',
  borderRadius: 0,
}

function Blinker() {
  const [on, setOn] = useState(true)
  useEffect(() => {
    const t = setInterval(() => setOn(v => !v), 500)
    return () => clearInterval(t)
  }, [])
  return <span style={{ opacity: on ? 1 : 0 }}>█</span>
}

function MarkdownViewer({ path }: { path: string }) {
  const [content, setContent] = useState('')
  useEffect(() => {
    fetch(`/api/artifacts/download?path=${encodeURIComponent(path)}`)
      .then(r => r.text())
      .then(setContent)
      .catch(() => setContent('Could not load file.'))
  }, [path])
  return (
    <pre style={{
      flex: 1, overflow: 'auto', padding: 16,
      fontFamily: 'var(--font-mono)', fontSize: 11,
      color: 'var(--white)', lineHeight: 1.7,
      background: 'var(--bg-input)',
      whiteSpace: 'pre-wrap', wordBreak: 'break-word',
    }}>
      {content}
    </pre>
  )
}
