import { useState, useEffect, useCallback } from 'react'
import { Sidebar } from './components/Sidebar'
import { Topbar } from './components/Topbar'
import { Worksheet } from './views/Worksheet'
import { Warehouses } from './views/Warehouses'
import { History } from './views/History'
import { QueryProfile } from './views/QueryProfile'
import { DataExplorer } from './views/DataExplorer'
import { Costs } from './views/Costs'
import { healthz } from './api'
import { navigate, useHashRoute } from './router'

const VALID_VIEWS = ['worksheet', 'warehouses', 'history', 'explorer', 'costs']

// #/worksheets | #/warehouses | #/history | #/history/:queryId | #/explorer
export function parseRoute(path) {
  const segs = path.split('/').filter(Boolean)
  const view = segs[0] || 'worksheet'
  if (!VALID_VIEWS.includes(view)) return { view: 'worksheet' }
  if (view === 'history' && segs[1]) return { view: 'history', queryId: segs[1] }
  return { view }
}

export default function App() {
  const route = useHashRoute()
  const { view, queryId } = parseRoute(route)

  const [theme, setTheme] = useState(() =>
    localStorage.getItem('fp-theme') || 'dark'
  )
  const [navOpen, setNavOpen] = useState(false)
  const [gatewayOnline, setGatewayOnline] = useState(false)

  // Normalize a bare URL (no hash) to the default view.
  useEffect(() => {
    if (!window.location.hash) window.history.replaceState(null, '', '#/worksheets')
  }, [])

  const checkGateway = useCallback(async () => {
    try {
      const h = await healthz()
      setGatewayOnline(h?.status === 'ok')
    } catch { setGatewayOnline(false) }
  }, [])

  useEffect(() => {
    checkGateway()
    const iv = setInterval(checkGateway, 15_000)
    return () => clearInterval(iv)
  }, [checkGateway])

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    localStorage.setItem('fp-theme', theme)
  }, [theme])

  const toggleTheme = () =>
    setTheme(t => (t === 'dark' ? 'light' : 'dark'))

  const goTo = (v) => navigate(`/${v}`)

  return (
    <div style={styles.shell}>
      <Sidebar
        active={view}
        onNav={goTo}
        open={navOpen}
        onToggle={() => setNavOpen(o => !o)}
      />
      <div style={styles.main}>
        <Topbar
          view={view}
          theme={theme}
          gatewayOnline={gatewayOnline}
          onThemeToggle={toggleTheme}
        />
        <div style={styles.content}>
          {view === 'history' && queryId ? (
            <QueryProfile queryId={queryId} onBack={() => navigate('/history')} />
          ) : (
            <>
              {view === 'worksheet'  && <Worksheet gatewayOnline={gatewayOnline} />}
              {view === 'warehouses' && <Warehouses gatewayOnline={gatewayOnline} />}
              {view === 'history'    && <History gatewayOnline={gatewayOnline} onOpenProfile={q => navigate(`/history/${q.query_id}`)} />}
              {view === 'explorer'   && <DataExplorer gatewayOnline={gatewayOnline} />}
              {view === 'costs'      && <Costs gatewayOnline={gatewayOnline} />}
            </>
          )}
        </div>
      </div>
    </div>
  )
}

const styles = {
  shell: {
    display: 'flex', height: '100%', overflow: 'hidden',
    background: 'var(--bg-base)',
  },
  main: {
    flex: 1, display: 'flex', flexDirection: 'column',
    overflow: 'hidden', minWidth: 0,
  },
  content: {
    flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column',
  },
}
