import { useEffect, useRef, useState } from 'react'
import type { CSSProperties } from 'react'

// ── Types & constants ──────────────────────────────────────────────────────
interface User {
  id: string
  display_name: string
  created_at: string
}
interface ResumeTemplate {
  id: string
  name: string
  content: string
  css_content: string
  is_default: boolean
  updated_at: string
}

const API = '/api'

export const SECTIONS = [
  { key: 'no_photo',        label: 'PHOTO',        desc: 'Profile photo in header' },
  { key: 'no_applying_for', label: 'APPLYING FOR', desc: 'Role subtitle under name' },
  { key: 'no_objective',    label: 'OBJECTIVE',    desc: 'Summary / objective blurb' },
  { key: 'no_education',    label: 'EDUCATION',    desc: 'Education section' },
  { key: 'no_skills',       label: 'SKILLS',       desc: 'Skills / tech stack section' },
  { key: 'no_projects',     label: 'PROJECTS',     desc: 'Projects section' },
  { key: 'no_experience',   label: 'EXPERIENCE',   desc: 'Work experience section' },
  { key: 'no_activities',   label: 'ACTIVITIES',   desc: 'Activities & achievements' },
] as const

export type SectionKey = (typeof SECTIONS)[number]['key']
export type Omissions = Record<SectionKey, boolean>

export const DEFAULT_OMISSIONS: Omissions = {
  no_photo:        true,
  no_applying_for: true,
  no_objective:    false,
  no_education:    false,
  no_skills:       false,
  no_projects:     false,
  no_experience:   false,
  no_activities:   false,
}

// ── Component ──────────────────────────────────────────────────────────────
export default function ProfilesPage() {
  const [users, setUsers] = useState<User[]>([])
  const [selectedUid, setSelectedUid] = useState<string | null>(null)
  const [newName, setNewName] = useState('')

  // Tab
  const [activeTab, setActiveTab] = useState<'truth' | 'defaults' | 'templates'>('truth')

  // Truth JSON editor
  const [truthText, setTruthText] = useState('')
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')
  const [jsonError, setJsonError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Generation defaults
  const [omissions, setOmissions] = useState<Omissions>({ ...DEFAULT_OMISSIONS })
  const [prefStatus, setPrefStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')
  const prefTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Jinja templates
  const [templates, setTemplates] = useState<ResumeTemplate[]>([])
  const [selectedTemplateId, setSelectedTemplateId] = useState('')
  const [templateName, setTemplateName] = useState('')
  const [templateContent, setTemplateContent] = useState('')
  const [templateCssContent, setTemplateCssContent] = useState('')
  const [templateView, setTemplateView] = useState<'html' | 'css'>('html')
  const [templateStatus, setTemplateStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')

  useEffect(() => { fetchUsers() }, [])

  async function fetchUsers() {
    try {
      const res = await fetch(`${API}/users`)
      const data: User[] = await res.json()
      setUsers(data)
      if (data.length > 0 && !selectedUid) selectUser(data[0].id)
    } catch { /* keep */ }
  }

  async function selectUser(uid: string) {
    setSelectedUid(uid)
    setLoading(true)
    setJsonError(null)
    try {
      const [truthRes, prefRes, templateRes] = await Promise.all([
        fetch(`${API}/users/${uid}/truth`),
        fetch(`${API}/users/${uid}/preferences`),
        fetch(`${API}/users/${uid}/templates`),
      ])
      const truthData = await truthRes.json()
      const prefData = await prefRes.json()
      const templateData: ResumeTemplate[] = await templateRes.json()
      setTruthText(JSON.stringify(truthData, null, 2))
      setOmissions({ ...DEFAULT_OMISSIONS, ...prefData })
      setTemplates(templateData)
      selectTemplate(templateData.find(t => t.is_default)?.id ?? templateData[0]?.id ?? '', templateData)
    } catch {
      setTruthText('{}')
      setOmissions({ ...DEFAULT_OMISSIONS })
      setTemplates([])
      selectTemplate('', [])
    } finally {
      setLoading(false)
    }
  }

  async function createUser() {
    const name = newName.trim()
    if (!name) return
    try {
      const res = await fetch(`${API}/users`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ display_name: name }),
      })
      if (!res.ok) throw new Error()
      const data = await res.json()
      setNewName('')
      await fetchUsers()
      selectUser(data.uid)
    } catch { /* noop */ }
  }

  function handleTruthChange(value: string) {
    setTruthText(value)
    setJsonError(null)
    setSaveStatus('idle')
    try { JSON.parse(value) }
    catch (e: any) { setJsonError(e.message) }
  }

  async function saveTruth() {
    if (!selectedUid || jsonError) return
    setSaveStatus('saving')
    try {
      const parsed = JSON.parse(truthText)
      const res = await fetch(`${API}/users/${selectedUid}/truth`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ truth_json: parsed }),
      })
      setSaveStatus(res.ok ? 'saved' : 'error')
    } catch { setSaveStatus('error') }
    if (saveTimer.current) clearTimeout(saveTimer.current)
    saveTimer.current = setTimeout(() => setSaveStatus('idle'), 2500)
  }

  async function savePreferences() {
    if (!selectedUid) return
    setPrefStatus('saving')
    try {
      const res = await fetch(`${API}/users/${selectedUid}/preferences`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ preferences: omissions }),
      })
      setPrefStatus(res.ok ? 'saved' : 'error')
    } catch { setPrefStatus('error') }
    if (prefTimer.current) clearTimeout(prefTimer.current)
    prefTimer.current = setTimeout(() => setPrefStatus('idle'), 2500)
  }

  function toggleOmission(key: SectionKey) {
    setOmissions(prev => ({ ...prev, [key]: !prev[key] }))
    setPrefStatus('idle')
  }

  function selectTemplate(id: string, source = templates) {
    const template = source.find(t => t.id === id)
    setSelectedTemplateId(template?.id ?? '')
    setTemplateName(template?.name ?? '')
    setTemplateContent(template?.content ?? '')
    setTemplateCssContent(template?.css_content ?? '')
    setTemplateStatus('idle')
  }

  async function refreshTemplates(uid = selectedUid) {
    if (!uid) return
    const res = await fetch(`${API}/users/${uid}/templates`)
    const data: ResumeTemplate[] = await res.json()
    setTemplates(data)
    return data
  }

  async function addTemplate() {
    if (!selectedUid) return
    setTemplateStatus('saving')
    try {
      const seed = templateContent || templates.find(t => t.is_default)?.content || ''
      const res = await fetch(`${API}/users/${selectedUid}/templates`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: 'New Template', content: seed, css_content: '', is_default: templates.length === 0 }),
      })
      if (!res.ok) throw new Error()
      const created: ResumeTemplate = await res.json()
      const data = await refreshTemplates()
      selectTemplate(created.id, data)
      setTemplateStatus('saved')
    } catch { setTemplateStatus('error') }
  }

  async function saveTemplate() {
    if (!selectedUid || !selectedTemplateId) return
    setTemplateStatus('saving')
    try {
      const current = templates.find(t => t.id === selectedTemplateId)
      const res = await fetch(`${API}/users/${selectedUid}/templates/${selectedTemplateId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: templateName, content: templateContent, css_content: templateCssContent, is_default: current?.is_default ?? false }),
      })
      if (!res.ok) throw new Error()
      const data = await refreshTemplates()
      selectTemplate(selectedTemplateId, data)
      setTemplateStatus('saved')
    } catch { setTemplateStatus('error') }
  }

  async function deleteTemplate() {
    if (!selectedUid || !selectedTemplateId) return
    if (!confirm('Delete this resume template?')) return
    await fetch(`${API}/users/${selectedUid}/templates/${selectedTemplateId}`, { method: 'DELETE' })
    const data = await refreshTemplates()
    selectTemplate(data?.find(t => t.is_default)?.id ?? data?.[0]?.id ?? '', data)
  }

  async function setDefaultTemplate() {
    if (!selectedUid || !selectedTemplateId) return
    await fetch(`${API}/users/${selectedUid}/templates/${selectedTemplateId}/default`, { method: 'PUT' })
    const data = await refreshTemplates()
    selectTemplate(selectedTemplateId, data)
  }

  const selectedUser = users.find(u => u.id === selectedUid)
  const lineCount = truthText.split('\n').length

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '260px 1fr', height: '100%', overflow: 'hidden' }}>

      {/* ── Left: User list ─────────────────────────────────────────── */}
      <div style={{ borderRight: '1px solid var(--line)', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        <div style={{ padding: '12px 14px', borderBottom: '1px solid var(--line)', background: 'var(--bg-panel)' }}>
          <div className="bp-label" style={{ marginBottom: 10 }}>PROFILES</div>
          <div style={{ display: 'flex', gap: 6 }}>
            <input
              type="text"
              placeholder="new profile name"
              value={newName}
              onChange={e => setNewName(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && createUser()}
              style={{ flex: 1, height: 32, fontSize: 11 }}
            />
            <button className="btn-primary" style={{ height: 32, padding: '0 10px', fontSize: 11 }} onClick={createUser}>+</button>
          </div>
        </div>
        <div style={{ flex: 1, overflowY: 'auto' }}>
          {users.length === 0 && (
            <div style={{ padding: 16, color: 'var(--muted)', fontSize: 11 }}>NO PROFILES FOUND</div>
          )}
          {users.map(u => (
            <div
              key={u.id}
              onClick={() => selectUser(u.id)}
              style={{
                padding: '10px 14px',
                borderBottom: '1px solid var(--line-dim)',
                cursor: 'pointer',
                background: u.id === selectedUid ? 'rgba(12,84,165,0.14)' : 'transparent',
                borderLeft: u.id === selectedUid ? '2px solid var(--cyan-bright)' : '2px solid transparent',
              }}
            >
              <div style={{ color: u.id === selectedUid ? 'var(--cyan-bright)' : 'var(--white)', fontSize: 12, fontWeight: 700, marginBottom: 3 }}>
                {u.display_name}
              </div>
              <div style={{ color: 'var(--muted)', fontSize: 10 }}>
                {new Date(u.created_at).toLocaleDateString()}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* ── Right: Tabbed panel ─────────────────────────────────────── */}
      <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>

        {/* Tab bar */}
        <div style={{ display: 'flex', alignItems: 'stretch', borderBottom: '1px solid var(--line)', background: 'var(--bg-panel)', flexShrink: 0 }}>
          {(['truth', 'defaults', 'templates'] as const).map(tab => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 11,
                fontWeight: 700,
                letterSpacing: '0.1em',
                textTransform: 'uppercase',
                background: 'transparent',
                border: 'none',
                borderBottom: `2px solid ${activeTab === tab ? 'var(--cyan-bright)' : 'transparent'}`,
                color: activeTab === tab ? 'var(--cyan-bright)' : 'var(--muted)',
                padding: '0 20px',
                height: 44,
                cursor: 'pointer',
              }}
            >
              {tab === 'truth' ? '01 / TRUTH.JSON' : tab === 'defaults' ? '02 / DEFAULTS' : '03 / TEMPLATES'}
            </button>
          ))}
          {selectedUser && (
            <span style={{ marginLeft: 'auto', padding: '0 16px', color: 'var(--muted)', fontSize: 10, display: 'flex', alignItems: 'center' }}>
              {selectedUser.display_name}
            </span>
          )}
        </div>

        {/* ── Tab 1: JSON Editor ──────────────────────────────────── */}
        {activeTab === 'truth' && (
          <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
            {/* Toolbar */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '0 16px', height: 40, borderBottom: '1px solid var(--line)', background: 'var(--bg-panel)', flexShrink: 0 }}>
              <span className="bp-label">TRUTH.JSON</span>
              <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 10 }}>
                {jsonError && <span style={{ color: 'var(--red)', fontSize: 10, fontWeight: 700 }}>✕ INVALID JSON</span>}
                {saveStatus === 'saved' && <span style={{ color: 'var(--green)', fontSize: 10, fontWeight: 700 }}>✓ SAVED</span>}
                {saveStatus === 'error' && <span style={{ color: 'var(--red)', fontSize: 10, fontWeight: 700 }}>✕ SAVE FAILED</span>}
                <button className="btn-primary" onClick={saveTruth} disabled={!selectedUid || !!jsonError || saveStatus === 'saving'}>
                  {saveStatus === 'saving' ? 'SAVING...' : 'SAVE'}
                </button>
              </div>
            </div>
            {jsonError && (
              <div style={{ padding: '5px 16px', background: 'rgba(224,82,99,0.08)', borderBottom: '1px solid var(--red)', fontSize: 10, color: 'var(--red)', fontWeight: 600, flexShrink: 0 }}>
                ✕ {jsonError}
              </div>
            )}
            <div style={{ flex: 1, overflow: 'hidden', display: 'flex' }}>
              {/* Line numbers */}
              <div style={{ width: 48, flexShrink: 0, background: 'var(--bg-input)', borderRight: '1px solid var(--line-dim)', padding: '10px 0', overflowY: 'hidden', textAlign: 'right' }}>
                {Array.from({ length: lineCount }, (_, i) => (
                  <div key={i} style={{ paddingRight: 8, color: 'var(--muted)', fontSize: 11, lineHeight: '19.2px' }}>{i + 1}</div>
                ))}
              </div>
              {loading
                ? <div style={{ flex: 1, padding: 20, color: 'var(--muted)', fontSize: 11 }}>LOADING...</div>
                : <textarea
                    value={truthText}
                    onChange={e => handleTruthChange(e.target.value)}
                    style={{ flex: 1, height: '100%', resize: 'none', border: 'none', padding: '10px 14px', fontSize: 12, lineHeight: 1.6, background: 'var(--bg-input)', color: jsonError ? 'rgba(240,246,255,0.4)' : 'var(--white)' }}
                    spellCheck={false}
                    placeholder={!selectedUid ? 'Select a profile to edit.' : ''}
                  />
              }
            </div>
            <div style={{ height: 28, borderTop: '1px solid var(--line-dim)', background: 'var(--bg-panel)', display: 'flex', alignItems: 'center', padding: '0 16px', gap: 20, fontSize: 10, color: 'var(--muted)', flexShrink: 0 }}>
              <span>{lineCount} LINES</span>
              <span>{new Blob([truthText]).size} BYTES</span>
              <span>UTF-8 · JSON</span>
            </div>
          </div>
        )}

        {/* ── Tab 2: Generation Defaults ──────────────────────────── */}
        {activeTab === 'defaults' && (
          <div style={{ flex: 1, overflow: 'auto', display: 'flex', flexDirection: 'column' }}>
            {/* Toolbar */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '0 16px', height: 40, borderBottom: '1px solid var(--line)', background: 'var(--bg-panel)', flexShrink: 0 }}>
              <span className="bp-label">GENERATION DEFAULTS</span>
              <span style={{ fontSize: 10, color: 'var(--muted)' }}>applied automatically when starting a run</span>
              <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 10 }}>
                {prefStatus === 'saved' && <span style={{ color: 'var(--green)', fontSize: 10, fontWeight: 700 }}>✓ SAVED</span>}
                {prefStatus === 'error' && <span style={{ color: 'var(--red)', fontSize: 10, fontWeight: 700 }}>✕ SAVE FAILED</span>}
                <button className="btn-primary" onClick={savePreferences} disabled={!selectedUid || prefStatus === 'saving'}>
                  {prefStatus === 'saving' ? 'SAVING...' : 'SAVE DEFAULTS'}
                </button>
              </div>
            </div>

            {!selectedUid && (
              <div style={{ padding: 24, color: 'var(--muted)', fontSize: 11 }}>Select a profile first.</div>
            )}

            {selectedUid && (
              <div style={{ padding: 24 }}>
                <div style={{ marginBottom: 16, fontSize: 11, color: 'var(--muted)', lineHeight: 1.8 }}>
                  Toggle which sections should be <strong style={{ color: 'var(--white)' }}>included</strong> by default when generating a resume.
                  These defaults are pre-loaded on the Generate page and can be overridden per-run.
                </div>

                {/* Section grid */}
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 1, border: '1px solid var(--line)' }}>
                  {SECTIONS.map(({ key, label, desc }) => {
                    const included = !omissions[key]
                    return (
                      <div
                        key={key}
                        onClick={() => toggleOmission(key)}
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: 14,
                          padding: '14px 18px',
                          cursor: 'pointer',
                          background: included ? 'rgba(12,84,165,0.10)' : 'var(--bg-input)',
                          borderBottom: '1px solid var(--line-dim)',
                          borderRight: '1px solid var(--line-dim)',
                        }}
                      >
                        {/* Toggle indicator */}
                        <div style={{
                          width: 32, height: 18, flexShrink: 0,
                          background: included ? 'var(--cyan-bright)' : 'var(--line)',
                          border: `1px solid ${included ? 'var(--cyan-bright)' : 'var(--line)'}`,
                          display: 'flex', alignItems: 'center',
                          padding: '0 3px',
                          position: 'relative',
                        }}>
                          <div style={{
                            width: 10, height: 12,
                            background: included ? '#fff' : 'var(--muted)',
                            position: 'absolute',
                            left: included ? 'calc(100% - 13px)' : '3px',
                          }} />
                        </div>
                        <div>
                          <div style={{ fontSize: 12, fontWeight: 700, color: included ? 'var(--white)' : 'var(--muted)', marginBottom: 2, letterSpacing: '0.05em' }}>
                            {label}
                          </div>
                          <div style={{ fontSize: 10, color: 'var(--muted)' }}>{desc}</div>
                        </div>
                        <div style={{ marginLeft: 'auto', fontSize: 10, fontWeight: 700, color: included ? 'var(--green)' : 'var(--red)', letterSpacing: '0.08em' }}>
                          {included ? 'INCLUDE' : 'OMIT'}
                        </div>
                      </div>
                    )
                  })}
                </div>

                {/* Reset */}
                <div style={{ marginTop: 16, display: 'flex', gap: 8 }}>
                  <button className="btn-ghost" onClick={() => setOmissions({ ...DEFAULT_OMISSIONS })}>
                    RESET TO ALL INCLUDED
                  </button>
                  <button className="btn-ghost" onClick={() => setOmissions(Object.fromEntries(SECTIONS.map(s => [s.key, true])) as Omissions)}>
                    OMIT ALL
                  </button>
                </div>
              </div>
            )}
          </div>
        )}

        {activeTab === 'templates' && (
          <div style={{ flex: 1, overflow: 'hidden', display: 'grid', gridTemplateColumns: '260px 1fr' }}>
            <div style={{ borderRight: '1px solid var(--line)', background: 'var(--bg-panel)', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
              <div style={{ padding: 12, borderBottom: '1px solid var(--line)' }}>
                <button className="btn-primary" onClick={addTemplate} disabled={!selectedUid} style={{ width: '100%' }}>ADD TEMPLATE</button>
              </div>
              <div style={{ flex: 1, overflowY: 'auto' }}>
                {templates.map(t => (
                  <div
                    key={t.id}
                    onClick={() => selectTemplate(t.id)}
                    style={{
                      padding: '10px 14px',
                      borderBottom: '1px solid var(--line-dim)',
                      cursor: 'pointer',
                      background: t.id === selectedTemplateId ? 'rgba(12,84,165,0.14)' : 'transparent',
                      borderLeft: t.id === selectedTemplateId ? '2px solid var(--cyan-bright)' : '2px solid transparent',
                    }}
                  >
                    <div style={{ fontSize: 12, fontWeight: 700, color: t.id === selectedTemplateId ? 'var(--cyan-bright)' : 'var(--white)', marginBottom: 3 }}>
                      {t.name}
                    </div>
                    <div style={{ color: t.is_default ? 'var(--green)' : 'var(--muted)', fontSize: 10 }}>
                      {t.is_default ? 'DEFAULT' : new Date(t.updated_at).toLocaleDateString()}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div style={{ minWidth: 0, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, height: 44, padding: '0 16px', borderBottom: '1px solid var(--line)', background: 'var(--bg-panel)', flexShrink: 0 }}>
                <input
                  value={templateName}
                  onChange={e => { setTemplateName(e.target.value); setTemplateStatus('idle') }}
                  placeholder="Template name"
                  style={{ ...inputStyle, maxWidth: 360 }}
                  disabled={!selectedTemplateId}
                />
                <div style={{ marginLeft: 'auto', display: 'flex', gap: 8, alignItems: 'center' }}>
                  {templateStatus === 'saved' && <span style={{ color: 'var(--green)', fontSize: 10, fontWeight: 700 }}>SAVED</span>}
                  {templateStatus === 'error' && <span style={{ color: 'var(--red)', fontSize: 10, fontWeight: 700 }}>SAVE FAILED</span>}
                  
                  {selectedTemplateId && (
                    <div style={{ display: 'flex', background: 'var(--bg-input)', padding: 2, borderRadius: 2, border: '1px solid var(--line)', marginRight: 16 }}>
                      <button 
                        onClick={() => setTemplateView('html')}
                        style={{ background: templateView === 'html' ? 'var(--line)' : 'transparent', border: 'none', color: templateView === 'html' ? 'var(--white)' : 'var(--muted)', fontSize: 10, padding: '2px 8px', fontWeight: 700, cursor: 'pointer' }}
                      >JINJA</button>
                      <button 
                        onClick={() => setTemplateView('css')}
                        style={{ background: templateView === 'css' ? 'var(--line)' : 'transparent', border: 'none', color: templateView === 'css' ? 'var(--white)' : 'var(--muted)', fontSize: 10, padding: '2px 8px', fontWeight: 700, cursor: 'pointer' }}
                      >CSS</button>
                    </div>
                  )}

                  <button className="btn-ghost" onClick={setDefaultTemplate} disabled={!selectedTemplateId}>SET DEFAULT</button>
                  <button className="btn-ghost" onClick={deleteTemplate} disabled={!selectedTemplateId} style={{ color: 'var(--red)', borderColor: 'var(--red)' }}>DELETE</button>
                  <button className="btn-primary" onClick={saveTemplate} disabled={!selectedTemplateId || templateStatus === 'saving'}>
                    {templateStatus === 'saving' ? 'SAVING...' : 'SAVE'}
                  </button>
                </div>
              </div>
              {selectedTemplateId ? (
                templateView === 'html' ? (
                  <textarea
                    value={templateContent}
                    onChange={e => { setTemplateContent(e.target.value); setTemplateStatus('idle') }}
                    spellCheck={false}
                    style={{ flex: 1, resize: 'none', border: 'none', padding: 14, fontSize: 12, lineHeight: 1.6, background: 'var(--bg-input)', color: 'var(--white)' }}
                  />
                ) : (
                  <textarea
                    value={templateCssContent}
                    onChange={e => { setTemplateCssContent(e.target.value); setTemplateStatus('idle') }}
                    spellCheck={false}
                    placeholder="/* Custom CSS for this template. Leave empty to use default styles. */"
                    style={{ flex: 1, resize: 'none', border: 'none', padding: 14, fontSize: 12, lineHeight: 1.6, background: 'var(--bg-input)', color: 'var(--white)' }}
                  />
                )
              ) : (
                <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--muted)', fontSize: 11 }}>
                  SELECT OR ADD A TEMPLATE
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

const inputStyle: CSSProperties = {
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
