import { useCallback, useEffect, useRef, useState } from 'react'

// ── Types ────────────────────────────────────────────────────────────────────
interface LogEntry {
  ts: number
  text: string
  level: string
}
interface ScrapeStatus {
  state: string
  phase: string
  progress: string
  total_jobs: number
  enriched_jobs: number
  error: string
  logs: LogEntry[]
}
interface ScrapedJob {
  id: string
  title: string
  company: string
  location: string
  link: string
  pay: string
  min_salary: number | null
  max_salary: number | null
  posted_date: string
  description: string
  technical_skills: string[]
  status: string
}

const API = '/api'

// ── Constants ────────────────────────────────────────────────────────────────
const INDIA_LOCATIONS = [
  'Bengaluru, Karnataka',
  'Mumbai, Maharashtra',
  'Pune, Maharashtra',
  'Hyderabad, Telangana',
  'Chennai, Tamil Nadu',
  'Delhi',
  'New Delhi, Delhi',
  'Gurgaon, Haryana',
  'Gurugram, Haryana',
  'Noida, Uttar Pradesh',
  'Kolkata, West Bengal',
  'Ahmedabad, Gujarat',
  'Jaipur, Rajasthan',
  'Chandigarh',
  'Lucknow, Uttar Pradesh',
  'Kochi, Kerala',
  'Thiruvananthapuram, Kerala',
  'Coimbatore, Tamil Nadu',
  'Indore, Madhya Pradesh',
  'Bhopal, Madhya Pradesh',
  'Visakhapatnam, Andhra Pradesh',
  'Nagpur, Maharashtra',
  'Mysore, Karnataka',
  'Surat, Gujarat',
  'Vadodara, Gujarat',
  'Remote',
]

const JOB_TYPES = [
  { value: '', label: 'All Types' },
  { value: 'fulltime', label: 'Full-time' },
  { value: 'permanent', label: 'Permanent' },
  { value: 'internship', label: 'Internship' },
  { value: 'fresher', label: 'Fresher' },
  { value: 'contract', label: 'Contract' },
  { value: 'temporary', label: 'Contractual / Temporary' },
  { value: 'parttime', label: 'Part-time' },
]

const DATE_OPTIONS = [
  { value: '', label: 'Any time' },
  { value: '1', label: 'Last 24 hours' },
  { value: '3', label: 'Last 3 days' },
  { value: '7', label: 'Last 7 days' },
  { value: '14', label: 'Last 14 days' },
]

const RADIUS_OPTIONS = [
  { value: '0', label: 'Exact location' },
  { value: '5', label: '5 km' },
  { value: '10', label: '10 km' },
  { value: '15', label: '15 km' },
  { value: '25', label: '25 km' },
  { value: '50', label: '50 km' },
  { value: '100', label: '100 km' },
]

const SALARY_OPTIONS = [
  { value: '', label: 'Any salary' },
  { value: '\u20B960,000', label: '\u20B960,000+ /yr' },
  { value: '\u20B91,20,000', label: '\u20B91,20,000+ /yr' },
  { value: '\u20B92,40,000', label: '\u20B92,40,000+ /yr' },
  { value: '\u20B93,00,000', label: '\u20B93,00,000+ /yr' },
  { value: '\u20B95,00,000', label: '\u20B95,00,000+ /yr' },
  { value: '\u20B98,00,000', label: '\u20B98,00,000+ /yr' },
  { value: '\u20B910,00,000', label: '\u20B910,00,000+ /yr' },
  { value: '\u20B915,00,000', label: '\u20B915,00,000+ /yr' },
  { value: '\u20B920,00,000', label: '\u20B920,00,000+ /yr' },
  { value: '\u20B930,00,000', label: '\u20B930,00,000+ /yr' },
]

// ── Component ────────────────────────────────────────────────────────────────
export default function ScrapePage() {
  // Config
  const [query, setQuery] = useState('ai engineer')
  const [location, setLocation] = useState('Bengaluru, Karnataka')
  const [jobType, setJobType] = useState('')
  const [radius, setRadius] = useState('25')
  const [fromage, setFromage] = useState('')
  const [targetCount, setTargetCount] = useState(50)
  const [salaryFilter, setSalaryFilter] = useState('')
  const [directUrl, setDirectUrl] = useState('')

  // Run state
  const [isRunning, setIsRunning] = useState(false)
  const [status, setStatus] = useState<ScrapeStatus | null>(null)
  const [logs, setLogs] = useState<LogEntry[]>([])
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Jobs
  const [jobs, setJobs] = useState<ScrapedJob[]>([])
  const [expandedJobId, setExpandedJobId] = useState<string>('')

  // Log scroll
  const logContainerRef = useRef<HTMLDivElement>(null)
  const logEndRef = useRef<HTMLDivElement>(null)
  const isScrolledUp = useRef(false)

  const handleLogScroll = useCallback(() => {
    const el = logContainerRef.current
    if (!el) return
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 30
    isScrolledUp.current = !atBottom
  }, [])

  useEffect(() => {
    if (!isScrolledUp.current && logEndRef.current) {
      logEndRef.current.scrollIntoView({ behavior: 'smooth' })
    }
  }, [logs])

  // ── Init ──────────────────────────────────────────────────────────────────
  useEffect(() => { fetchJobs() }, [])

  // ── API ───────────────────────────────────────────────────────────────────
  async function fetchJobs() {
    try {
      const res = await fetch(`${API}/jobs`)
      const data: ScrapedJob[] = await res.json()
      setJobs(data)
    } catch { /* ignore */ }
  }

  async function startScrape() {
    const res = await fetch(`${API}/scrape/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, location, job_type: jobType, radius, fromage, target_count: targetCount, salary_filter: salaryFilter, direct_url: directUrl }),
    })
    if (!res.ok) return
    setIsRunning(true)
    setLogs([])
    setStatus(null)
    startPolling()
  }

  function startPolling() {
    if (pollRef.current) clearInterval(pollRef.current)
    pollRef.current = setInterval(async () => {
      try {
        const res = await fetch(`${API}/scrape/status`)
        const data: ScrapeStatus = await res.json()
        setStatus(data)
        setLogs(data.logs || [])

        if (['completed', 'failed', 'stopped'].includes(data.state)) {
          setIsRunning(false)
          clearInterval(pollRef.current!)
          await fetchJobs()
        }
      } catch { /* keep polling */ }
    }, 1500)
  }

  async function stopScrape() {
    await fetch(`${API}/scrape/stop`, { method: 'POST' })
  }

  async function deleteAllJobs() {
    await fetch(`${API}/jobs`, { method: 'DELETE' })
    setJobs([])
    setExpandedJobId('')
  }

  async function deleteJob(jobId: string) {
    await fetch(`${API}/jobs/${jobId}`, { method: 'DELETE' })
    setJobs(prev => prev.filter(j => j.id !== jobId))
    if (expandedJobId === jobId) setExpandedJobId('')
  }

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div style={{ display: 'flex', height: '100%', overflow: 'hidden' }}>

      {/* ── Left: Config + Terminal ────────────────────────────── */}
      <div style={{ width: 420, flexShrink: 0, display: 'flex', flexDirection: 'column', height: '100%', borderRight: '1px solid var(--line)' }}>

        {/* Config panel */}
        <div style={{ flexShrink: 0, background: 'var(--bg-panel)', borderBottom: '1px solid var(--line)' }}>
          <div style={{ padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div>
              <div className="bp-label" style={{ marginBottom: 4 }}>SEARCH QUERY</div>
              <input type="text" value={query} onChange={e => setQuery(e.target.value)} style={inputStyle} />
            </div>
            <div>
              <div className="bp-label" style={{ marginBottom: 4 }}>LOCATION</div>
              <select value={location} onChange={e => setLocation(e.target.value)} style={selectStyle}>
                {INDIA_LOCATIONS.map(loc => (
                  <option key={loc} value={loc}>{loc}</option>
                ))}
              </select>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
              <div>
                <div className="bp-label" style={{ marginBottom: 4 }}>JOB TYPE</div>
                <select value={jobType} onChange={e => setJobType(e.target.value)} style={selectStyle}>
                  {JOB_TYPES.map(jt => (
                    <option key={jt.value} value={jt.value}>{jt.label}</option>
                  ))}
                </select>
              </div>
              <div>
                <div className="bp-label" style={{ marginBottom: 4 }}>RADIUS</div>
                <select value={radius} onChange={e => setRadius(e.target.value)} style={selectStyle}>
                  {RADIUS_OPTIONS.map(r => (
                    <option key={r.value} value={r.value}>{r.label}</option>
                  ))}
                </select>
              </div>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
              <div>
                <div className="bp-label" style={{ marginBottom: 4 }}>DATE POSTED</div>
                <select value={fromage} onChange={e => setFromage(e.target.value)} style={selectStyle}>
                  {DATE_OPTIONS.map(d => (
                    <option key={d.value} value={d.value}>{d.label}</option>
                  ))}
                </select>
              </div>
              <div>
                <div className="bp-label" style={{ marginBottom: 4 }}>MIN SALARY (INR/YR)</div>
                <select value={salaryFilter} onChange={e => setSalaryFilter(e.target.value)} style={selectStyle}>
                  {SALARY_OPTIONS.map(s => (
                    <option key={s.value} value={s.value}>{s.label}</option>
                  ))}
                </select>
              </div>
            </div>
            <div>
              <div className="bp-label" style={{ marginBottom: 4 }}>TARGET COUNT</div>
              <input type="number" value={targetCount} min={1} max={200} onChange={e => setTargetCount(Number(e.target.value))} style={inputStyle} />
            </div>

            <div style={{ height: 1, background: 'var(--line)', margin: '4px 0' }} />

            <div>
              <div className="bp-label" style={{ marginBottom: 4 }}>OR PASTE DIRECT INDEED LINK</div>
              <input 
                type="text" 
                value={directUrl} 
                onChange={e => setDirectUrl(e.target.value)} 
                placeholder="https://in.indeed.com/jobs?q=..." 
                style={{ ...inputStyle, borderColor: directUrl ? 'var(--cyan-bright)' : 'var(--line)' }} 
              />
            </div>

            <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 4 }}>
              {isRunning
                ? <button className="btn-danger" onClick={stopScrape}>■ STOP</button>
                : <button className="btn-primary" onClick={startScrape} disabled={!query.trim() && !directUrl.trim()}>▶ START SCRAPE</button>
              }
              {status && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginLeft: 8 }}>
                  <div className={`status-dot ${status.state}`} />
                  <span style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase' }}>{status.phase !== '-' ? status.phase : status.state}</span>
                </div>
              )}
            </div>
            {status && status.progress !== '-' && (
              <div style={{ fontSize: 10, color: 'var(--cyan-bright)', fontFamily: 'var(--font-mono)', fontWeight: 600 }}>
                {status.progress}
              </div>
            )}
          </div>
        </div>

        {/* Terminal */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          <div style={{
            height: 34, flexShrink: 0, display: 'flex', alignItems: 'center',
            gap: 8, padding: '0 12px', borderBottom: '1px solid var(--line)',
            background: 'var(--bg-panel)',
          }}>
            <span className="bp-label">TERMINAL</span>
            {status && status.state !== 'idle' && (
              <>
                <div className={`status-dot ${status.state}`} />
                <span style={{ fontSize: 10, color: 'var(--muted)', textTransform: 'uppercase' }}>{status.state}</span>
              </>
            )}
          </div>
          <div className="log-terminal" style={{ flex: 1 }} ref={logContainerRef} onScroll={handleLogScroll}>
            {logs.length === 0 && !isRunning && (
              <span style={{ color: 'var(--muted)' }}>&gt; Configure and start a scrape to see live output.</span>
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

      {/* ── Right: Jobs Table ─────────────────────────────────── */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>

        {/* Header */}
        <div style={{
          height: 44, flexShrink: 0, display: 'flex', alignItems: 'center',
          padding: '0 14px', gap: 10, borderBottom: '1px solid var(--line)',
          background: 'var(--bg-panel)',
        }}>
          <span className="bp-label">SCRAPED JOBS</span>
          <span style={{ color: 'var(--muted)', fontSize: 10, marginLeft: 4 }}>{jobs.length} JOBS</span>
          <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
            <button className="btn-ghost" style={{ height: 28, padding: '0 10px', fontSize: 10 }} onClick={fetchJobs}>↻ REFRESH</button>
            {jobs.length > 0 && (
              <button className="btn-ghost" style={{ height: 28, padding: '0 10px', fontSize: 10, color: 'var(--red)', borderColor: 'var(--red)' }} onClick={deleteAllJobs}>✕ DELETE ALL</button>
            )}
          </div>
        </div>

        {/* Table header */}
        <div className="jobs-table-header">
          <span style={{ flex: 2 }}>TITLE</span>
          <span style={{ flex: 1.5 }}>COMPANY</span>
          <span style={{ flex: 1 }}>LOCATION</span>
          <span style={{ width: 60, textAlign: 'center' }}>SKILLS</span>
          <span style={{ width: 70, textAlign: 'center' }}>STATUS</span>
          <span style={{ width: 40 }}></span>
        </div>

        {/* Rows */}
        <div style={{ flex: 1, overflowY: 'auto' }}>
          {jobs.length === 0 && (
            <div style={{ padding: 40, textAlign: 'center', color: 'var(--muted)', fontSize: 11 }}>
              NO SCRAPED JOBS YET — START A SCRAPE TO POPULATE
            </div>
          )}
          {jobs.map(job => (
            <div key={job.id}>
              <div
                className={`jobs-table-row${expandedJobId === job.id ? ' expanded' : ''}`}
                onClick={() => setExpandedJobId(expandedJobId === job.id ? '' : job.id)}
              >
                <span style={{ flex: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {job.title || '—'}
                </span>
                <span style={{ flex: 1.5, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: 'var(--white-dim)' }}>
                  {job.company || '—'}
                </span>
                <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: 'var(--muted)' }}>
                  {job.location || '—'}
                </span>
                <span style={{ width: 60, textAlign: 'center', color: 'var(--cyan-bright)' }}>
                  {job.technical_skills?.length || 0}
                </span>
                <span style={{ width: 70, textAlign: 'center' }}>
                  <span style={{
                    fontSize: 9, padding: '2px 6px', fontWeight: 700,
                    color: job.status === 'nlp_done' ? 'var(--green)' : job.status === 'enriched' ? 'var(--cyan-bright)' : 'var(--muted)',
                    border: `1px solid ${job.status === 'nlp_done' ? 'var(--green)' : job.status === 'enriched' ? 'var(--cyan-bright)' : 'var(--line)'}`,
                  }}>
                    {job.status === 'nlp_done' ? 'DONE' : job.status === 'enriched' ? 'ENRICH' : 'BASIC'}
                  </span>
                </span>
                <span style={{ width: 40, textAlign: 'center' }}>
                  <button
                    onClick={e => { e.stopPropagation(); deleteJob(job.id) }}
                    style={{ background: 'transparent', border: 'none', color: 'var(--muted)', cursor: 'pointer', fontSize: 12, padding: 0 }}
                    title="Delete"
                  >✕</button>
                </span>
              </div>

              {/* Expanded detail */}
              {expandedJobId === job.id && (
                <div className="job-detail-panel">
                  <div style={{ display: 'flex', gap: 16, marginBottom: 10 }}>
                    {job.pay && (
                      <div>
                        <span className="bp-label" style={{ marginRight: 6 }}>PAY</span>
                        <span style={{ fontSize: 11, color: 'var(--white-dim)' }}>{job.pay}</span>
                      </div>
                    )}
                    {job.link && (
                      <a href={job.link} target="_blank" rel="noopener noreferrer" style={{ fontSize: 11, color: 'var(--cyan-bright)' }}>
                        View on Indeed →
                      </a>
                    )}
                  </div>

                  {job.technical_skills && job.technical_skills.length > 0 && (
                    <div style={{ marginBottom: 10 }}>
                      <div className="bp-label" style={{ marginBottom: 6 }}>TECHNICAL SKILLS</div>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                        {job.technical_skills.map(s => (
                          <span key={s} style={{
                            fontSize: 10, fontFamily: 'var(--font-mono)', fontWeight: 600,
                            padding: '2px 8px', border: '1px solid var(--cyan-bright)',
                            color: 'var(--cyan-bright)', background: 'rgba(43,125,233,0.1)',
                          }}>{s}</span>
                        ))}
                      </div>
                    </div>
                  )}

                  {job.description && (
                    <div>
                      <div className="bp-label" style={{ marginBottom: 6 }}>DESCRIPTION</div>
                      <div style={{
                        fontSize: 11, color: 'var(--white-dim)', lineHeight: 1.6,
                        maxHeight: 200, overflowY: 'auto', padding: 10,
                        background: 'var(--bg-input)', border: '1px solid var(--line-dim)',
                        whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                      }}>
                        {job.description}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

// ── Sub-components ─────────────────────────────────────────────────────────
function Blinker() {
  const [on, setOn] = useState(true)
  useEffect(() => {
    const t = setInterval(() => setOn(v => !v), 500)
    return () => clearInterval(t)
  }, [])
  return <span style={{ opacity: on ? 1 : 0 }}>█</span>
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
  width: '100%',
  borderRadius: 0,
  cursor: 'pointer',
  appearance: 'none',
  WebkitAppearance: 'none',
  backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M0 0l5 6 5-6z' fill='%236a9cc8'/%3E%3C/svg%3E")`,
  backgroundRepeat: 'no-repeat',
  backgroundPosition: 'right 8px center',
  paddingRight: '24px',
}
