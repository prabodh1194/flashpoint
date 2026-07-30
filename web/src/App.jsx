import { useState, useEffect, useCallback } from 'react'
import { Sidebar } from './components/Sidebar'
import { Topbar } from './components/Topbar'
import { Worksheet } from './views/Worksheet'
import { Warehouses } from './views/Warehouses'
import { History } from './views/History'
import { DataExplorer } from './views/DataExplorer'
import { healthz } from './api'

export default function App() {
  const [theme, setTheme] = useState(() =>
    localStorage.getItem('fp-theme') || 'dark'
  )
  const [view, setView] = useState('worksheet')
  const [navOpen, setNavOpen] = useState(false)
  const [gatewayOnline, setGatewayOnline] = useState(false)

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

  return (
    <div style={styles.shell}>
      <Sidebar
        active={view}
        onNav={setView}
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
          {view === 'worksheet'  && <Worksheet gatewayOnline={gatewayOnline} />}
          {view === 'warehouses' && <Warehouses gatewayOnline={gatewayOnline} />}
          {view === 'history'    && <History gatewayOnline={gatewayOnline} />}
          {view === 'explorer'   && <DataExplorer gatewayOnline={gatewayOnline} />}
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
