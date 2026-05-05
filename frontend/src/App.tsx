import { BrowserRouter, NavLink, Route, Routes } from 'react-router-dom'
import ProfilesPage from './pages/ProfilesPage'
import GeneratePage from './pages/GeneratePage'
import ScrapePage from './pages/ScrapePage'
import JobLibraryPage from './pages/JobLibraryPage'
import BatchProcessingPage from './pages/BatchProcessingPage'

export default function App() {
  return (
    <BrowserRouter>
      <nav className="bp-nav">
        <span className="bp-nav-logo">RESUMER</span>
        <NavLink
          to="/profiles"
          className={({ isActive }) => `bp-nav-link${isActive ? ' active' : ''}`}
        >
          01 / PROFILES
        </NavLink>
        <NavLink
          to="/generate"
          className={({ isActive }) => `bp-nav-link${isActive ? ' active' : ''}`}
        >
          02 / GENERATE
        </NavLink>
        <NavLink
          to="/scrape"
          className={({ isActive }) => `bp-nav-link${isActive ? ' active' : ''}`}
        >
          03 / SCRAPE INDEED
        </NavLink>
        <NavLink
          to="/library"
          className={({ isActive }) => `bp-nav-link${isActive ? ' active' : ''}`}
        >
          04 / JOB LIBRARY
        </NavLink>
        <NavLink
          to="/batch"
          className={({ isActive }) => `bp-nav-link${isActive ? ' active' : ''}`}
        >
          05 / BATCH PROCESS
        </NavLink>
        <div style={{ marginLeft: 'auto', color: 'var(--muted)', fontSize: 10, letterSpacing: '0.1em' }}>
          RESUMER · LOCAL
        </div>
      </nav>

      <div style={{ flex: 1, overflow: 'hidden' }}>
        <Routes>
          <Route path="/" element={<ProfilesPage />} />
          <Route path="/profiles" element={<ProfilesPage />} />
          <Route path="/generate" element={<GeneratePage />} />
          <Route path="/scrape" element={<ScrapePage />} />
          <Route path="/library" element={<JobLibraryPage />} />
          <Route path="/batch" element={<BatchProcessingPage />} />
        </Routes>
      </div>
    </BrowserRouter>
  )
}
