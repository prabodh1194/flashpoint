import { useState, useEffect } from 'react'
import { Sidebar } from './components/Sidebar'
import { Topbar } from './components/Topbar'
import { Worksheet } from './views/Worksheet'
import { Warehouses } from './views/Warehouses'
import { History } from './views/History'
import { DataExplorer } from './views/DataExplorer'

const VIEWS = ['worksheet', 'warehouses', 'history', 'explorer']

export default function App() {
  const [theme, setTheme] = useState(() =>
    localStorage.getItem('fp-theme') || 'dark'
  )
  const [view, setView] = useState('worksheet')
  const [navOpen, setNavOpen] = useState(false)

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
          onThemeToggle={toggleTheme}
        />
        <div style={styles.content}>
          {view === 'worksheet'  && <Worksheet />}
          {view === 'warehouses' && <Warehouses />}
          {view === 'history'    && <History />}
          {view === 'explorer'   && <DataExplorer />}
        </div>
      </div>
    </div>
  )
}

const styles = {
  shell: {
    display: 'flex',
    height: '100%',
    overflow: 'hidden',
    background: 'var(--bg-base)',
  },
  main: {
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
    overflow: 'hidden',
    minWidth: 0,
  },
  content: {
    flex: 1,
    overflow: 'hidden',
    display: 'flex',
    flexDirection: 'column',
  },
}
