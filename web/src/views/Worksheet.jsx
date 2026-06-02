import { useState, useRef, useEffect } from 'react'
import { Play, Plus, ChevronDown, Clock, Rows, Database, Cpu, Hash, X, Loader, Unplug } from 'lucide-react'
import { createSession, deleteSession, runQuery } from '../api'

const PLACEHOLDER = `-- Flashpoint SQL Worksheet
-- ⌘↵ to run  •  connects a warehouse automatically on first run

SELECT
  bucket,
  COUNT(*) AS cnt
FROM (
  SELECT id % 10 AS bucket
  FROM range(1000000)
) GROUP BY bucket
ORDER BY bucket`

export function Worksheet() {
  const [sql, setSql] = useState(PLACEHOLDER)
  const [running, setRunning] = useState(false)
  const [connecting, setConnecting] = useState(false)
  const [results, setResults] = useState(null)
  const [stats, setStats] = useState(null)
  const [error, setError] = useState(null)
  const [session, setSession] = useState(null)  // {session_id, endpoint}
  const textareaRef = useRef(null)

  // Clean up session when unmounting
  useEffect(() => {
    return () => {
      if (session) deleteSession(session.session_id).catch(() => {})
    }
  }, [session])

  const disconnect = async () => {
    if (!session) return
    await deleteSession(session.session_id).catch(() => {})
    setSession(null)
    setResults(null)
    setStats(null)
    setError(null)
  }

  const run = async () => {
    setRunning(true)
    setError(null)

    try {
      let activeSession = session

      // Auto-connect on first run
      if (!activeSession) {
        setConnecting(true)
        try {
          activeSession = await createSession()
          setSession(activeSession)
        } finally {
          setConnecting(false)
        }
      }

      const result = await runQuery(activeSession.session_id, sql.trim())
      setStats({
        duration: result.duration_ms,
        rows: result.row_count,
        queryId: result.query_id,
        bytes: '—',
        tasks: '—',
        executors: '—',
        endpoint: activeSession.endpoint,
      })
      setResults({ columns: result.columns, rows: result.rows })
    } catch (err) {
      setError(err.message)
      // If session is gone, clear it so next run reconnects
      if (err.message?.includes('session not found') || err.message?.includes('session not running')) {
        setSession(null)
      }
    } finally {
      setRunning(false)
    }
  }

  const isConnected = !!session
  const isLoading = running || connecting

  return (
    <div style={s.root}>
      {/* Tab bar */}
      <div style={s.tabBar}>
        <Tab active>Sheet 1</Tab>
        <button style={s.addTab} title="New worksheet">
          <Plus size={13} />
        </button>
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 8 }}>
          <SessionIndicator session={session} connecting={connecting} onDisconnect={disconnect} />
          <WarehousePicker />
        </div>
      </div>

      {/* Editor */}
      <div style={s.editorWrap}>
        <div style={s.lineNums} aria-hidden>
          {sql.split('\n').map((_, i) => (
            <div key={i} style={s.lineNum}>{i + 1}</div>
          ))}
        </div>
        <textarea
          ref={textareaRef}
          style={s.editor}
          value={sql}
          onChange={e => setSql(e.target.value)}
          spellCheck={false}
          onKeyDown={e => {
            if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
              e.preventDefault()
              if (!isLoading) run()
            }
            if (e.key === 'Tab') {
              e.preventDefault()
              const { selectionStart: ss, selectionEnd: se } = e.target
              setSql(v => v.slice(0, ss) + '  ' + v.slice(se))
              requestAnimationFrame(() => {
                e.target.selectionStart = e.target.selectionEnd = ss + 2
              })
            }
          }}
        />
      </div>

      {/* Run bar */}
      <div style={s.runBar}>
        <button
          style={{ ...s.runBtn, ...(isLoading ? s.runBtnRunning : {}) }}
          onClick={run}
          disabled={isLoading}
        >
          {isLoading
            ? <Loader size={12} style={{ animation: 'spin 1s linear infinite' }} />
            : <Play size={12} fill="currentColor" />}
          {connecting ? 'Connecting…' : running ? 'Running…' : 'Run'}
          {!isLoading && <span style={s.kbd}>⌘↵</span>}
        </button>

        {stats && <StatBar stats={stats} />}
      </div>

      {/* Results */}
      {(results || error) && (
        <div style={s.resultsPane}>
          {error ? (
            <ErrorMsg msg={error} onDismiss={() => setError(null)} />
          ) : (
            <ResultTable results={results} />
          )}
        </div>
      )}

      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  )
}

function SessionIndicator({ session, connecting, onDisconnect }) {
  if (connecting) {
    return (
      <div style={indS.pill}>
        <Loader size={10} style={{ animation: 'spin 1s linear infinite', color: 'var(--amber)' }} />
        <span style={indS.text}>connecting…</span>
      </div>
    )
  }
  if (!session) return null
  return (
    <div style={indS.pill}>
      <span style={indS.dot} />
      <span style={indS.text} title={session.endpoint}>{session.endpoint?.replace('sc://', '').split(':')[0].slice(-8)}</span>
      <button style={indS.closeBtn} onClick={onDisconnect} title="Disconnect">
        <Unplug size={10} />
      </button>
    </div>
  )
}

function Tab({ children }) {
  return (
    <div style={{ ...tabS.tab, ...tabS.tabActive }}>
      <span>{children}</span>
    </div>
  )
}

function WarehousePicker() {
  return (
    <button style={wpS.btn}>
      <Cpu size={12} style={{ color: 'var(--amber)' }} />
      <span>dev-xs</span>
      <ChevronDown size={11} style={{ color: 'var(--text-dim)' }} />
    </button>
  )
}

function StatBar({ stats }) {
  return (
    <div style={stS.bar}>
      <Stat icon={<Clock size={11} />} value={`${stats.duration}ms`} />
      <Sep />
      <Stat icon={<Rows size={11} />} value={`${stats.rows.toLocaleString()} rows`} />
      {stats.queryId && <><Sep /><Stat icon={<Hash size={11} />} value={stats.queryId} /></>}
      {stats.bytes !== '—' && <><Sep /><Stat icon={<Database size={11} />} value={stats.bytes} /></>}
      {stats.executors !== '—' && <><Sep /><Stat icon={<Cpu size={11} />} value={`${stats.executors}×exec`} /></>}
    </div>
  )
}

function Stat({ icon, value }) {
  return (
    <div style={stS.stat}>
      <span style={stS.icon}>{icon}</span>
      <span>{value}</span>
    </div>
  )
}

function Sep() {
  return <div style={{ width: 1, height: 12, background: 'var(--border)' }} />
}

function ResultTable({ results }) {
  return (
    <div style={rtS.wrap}>
      <table style={rtS.table}>
        <thead>
          <tr>
            <th style={{ ...rtS.th, ...rtS.rowNumTh }}>#</th>
            {results.columns.map(c => (
              <th key={c} style={rtS.th}>{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {results.rows.map((row, i) => (
            <tr key={i} style={i % 2 === 0 ? {} : rtS.altRow}>
              <td style={{ ...rtS.td, ...rtS.rowNum }}>{i + 1}</td>
              {row.map((cell, j) => (
                <td key={j} style={rtS.td}>{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function ErrorMsg({ msg, onDismiss }) {
  return (
    <div style={errS.box}>
      <span style={errS.text}>{msg}</span>
      <button style={errS.close} onClick={onDismiss}><X size={12} /></button>
    </div>
  )
}

// ---- styles ----
const s = {
  root: { flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', background: 'var(--bg-base)' },
  tabBar: {
    display: 'flex', alignItems: 'center', height: 34,
    background: 'var(--bg-surface)', borderBottom: '1px solid var(--border-dim)',
    padding: '0 8px', gap: 2, flexShrink: 0,
  },
  addTab: {
    width: 24, height: 24, display: 'flex', alignItems: 'center', justifyContent: 'center',
    background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-dim)',
    borderRadius: 'var(--radius-sm)', marginLeft: 2,
  },
  editorWrap: {
    display: 'flex', flex: '1 1 200px', overflow: 'auto',
    background: 'var(--bg-base)', borderBottom: '1px solid var(--border-dim)',
    minHeight: 160, maxHeight: '50vh',
  },
  lineNums: {
    padding: '12px 0', minWidth: 40, textAlign: 'right',
    background: 'var(--bg-surface)', borderRight: '1px solid var(--border-dim)',
    flexShrink: 0, userSelect: 'none',
  },
  lineNum: {
    padding: '0 10px', height: '1.6em', fontFamily: 'var(--font-mono)',
    fontSize: 11, color: 'var(--text-dim)', lineHeight: '1.6em',
  },
  editor: {
    flex: 1, padding: '12px 16px', background: 'transparent', border: 'none',
    resize: 'none', fontFamily: 'var(--font-mono)', fontSize: 12.5,
    lineHeight: '1.6em', color: 'var(--text-mono)', outline: 'none',
    caretColor: 'var(--amber)', whiteSpace: 'pre', overflowWrap: 'normal',
  },
  runBar: {
    display: 'flex', alignItems: 'center', gap: 16, padding: '8px 16px',
    background: 'var(--bg-surface)', borderBottom: '1px solid var(--border-dim)', flexShrink: 0,
  },
  runBtn: {
    display: 'flex', alignItems: 'center', gap: 6, height: 28, padding: '0 12px',
    background: 'var(--amber)', color: '#0d0e10', border: 'none',
    borderRadius: 'var(--radius-sm)', cursor: 'pointer', fontSize: 12,
    fontWeight: 600, fontFamily: 'var(--font-ui)', letterSpacing: '0.01em',
    transition: 'opacity 0.12s',
  },
  runBtnRunning: { opacity: 0.6, cursor: 'not-allowed' },
  kbd: { fontFamily: 'var(--font-mono)', fontSize: 10, opacity: 0.5, marginLeft: 2 },
  resultsPane: { flex: '1 1 120px', overflow: 'auto', background: 'var(--bg-base)' },
}

const tabS = {
  tab: {
    display: 'flex', alignItems: 'center', gap: 6, height: 28, padding: '0 12px',
    borderRadius: 'var(--radius-sm)', cursor: 'pointer', color: 'var(--text-secondary)',
    fontSize: 12, userSelect: 'none',
  },
  tabActive: { background: 'var(--bg-raised)', color: 'var(--text-primary)', fontWeight: 500 },
}

const wpS = {
  btn: {
    display: 'flex', alignItems: 'center', gap: 5, height: 24, padding: '0 10px',
    background: 'var(--bg-raised)', border: '1px solid var(--border)',
    borderRadius: 'var(--radius-sm)', cursor: 'pointer', color: 'var(--text-primary)',
    fontSize: 12, fontFamily: 'var(--font-ui)',
  },
}

const stS = {
  bar: { display: 'flex', alignItems: 'center', gap: 10, flex: 1 },
  stat: {
    display: 'flex', alignItems: 'center', gap: 4,
    color: 'var(--text-secondary)', fontSize: 11, fontFamily: 'var(--font-mono)',
  },
  icon: { color: 'var(--text-dim)', display: 'flex' },
}

const rtS = {
  wrap: { overflowX: 'auto' },
  table: { width: '100%', borderCollapse: 'collapse', fontSize: 12, fontFamily: 'var(--font-mono)' },
  th: {
    padding: '7px 16px', textAlign: 'left', color: 'var(--text-secondary)',
    fontWeight: 500, fontSize: 11, letterSpacing: '0.04em', textTransform: 'uppercase',
    background: 'var(--bg-surface)', borderBottom: '1px solid var(--border)',
    position: 'sticky', top: 0, whiteSpace: 'nowrap',
  },
  rowNumTh: { width: 48, color: 'var(--text-dim)', textAlign: 'right' },
  td: { padding: '5px 16px', color: 'var(--text-mono)', borderBottom: '1px solid var(--border-dim)', whiteSpace: 'nowrap' },
  rowNum: { color: 'var(--text-dim)', textAlign: 'right', fontSize: 10 },
  altRow: { background: 'rgba(255,255,255,0.015)' },
}

const errS = {
  box: {
    display: 'flex', alignItems: 'flex-start', gap: 8, margin: 12, padding: '10px 14px',
    background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.25)',
    borderRadius: 'var(--radius)', color: 'var(--red)', fontSize: 12, fontFamily: 'var(--font-mono)',
  },
  text: { flex: 1 },
  close: { background: 'none', border: 'none', cursor: 'pointer', color: 'inherit', padding: 0, flexShrink: 0 },
}

const indS = {
  pill: {
    display: 'flex', alignItems: 'center', gap: 5,
    background: 'var(--amber-bg)', border: '1px solid var(--amber-border)',
    borderRadius: 100, padding: '2px 8px',
  },
  dot: { width: 5, height: 5, borderRadius: '50%', background: 'var(--green)', boxShadow: '0 0 4px var(--green)' },
  text: { fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--amber)' },
  closeBtn: {
    background: 'none', border: 'none', cursor: 'pointer', color: 'var(--amber)',
    display: 'flex', alignItems: 'center', padding: 0, marginLeft: 2,
  },
}
