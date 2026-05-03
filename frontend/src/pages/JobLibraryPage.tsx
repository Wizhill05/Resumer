import { useEffect, useState, useMemo } from 'react'

const API = '/api'

interface ScrapedJob {
  id: string
  title: string
  company: string
  location: string
  link: string
  pay: string
  min_salary_inr: number | null
  max_salary_inr: number | null
  posted_date: string
  description: string
  technical_skills: string[]
  metadata: string[]
  status: string
  scrape_session: string
}

export default function JobLibraryPage() {
  const [jobs, setJobs] = useState<ScrapedJob[]>([])
  const [loading, setLoading] = useState(true)

  // Filters
  const [searchQuery, setSearchQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [hasSalaryFilter, setHasSalaryFilter] = useState(false)

  // Selection
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null)

  useEffect(() => {
    fetchJobs()
  }, [])

  async function fetchJobs() {
    setLoading(true)
    try {
      const res = await fetch(`${API}/jobs`)
      const data: ScrapedJob[] = await res.json()
      setJobs(data)
    } catch {
      // Ignore
    } finally {
      setLoading(false)
    }
  }

  // Filter jobs based on global text search and dropdowns
  const filteredJobs = useMemo(() => {
    return jobs.filter(job => {
      // 1. Status Filter
      if (statusFilter && job.status !== statusFilter) return false
      
      // 2. Has Salary Filter
      if (hasSalaryFilter && !job.pay) return false

      // 3. Global Text Search
      if (searchQuery) {
        const query = searchQuery.toLowerCase()
        const searchableText = [
          job.title,
          job.company,
          job.location,
          job.description,
          ...(job.technical_skills || []),
          ...(job.metadata || []),
        ].filter(Boolean).join(' ').toLowerCase()

        if (!searchableText.includes(query)) return false
      }

      return true
    })
  }, [jobs, searchQuery, statusFilter, hasSalaryFilter])

  const selectedJob = useMemo(() => {
    return jobs.find(j => j.id === selectedJobId) || null
  }, [jobs, selectedJobId])

  // Select first job automatically when filter changes if none selected
  useEffect(() => {
    if (filteredJobs.length > 0 && (!selectedJobId || !filteredJobs.find(j => j.id === selectedJobId))) {
      setSelectedJobId(filteredJobs[0].id)
    }
  }, [filteredJobs, selectedJobId])

  return (
    <div style={{ display: 'flex', height: '100%', overflow: 'hidden' }}>
      {/* ── Left: Job List & Filters ────────────────────────────── */}
      <div style={{ width: 420, flexShrink: 0, display: 'flex', flexDirection: 'column', height: '100%', borderRight: '1px solid var(--line)' }}>
        
        {/* Filters Panel */}
        <div style={{ flexShrink: 0, background: 'var(--bg-panel)', borderBottom: '1px solid var(--line)' }}>
          <div style={{ padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span className="bp-label">JOB LIBRARY ({filteredJobs.length}/{jobs.length})</span>
              <button className="btn-ghost" style={{ height: 24, padding: '0 8px', fontSize: 10 }} onClick={fetchJobs}>↻ REFRESH</button>
            </div>
            
            <input 
              type="text" 
              placeholder="Search across all fields..." 
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              style={inputStyle}
            />

            <div style={{ display: 'flex', gap: 10 }}>
              <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)} style={{ ...selectStyle, flex: 1 }}>
                <option value="">All Statuses</option>
                <option value="nlp_done">Done (NLP)</option>
                <option value="enriched">Enriched</option>
                <option value="basic">Basic</option>
              </select>
              <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, cursor: 'pointer', fontFamily: 'var(--font-mono)' }}>
                <input 
                  type="checkbox" 
                  checked={hasSalaryFilter} 
                  onChange={e => setHasSalaryFilter(e.target.checked)} 
                  style={{ accentColor: 'var(--cyan-bright)' }}
                />
                Has Pay
              </label>
            </div>
          </div>
        </div>

        {/* Job List */}
        <div style={{ flex: 1, overflowY: 'auto' }}>
          {loading && <div style={{ padding: 20, textAlign: 'center', color: 'var(--muted)', fontSize: 11 }}>LOADING...</div>}
          {!loading && filteredJobs.length === 0 && (
            <div style={{ padding: 40, textAlign: 'center', color: 'var(--muted)', fontSize: 11 }}>NO JOBS MATCH YOUR FILTERS</div>
          )}
          {filteredJobs.map(job => {
            const isSelected = selectedJobId === job.id
            return (
              <div 
                key={job.id}
                onClick={() => setSelectedJobId(job.id)}
                className={`library-job-card ${isSelected ? 'selected' : ''}`}
              >
                <div style={{ fontWeight: 600, color: isSelected ? 'var(--cyan-bright)' : 'var(--white)', marginBottom: 4, fontSize: 12 }}>
                  {job.title || 'Untitled'}
                </div>
                <div style={{ color: 'var(--white-dim)', fontSize: 11, marginBottom: 4 }}>
                  {job.company || 'Unknown Company'}
                </div>
                <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                  <span style={{ color: 'var(--muted)', fontSize: 10 }}>{job.location || 'No Location'}</span>
                  {job.pay && <span style={{ color: 'var(--green)', fontSize: 10, fontWeight: 600 }}>• Has Pay</span>}
                  <span style={{ 
                    marginLeft: 'auto', fontSize: 9, padding: '2px 4px', 
                    background: job.status === 'nlp_done' ? 'rgba(30,165,88,0.1)' : 'transparent',
                    color: job.status === 'nlp_done' ? 'var(--green)' : 'var(--muted)',
                    border: `1px solid ${job.status === 'nlp_done' ? 'var(--green)' : 'var(--line)'}`
                  }}>
                    {job.status.toUpperCase()}
                  </span>
                </div>
              </div>
            )
          })}
        </div>
      </div>

      {/* ── Right: Job Detail ─────────────────────────────────── */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', height: '100%', overflowY: 'auto', background: 'var(--bg-panel)' }}>
        {selectedJob ? (
          <div style={{ padding: '24px 32px', maxWidth: 800 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 }}>
              <div>
                <h1 style={{ margin: '0 0 8px 0', fontSize: 24, fontWeight: 700 }}>{selectedJob.title}</h1>
                <div style={{ fontSize: 14, color: 'var(--cyan-bright)', fontWeight: 600, marginBottom: 4 }}>
                  {selectedJob.company}
                </div>
                <div style={{ fontSize: 12, color: 'var(--muted)' }}>
                  {selectedJob.location} • Posted: {selectedJob.posted_date || 'Unknown'}
                </div>
              </div>
              <a 
                href={selectedJob.link} 
                target="_blank" 
                rel="noopener noreferrer" 
                className="btn-primary" 
                style={{ textDecoration: 'none', display: 'inline-block' }}
              >
                OPEN IN INDEED ↗
              </a>
            </div>

            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 24 }}>
              {selectedJob.pay && (
                <div className="detail-tag" style={{ color: 'var(--green)', borderColor: 'var(--green)', background: 'rgba(30,165,88,0.05)' }}>
                  💰 {selectedJob.pay}
                </div>
              )}
              {selectedJob.metadata && selectedJob.metadata.map((m, i) => (
                <div key={i} className="detail-tag">{m}</div>
              ))}
            </div>

            {selectedJob.technical_skills && selectedJob.technical_skills.length > 0 && (
              <div style={{ marginBottom: 24 }}>
                <div className="bp-label" style={{ marginBottom: 8 }}>TECHNICAL SKILLS</div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                  {selectedJob.technical_skills.map(s => (
                    <span key={s} className="skill-chip">{s}</span>
                  ))}
                </div>
              </div>
            )}

            <div style={{ height: 1, background: 'var(--line)', margin: '24px 0' }} />

            <div>
              <div className="bp-label" style={{ marginBottom: 12 }}>FULL DESCRIPTION</div>
              <div style={{ 
                fontSize: 13, 
                color: 'var(--white)', 
                lineHeight: 1.6, 
                whiteSpace: 'pre-wrap',
                fontFamily: 'system-ui, -apple-system, sans-serif'
              }}>
                {selectedJob.description || <span style={{ color: 'var(--muted)' }}>No description available (Phase 2 required).</span>}
              </div>
            </div>
            
            <div style={{ marginTop: 40, paddingTop: 20, borderTop: '1px solid var(--line)', fontSize: 10, color: 'var(--muted)', fontFamily: 'var(--font-mono)' }}>
              JOB ID: {selectedJob.id} • SESSION: {selectedJob.scrape_session} • STATUS: {selectedJob.status.toUpperCase()}
            </div>
          </div>
        ) : (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: 'var(--muted)', fontSize: 12 }}>
            {jobs.length > 0 ? 'SELECT A JOB TO VIEW DETAILS' : 'NO SCRAPED JOBS YET'}
          </div>
        )}
      </div>
    </div>
  )
}

// ── Styles ─────────────────────────────────────────────────────────────────
const inputStyle: React.CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: 11,
  fontWeight: 600,
  color: 'var(--white)',
  background: 'var(--bg-input)',
  border: '1px solid var(--line)',
  padding: '6px 8px',
  height: 32,
  outline: 'none',
  width: '100%',
  borderRadius: 0,
}

const selectStyle: React.CSSProperties = {
  ...inputStyle,
  cursor: 'pointer',
  appearance: 'none',
  WebkitAppearance: 'none',
  backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M0 0l5 6 5-6z' fill='%236a9cc8'/%3E%3C/svg%3E")`,
  backgroundRepeat: 'no-repeat',
  backgroundPosition: 'right 8px center',
  paddingRight: '24px',
}
