import { useEffect, useState, useRef, useCallback } from 'react'
import { SECTIONS, DEFAULT_OMISSIONS, type Omissions, type SectionKey } from './ProfilesPage'

const API = '/api'
const MAX_ITERATIONS = 5

interface ScrapedJob {
  id: string
  title: string
  company: string
  location: string
  pay: string
  status: string
  project_id: string
  description: string
  applied: boolean
}

interface User {
  id: string
  display_name: string
}

const MODEL_PRESETS: Record<string, { model: string; key_env: string }> = {
  'Mistral Large':         { model: 'mistral/mistral-large-latest',         key_env: 'MISTRAL_API_KEY' },
  'Mistral Medium':        { model: 'mistral/mistral-medium-latest',        key_env: 'MISTRAL_API_KEY' },
  'Gemini 3 Flash':        { model: 'gemini/gemini-3-flash-preview',        key_env: 'GEMINI_KEY' },
  'Gemini 3.1 Flash lite': { model: 'gemini/gemini-3.1-flash-lite-preview', key_env: 'GEMINI_KEY' },
  'Gemma 4 31B':           { model: 'gemini/gemma-4-31b-it',                key_env: 'GEMINI_KEY' },
}

// ── Module-level batch state (persists across navigation) ─────────────────────
// Using a simple mutable object + a set of subscriber callbacks
const _batchState = {
  isProcessing: false,
  logs: [] as string[],
  progress: { current: 0, total: 0 },
  selectedJobIds: new Set<string>(),
}
type BatchStateListener = () => void
const _batchListeners = new Set<BatchStateListener>()

function notifyBatchListeners() {
  _batchListeners.forEach(fn => fn())
}

function setBatchState(patch: Partial<typeof _batchState>) {
  Object.assign(_batchState, patch)
  notifyBatchListeners()
}

function appendBatchLog(msg: string) {
  const time = new Date().toLocaleTimeString('en-GB')
  _batchState.logs = [..._batchState.logs, `[${time}] ${msg}`]
  notifyBatchListeners()
}

// ── Component ────────────────────────────────────────────────────────────────
export default function BatchProcessingPage() {
  const clampIterations = useCallback((value: number) => {
    if (!Number.isFinite(value)) return 1
    return Math.max(1, Math.min(MAX_ITERATIONS, Math.trunc(value)))
  }, [])

  const [users, setUsers] = useState<User[]>([])
  const [selectedUid, setSelectedUid] = useState<string>('')
  const [jobs, setJobs] = useState<ScrapedJob[]>([])
  const [loading, setLoading] = useState(true)

  // Config options
  const [selectedPreset, setSelectedPreset] = useState('Mistral Large')
  const [maxIter, setMaxIter] = useState(MAX_ITERATIONS)
  const [omissions, setOmissions] = useState<Omissions>({ ...DEFAULT_OMISSIONS })

  // Mirror module-level batch state into React state for re-renders
  const [, forceUpdate] = useState(0)
  const rerender = useCallback(() => forceUpdate(n => n + 1), [])

  const logEndRef = useRef<HTMLDivElement>(null)

  // Subscribe to module-level state changes
  useEffect(() => {
    _batchListeners.add(rerender)
    return () => { _batchListeners.delete(rerender) }
  }, [rerender])

  useEffect(() => {
    fetchUsers()
    fetchJobs()
  }, [])

  useEffect(() => {
    if (logEndRef.current) {
      logEndRef.current.scrollIntoView({ behavior: 'smooth' })
    }
  }, [_batchState.logs.length])

  async function fetchUsers() {
    try {
      const res = await fetch(`${API}/users`)
      const data: User[] = await res.json()
      setUsers(data)
      if (data.length > 0) setSelectedUid(data[0].id)
    } catch { /* ignore */ }
  }

  async function fetchJobs() {
    setLoading(true)
    try {
      const res = await fetch(`${API}/jobs`)
      const data: ScrapedJob[] = await res.json()
      // Do not keep jobs that have a resume OR are already marked as applied
      setJobs(data.filter(j => !j.project_id && !j.applied))
    } catch { /* ignore */ }
    finally { setLoading(false) }
  }

  async function fetchPreferences() {
    if (!selectedUid) return
    try {
      const res = await fetch(`${API}/users/${selectedUid}/preferences`)
      const data = await res.json()
      setOmissions({ ...DEFAULT_OMISSIONS, ...data })
    } catch { 
      setOmissions({ ...DEFAULT_OMISSIONS }) 
    }
  }

  useEffect(() => {
    fetchPreferences()
  }, [selectedUid])

  function toggleSelection(id: string) {
    if (_batchState.isProcessing) return
    const next = new Set(_batchState.selectedJobIds)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    setBatchState({ selectedJobIds: next })
  }

  function toggleAll() {
    if (_batchState.isProcessing) return
    const next = _batchState.selectedJobIds.size === jobs.length
      ? new Set<string>()
      : new Set(jobs.map(j => j.id))
    setBatchState({ selectedJobIds: next })
  }

  async function startBatchProcessing() {
    if (!selectedUid || _batchState.selectedJobIds.size === 0 || _batchState.isProcessing) return

    const preset = MODEL_PRESETS[selectedPreset]
    const jobsToProcess = jobs.filter(j => _batchState.selectedJobIds.has(j.id))

    setBatchState({
      isProcessing: true,
      logs: [],
      progress: { current: 0, total: jobsToProcess.length },
    })

    appendBatchLog(`Starting batch for ${jobsToProcess.length} job(s) using ${selectedPreset}...`)

    for (let i = 0; i < jobsToProcess.length; i++) {
      const job = jobsToProcess[i]
      setBatchState({ progress: { current: i + 1, total: jobsToProcess.length } })
      appendBatchLog(`---`)
      appendBatchLog(`[${i + 1}/${jobsToProcess.length}] ${job.title} @ ${job.company}`)

      try {
        const genRes = await fetch(`${API}/users/${selectedUid}/generate`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              job_description: job.description || 'No description provided.',
              job_label: `${job.company} - ${job.title}`,
              model: preset.model,
              api_key_env: preset.key_env,
              max_iterations: clampIterations(maxIter),
              omissions: omissions,
              mandatory_words: [],
            }),
        })

        if (!genRes.ok) {
          appendBatchLog(`ERROR: Failed to start generation (HTTP ${genRes.status})`)
          continue
        }

        const genData = await genRes.json()
        const projectId: string = genData.project_id
        appendBatchLog(`Project created: ${projectId.slice(-8)}. Waiting...`)

        // Poll until done
        let done = false
        let lastLogTs = 0
        while (!done) {
          await new Promise(r => setTimeout(r, 1500))
          try {
            const [sRes, lRes] = await Promise.all([
              fetch(`${API}/users/${selectedUid}/projects/${projectId}/status`),
              fetch(`${API}/users/${selectedUid}/projects/${projectId}/logs?limit=500`),
            ])
            
            if (lRes.ok) {
              const logs: {ts: number, text: string, level: string}[] = await lRes.json()
              const newLogs = logs.filter(l => l.ts > lastLogTs)
              if (newLogs.length > 0) {
                newLogs.forEach(l => appendBatchLog(`[Agent] ${l.text}`))
                lastLogTs = newLogs[newLogs.length - 1].ts
              }
            }

            if (sRes.ok) {
              const s = await sRes.json()
              if (['completed', 'failed', 'stopped'].includes(s.state)) {
                done = true
                appendBatchLog(`Job completed with status: ${s.state}`)
              }
            }
          } catch { /* keep polling */ }
        }

        // Link job to project (even if failed, to avoid re-processing in future batches)
        await fetch(`${API}/jobs/${job.id}/project`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ project_id: projectId }),
        })
        appendBatchLog(`Linked to project.`)

      } catch (err: unknown) {
        appendBatchLog(`ERROR: ${err instanceof Error ? err.message : String(err)}`)
      }
    }

    appendBatchLog(`=== Batch complete ===`)
    setBatchState({ isProcessing: false, selectedJobIds: new Set() })
    fetchJobs()
  }

  const { isProcessing, logs, progress, selectedJobIds } = _batchState
  const preset = MODEL_PRESETS[selectedPreset]

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>

      {/* ── Top Bar ─────────────────────────────────────────── */}
      <div style={{ flexShrink: 0, padding: '12px 24px', background: 'var(--bg-panel)', borderBottom: '1px solid var(--line)', display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 16 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 18 }}>BATCH PROCESSING</h1>
          <div style={{ color: 'var(--muted)', fontSize: 11, marginTop: 3 }}>
            Generate resumes for multiple jobs sequentially.
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          {isProcessing ? (
            <div style={{ color: 'var(--cyan-bright)', fontSize: 12, fontFamily: 'var(--font-mono)', fontWeight: 700 }}>
              ◈ PROCESSING {progress.current} / {progress.total}
            </div>
          ) : (
            <>
              <span style={{ color: 'var(--muted)', fontSize: 11 }}>{selectedJobIds.size} selected</span>
              <button
                className="btn-primary"
                onClick={startBatchProcessing}
                disabled={selectedJobIds.size === 0 || !selectedUid}
              >
                ▶ START BATCH
              </button>
            </>
          )}
        </div>
      </div>

      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>

        {/* ── Left: Config + Job List ──────────────────────── */}
        <div style={{ flex: 2, display: 'flex', flexDirection: 'column', overflow: 'hidden', borderRight: '1px solid var(--line)' }}>

          {/* Config Panel */}
          <div style={{ flexShrink: 0, background: 'var(--bg-panel)', borderBottom: '1px solid var(--line)', padding: '12px 16px', display: 'flex', flexDirection: 'column', gap: 12 }}>
            <span className="bp-label">GENERATION CONFIG</span>

            {/* Row 1: Profile, Model, Max Iter */}
            <div style={{ display: 'flex', gap: 12 }}>
              <div style={{ flex: 1 }}>
                <div className="bp-label" style={{ marginBottom: 4 }}>PROFILE</div>
                <select value={selectedUid} onChange={e => setSelectedUid(e.target.value)} style={selStyle} disabled={isProcessing}>
                  {users.map(u => <option key={u.id} value={u.id}>{u.display_name}</option>)}
                </select>
              </div>
              <div style={{ flex: 2 }}>
                <div className="bp-label" style={{ marginBottom: 4 }}>MODEL — <span style={{ color: 'var(--muted)' }}>{preset.key_env}</span></div>
                <select value={selectedPreset} onChange={e => setSelectedPreset(e.target.value)} style={selStyle} disabled={isProcessing}>
                  {Object.keys(MODEL_PRESETS).map(k => <option key={k}>{k}</option>)}
                </select>
              </div>
              <div style={{ width: 80, flexShrink: 0 }}>
                <div className="bp-label" style={{ marginBottom: 4 }}>MAX ITER</div>
                <input
                  type="number" value={maxIter} min={1} max={MAX_ITERATIONS}
                  onChange={e => setMaxIter(clampIterations(Number(e.target.value)))}
                  disabled={isProcessing}
                  style={{ ...selStyle, height: 30, width: '100%' }}
                />
              </div>
            </div>

            {/* Row 2: Section toggles */}
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {SECTIONS.map(({ key, label }) => {
                const included = !omissions[key as SectionKey]
                return (
                  <button
                    key={key}
                    onClick={() => !isProcessing && setOmissions(prev => ({ ...prev, [key]: !prev[key as SectionKey] }))}
                    disabled={isProcessing}
                    style={{
                      fontFamily: 'var(--font-mono)', fontSize: 10, fontWeight: 700,
                      letterSpacing: '0.08em', textTransform: 'uppercase',
                      padding: '3px 10px', height: 24, cursor: isProcessing ? 'default' : 'pointer',
                      border: `1px solid ${included ? 'var(--cyan-bright)' : 'var(--line)'}`,
                      background: included ? 'rgba(43,125,233,0.15)' : 'transparent',
                      color: included ? 'var(--cyan-bright)' : 'var(--muted)',
                    }}
                  >
                    {included ? '✓' : '✕'} {label}
                  </button>
                )
              })}
            </div>
          </div>

          {/* Job List header */}
          <div style={{ padding: '8px 16px', background: 'var(--bg-panel)', borderBottom: '1px solid var(--line)', display: 'flex', alignItems: 'center', gap: 12, flexShrink: 0 }}>
            <input
              type="checkbox"
              checked={jobs.length > 0 && selectedJobIds.size === jobs.length}
              onChange={toggleAll}
              disabled={isProcessing || jobs.length === 0}
              style={{ accentColor: 'var(--cyan-bright)', width: 16, height: 16, cursor: 'pointer' }}
            />
            <span className="bp-label">PENDING JOBS ({jobs.length})</span>
            <button className="btn-ghost" style={{ marginLeft: 'auto', height: 24, padding: '0 8px', fontSize: 10 }} onClick={fetchJobs} disabled={isProcessing}>↻ REFRESH</button>
          </div>

          {/* Job rows */}
          <div style={{ flex: 1, overflowY: 'auto' }}>
            {loading && <div style={{ padding: 40, textAlign: 'center', color: 'var(--muted)', fontSize: 12 }}>LOADING...</div>}
            {!loading && jobs.length === 0 && (
              <div style={{ padding: 40, textAlign: 'center', color: 'var(--muted)', fontSize: 12 }}>
                All jobs have been processed, or no jobs have been scraped yet.
              </div>
            )}
            {!loading && jobs.map(job => {
              const isSel = selectedJobIds.has(job.id)
              return (
                <div
                  key={job.id}
                  onClick={() => toggleSelection(job.id)}
                  style={{
                    padding: '12px 16px', borderBottom: '1px solid var(--line-dim)',
                    background: isSel ? 'rgba(43,125,233,0.06)' : 'transparent',
                    display: 'flex', gap: 16, alignItems: 'center',
                    cursor: isProcessing ? 'default' : 'pointer',
                    opacity: isProcessing && !isSel ? 0.45 : 1,
                  }}
                >
                  <input
                    type="checkbox" checked={isSel}
                    onChange={() => toggleSelection(job.id)}
                    disabled={isProcessing}
                    style={{ accentColor: 'var(--cyan-bright)', width: 16, height: 16, flexShrink: 0, cursor: 'pointer' }}
                  />
                  <div>
                    <div style={{ fontWeight: 600, fontSize: 13, color: isSel ? 'var(--cyan-bright)' : 'var(--white)', marginBottom: 3 }}>
                      {job.title || 'Untitled'}
                    </div>
                    <div style={{ fontSize: 11, color: 'var(--white-dim)' }}>
                      {job.company || 'Unknown'} • {job.location || 'Unknown location'}
                    </div>
                  </div>
                  <div style={{ marginLeft: 'auto', fontSize: 9, fontFamily: 'var(--font-mono)', color: 'var(--muted)' }}>
                    {job.id.slice(-8)}
                  </div>
                </div>
              )
            })}
          </div>
        </div>

        {/* ── Right: Logs Panel ─────────────────────────────── */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', background: '#010c18' }}>
          <div style={{ padding: '10px 16px', background: 'var(--bg-panel)', borderBottom: '1px solid var(--line)', flexShrink: 0, display: 'flex', alignItems: 'center', gap: 10 }}>
            <span className="bp-label">BATCH LOGS</span>
            {isProcessing && <><div className="status-dot running" /><span style={{ fontSize: 10, color: 'var(--cyan-bright)' }}>RUNNING</span></>}
            {!isProcessing && logs.length > 0 && (
              <button className="btn-ghost" style={{ marginLeft: 'auto', height: 22, padding: '0 8px', fontSize: 10 }} onClick={() => setBatchState({ logs: [] })}>
                CLEAR
              </button>
            )}
          </div>
          <div style={{ flex: 1, overflowY: 'auto', padding: 16, fontFamily: 'var(--font-mono)', fontSize: 11, lineHeight: 1.7 }}>
            {logs.length === 0 ? (
              <span style={{ color: 'var(--muted)' }}>&gt; Select jobs and click Start Batch to begin.</span>
            ) : (
              logs.map((log, i) => (
                <div key={i} style={{
                  color: log.includes('ERROR') ? 'var(--red)'
                    : log.includes('===') ? 'var(--cyan-bright)'
                    : log.startsWith('[') && log.includes(']/') ? 'var(--white)'
                    : 'var(--muted)',
                  marginBottom: 2,
                }}>
                  {log}
                </div>
              ))
            )}
            {isProcessing && <span style={{ color: 'var(--cyan-bright)' }}>&gt; <Blinker /></span>}
            <div ref={logEndRef} />
          </div>
        </div>

      </div>
    </div>
  )
}

function Blinker() {
  const [on, setOn] = useState(true)
  useEffect(() => {
    const t = setInterval(() => setOn(v => !v), 500)
    return () => clearInterval(t)
  }, [])
  return <span style={{ opacity: on ? 1 : 0 }}>█</span>
}

const selStyle: React.CSSProperties = {
  fontFamily: 'var(--font-mono)', fontSize: 11, fontWeight: 600,
  color: 'var(--white)', background: 'var(--bg-input)',
  border: '1px solid var(--line)', padding: '4px 8px',
  height: 30, outline: 'none', borderRadius: 0, width: '100%',
}
