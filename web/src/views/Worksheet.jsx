import { useState, useRef, useEffect, useMemo } from 'react'
import { Play, Plus, ChevronDown, Clock, Rows, Database, Cpu, Hash, X, Loader, Unplug } from 'lucide-react'
import { createWarehouse, deleteWarehouse, runQuery } from '../api'
import { QueryDag } from '../components/QueryDag'
import { OfflineBanner } from '../components/OfflineBanner'

// Lightweight SQL highlighter — zero deps, one pass, good enough for a
// worksheet. Token classes are matched to the mockup palette.
const KEYWORDS = new Set(
  `SELECT FROM WHERE JOIN LEFT RIGHT INNER ON GROUP BY ORDER AS ASC DESC AND OR NOT IN IS NULL
   TRUE FALSE CASE WHEN THEN ELSE END CREATE REPLACE TEMPORARY VIEW USING OPTIONS DROP TABLE
   IF EXISTS LIMIT DISTINCT HAVING UNION ALL SET WITH OVER PARTITION ROWS BETWEEN
   CURRENT INTERVAL ADD COLUMN TO VALUES INTO`.split(/\s+/)
)

function tokenizeSql(sql) {
  const out = []
  const re = /(--[^\n]*)|('(?:[^']|'')*')|(\b\d+(?:\.\d+)?\b)|([A-Za-z_][A-Za-z0-9_]*)(?=\s*\()|\b([A-Za-z_][A-Za-z0-9_]*)\b|(\s+)|(.)/g
  let m
  while ((m = re.exec(sql))) {
    const [full, cmt, str, num, fn, word] = m
    if (cmt) out.push([full, 'sql-cmt'])
    else if (str) out.push([full, 'sql-str'])
    else if (num) out.push([full, 'sql-num'])
    else if (fn) out.push([full, 'sql-fn'])
    else if (word) out.push([full, KEYWORDS.has(word.toUpperCase()) ? 'sql-kw' : 'sql-plain'])
    else out.push([full, 'sql-plain'])
  }
  return out
}

function esc(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function SqlHighlight({ sql }) {
  const html = useMemo(
    () => tokenizeSql(sql).map(([t, cls]) => `<span class="${cls}">${esc(t)}</span>`).join(''),
    [sql]
  )
  return <pre style={s.hl} dangerouslySetInnerHTML={{ __html: html || '\n' }} />
}

function FlowStrip({ gatewayOnline, connecting, running, hasResults, hasProfile, elapsed }) {
  const dim = { ...flowS.step, ...flowS.grey }
  let steps
  if (!gatewayOnline) {
    steps = [{ label: 'offline', style: { ...flowS.step, ...flowS.red } }]
  } else if (connecting) {
    steps = [{ label: 'submitted', style: flowS.done }, { label: 'connecting…', style: flowS.cur }]
  } else if (running) {
    steps = [{ label: 'submitted', style: flowS.done }, { label: `running · ${elapsed}s`, style: flowS.cur }]
  } else if (hasResults && hasProfile) {
    steps = [
      { label: 'submitted', style: flowS.done },
      { label: 'running', style: flowS.done },
      { label: 'profile', style: flowS.done },
      { label: 'done', style: flowS.cur },
    ]
  } else if (hasResults) {
    steps = [
      { label: 'submitted', style: flowS.done },
      { label: 'running', style: flowS.done },
      { label: 'done', style: flowS.cur },
    ]
  } else {
    steps = [
      { label: 'submitted', style: dim },
      { label: 'running', style: dim },
      { label: 'profile', style: dim },
      { label: 'done', style: dim },
    ]
  }
  return (
    <div style={flowS.bar}>
      {steps.map((st, i) => (
        <span key={st.label} style={{ display: 'contents' }}>
          {i > 0 && <span style={flowS.arrow}>→</span>}
          <span style={st.style}>{st.label}</span>
        </span>
      ))}
    </div>
  )
}

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

export function Worksheet({ gatewayOnline }) {
  const [sql, setSql] = useState(PLACEHOLDER)
  const [running, setRunning] = useState(false)
  const [connecting, setConnecting] = useState(false)
  const [results, setResults] = useState(null)
  const [profile, setProfile] = useState(null)
  const [resultTab, setResultTab] = useState('results')
  const [stats, setStats] = useState(null)
  const [error, setError] = useState(null)
  const [session, setSession] = useState(null)  // {session_id, endpoint}
  const [elapsed, setElapsed] = useState(0)
  const textareaRef = useRef(null)
  const hlRef = useRef(null)

  // Clean up session when unmounting
  useEffect(() => {
    return () => {
      if (session) deleteWarehouse(session.name).catch(() => {})
    }
  }, [session])

  const disconnect = async () => {
    if (!session) return
    await deleteWarehouse(session.name).catch(() => {})
    setSession(null)
    setResults(null)
    setProfile(null)
    setStats(null)
    setError(null)
  }

  // Live elapsed-seconds while a query is running (for the flow strip).
  useEffect(() => {
    if (!running) return
    const iv = setInterval(() => setElapsed(t => t + 1), 1000)
    return () => clearInterval(iv)
  }, [running])

  // Keep the highlight layer scrolled in lockstep with the (transparent) editor.
  const syncScroll = () => {
    const ta = textareaRef.current, hl = hlRef.current
    if (ta && hl) {
      hl.scrollTop = ta.scrollTop
      hl.scrollLeft = ta.scrollLeft
    }
  }

  const run = async () => {
    setRunning(true)
    setElapsed(0)
    setError(null)

    try {
      let activeWarehouse = session

      // Auto-connect on first run
      if (!activeWarehouse) {
        setConnecting(true)
        try {
          activeWarehouse = await createWarehouse(`ws-${Date.now().toString(36)}`)
          setSession(activeWarehouse)
        } finally {
          setConnecting(false)
        }
      }

      const result = await runQuery(activeWarehouse.name, sql.trim())
      setStats({
        duration: result.duration_ms,
        rows: result.row_count,
        queryId: result.query_id,
        bytes: '—',
        tasks: '—',
        executors: '—',
        endpoint: activeWarehouse.endpoint,
      })
      setResults({ columns: result.columns, rows: result.rows })
      setProfile(result.profile || null)
      setResultTab('results')
    } catch (err) {
      setError(err.message)
      // A failed run must not leave a stale profile/results from a previous
      // query on screen — the current query's profile is simply unknown.
      setProfile(null)
      setResults(null)
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
      {!gatewayOnline && <OfflineBanner />}
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
        <div style={s.editorStack}>
          <div ref={hlRef} style={s.hlWrap} aria-hidden>
            <SqlHighlight sql={sql} />
          </div>
          <textarea
            ref={textareaRef}
            style={s.editor}
            value={sql}
            onChange={e => setSql(e.target.value)}
            onScroll={syncScroll}
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
      </div>

      {/* Run bar */}
      <div style={s.runBar}>
        <button
          style={{ ...s.runBtn, ...(isLoading ? s.runBtnRunning : {}), ...(!gatewayOnline ? s.runBtnOffline : {}) }}
          onClick={run}
          disabled={isLoading || !gatewayOnline}
          title={!gatewayOnline ? 'Gateway offline — run `tofu apply` to wake it' : undefined}
        >
          {isLoading
            ? <Loader size={12} style={{ animation: 'spin 1s linear infinite' }} />
            : <Play size={12} fill="currentColor" />}
          {!gatewayOnline ? 'Offline' : connecting ? 'Connecting…' : running ? 'Running…' : 'Run'}
          {!isLoading && gatewayOnline && <span style={s.kbd}>⌘↵</span>}
        </button>

        <FlowStrip
          gatewayOnline={gatewayOnline}
          connecting={connecting}
          running={running}
          hasResults={!!results}
          hasProfile={!!profile}
          elapsed={elapsed}
        />

        {stats && <StatBar stats={stats} />}
      </div>

      {/* Results */}
      {(results || error) && (
        <div style={s.resultsPane}>
          {error ? (
            <ErrorMsg msg={error} onDismiss={() => setError(null)} />
          ) : (
            <>
              <div style={s.resultTabs}>
                <ResultTab active={resultTab === 'results'} onClick={() => setResultTab('results')}>
                  Results
                </ResultTab>
                {profile && (
                  <ResultTab active={resultTab === 'profile'} onClick={() => setResultTab('profile')}>
                    Query Profile
                  </ResultTab>
                )}
              </div>
              <div style={s.resultBody}>
                {resultTab === 'results'
                  ? <ResultTable results={results} />
                  : <QueryDag profile={profile} />}
              </div>
            </>
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
      <span style={indS.text} title={session.endpoint}>{session.endpoint?.replace('sc://', '').split(':')[0]}</span>
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

function ResultTab({ active, onClick, children }) {
  return (
    <button
      style={{ ...rtabS.tab, ...(active ? rtabS.active : {}) }}
      onClick={onClick}
    >
      {children}
    </button>
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
    display: 'flex', flex: '1 1 200px', overflow: 'hidden',
    background: 'var(--bg-base)', borderBottom: '1px solid var(--border-dim)',
    minHeight: 160, maxHeight: '50vh',
  },
  lineNums: {
    padding: '12px 0', minWidth: 40, textAlign: 'right',
    background: 'var(--bg-surface)', borderRight: '1px solid var(--border-dim)',
    flexShrink: 0, userSelect: 'none', overflow: 'hidden',
  },
  lineNum: {
    padding: '0 10px', height: '1.6em', fontFamily: 'var(--font-mono)',
    fontSize: 11, color: 'var(--text-dim)', lineHeight: '1.6em',
  },
  editorStack: {
    position: 'relative', flex: 1, minWidth: 0, overflow: 'hidden',
  },
  hlWrap: {
    position: 'absolute', inset: 0, overflow: 'hidden', pointerEvents: 'none',
  },
  hl: {
    margin: 0, padding: '12px 16px', fontFamily: 'var(--font-mono)',
    fontSize: 12.5, lineHeight: '1.6em', whiteSpace: 'pre',
    color: 'var(--text-mono)', '-webkit-font-smoothing': 'antialiased',
    overflow: 'hidden', pointerEvents: 'none',
    fontVariantLigatures: 'none',
  },
  editor: {
    position: 'absolute', inset: 0, padding: '12px 16px',
    background: 'transparent', border: 'none', resize: 'none',
    fontFamily: 'var(--font-mono)', fontSize: 12.5,
    lineHeight: '1.6em', color: 'transparent', outline: 'none',
    caretColor: 'var(--amber)', whiteSpace: 'pre', overflowWrap: 'normal',
    fontVariantLigatures: 'none',
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
  runBtnOffline: { background: 'var(--bg-raised)', color: 'var(--text-dim)', border: '1px solid var(--border)', cursor: 'not-allowed', fontWeight: 400 },
  kbd: { fontFamily: 'var(--font-mono)', fontSize: 10, opacity: 0.5, marginLeft: 2 },
  resultsPane: { flex: '1 1 120px', display: 'flex', flexDirection: 'column', overflow: 'hidden', background: 'var(--bg-base)' },
  resultTabs: {
    display: 'flex', alignItems: 'center', gap: 2, height: 32, flexShrink: 0,
    padding: '0 8px', background: 'var(--bg-surface)', borderBottom: '1px solid var(--border-dim)',
  },
  resultBody: { flex: 1, overflow: 'auto' },
}

const rtabS = {
  tab: {
    height: 24, padding: '0 10px', background: 'none', border: 'none', cursor: 'pointer',
    color: 'var(--text-dim)', fontSize: 11, fontWeight: 500, fontFamily: 'var(--font-ui)',
    letterSpacing: '0.02em', borderRadius: 'var(--radius-sm)',
  },
  active: { background: 'var(--bg-raised)', color: 'var(--text-primary)' },
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

// Query lifecycle strip — matches the mockup flow: submitted → running → profile → done.
const flowS = {
  bar: {
    display: 'flex', alignItems: 'center', gap: 6,
    fontFamily: 'var(--font-mono)', fontSize: 10,
    marginLeft: 'auto', flexShrink: 0, padding: '0 6px',
  },
  step: {
    padding: '2px 8px', borderRadius: 100,
    border: '1px solid var(--border)', background: 'var(--bg-surface)',
    color: 'var(--text-dim)', whiteSpace: 'nowrap',
  },
  done: {
    padding: '2px 8px', borderRadius: 100,
    border: '1px solid var(--amber-border)', background: 'var(--amber-bg)',
    color: 'var(--amber)', whiteSpace: 'nowrap',
  },
  cur: {
    padding: '2px 8px', borderRadius: 100,
    border: '1px solid var(--amber-border)', background: 'var(--amber)',
    color: '#1c1405', fontWeight: 600, whiteSpace: 'nowrap',
  },
  red: {
    padding: '2px 8px', borderRadius: 100,
    border: '1px solid rgba(239,68,68,0.4)', background: 'rgba(239,68,68,0.12)',
    color: 'var(--red)', whiteSpace: 'nowrap',
  },
  grey: { opacity: 0.45 },
  arrow: { color: 'var(--text-dim)', userSelect: 'none' },
}
