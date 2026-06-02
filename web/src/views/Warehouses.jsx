import { useState, useEffect, useCallback } from 'react'
import { Zap, Play, Square, ChevronDown, Loader, RefreshCw } from 'lucide-react'
import { listSessions, createSession, deleteSession, fetchHistory } from '../api'

// Warehouse name registry — persisted to localStorage so names survive page reloads.
// Maps session_id -> { name, size, createdAt }
const REGISTRY_KEY = 'fp-warehouses'
const SIZES = ['XS', 'S', 'M', 'L', 'XL']
const EXECUTOR_COUNTS = { XS: 1, S: 2, M: 4, L: 8, XL: 16 }
const HOURLY_RATE = { XS: 0.08, S: 0.16, M: 0.32, L: 0.64, XL: 1.28 }

function loadRegistry() {
  try { return JSON.parse(localStorage.getItem(REGISTRY_KEY) || '{}') } catch { return {} }
}
function saveRegistry(r) { localStorage.setItem(REGISTRY_KEY, JSON.stringify(r)) }

let _whCounter = Object.keys(loadRegistry()).length + 1

export function Warehouses() {
  const [warehouses, setWarehouses] = useState([])
  const [loading, setLoading] = useState(true)
  const [creating, setCreating] = useState(false)
  const [newSize, setNewSize] = useState('XS')
  const [showSizePicker, setShowSizePicker] = useState(false)
  const [queryCounts, setQueryCounts] = useState({})  // session_id -> count

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const [sessionsResp, histResp] = await Promise.all([
        listSessions().catch(() => ({ sessions: [] })),
        fetchHistory().catch(() => ({ history: [] })),
      ])
      const registry = loadRegistry()
      const counts = {}
      for (const e of histResp.history) {
        counts[e.session_id] = (counts[e.session_id] || 0) + 1
      }
      setQueryCounts(counts)
      const whs = sessionsResp.sessions.map(sid => {
        const reg = registry[sid] || { name: `wh-${sid.slice(0, 6)}`, size: 'XS', createdAt: Date.now() }
        return { session_id: sid, ...reg, status: 'running' }
      })
      setWarehouses(whs)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { refresh() }, [refresh])

  const resume = async (size) => {
    setCreating(true)
    setShowSizePicker(false)
    try {
      const session = await createSession()
      const registry = loadRegistry()
      const name = `wh-${_whCounter++}`
      registry[session.session_id] = { name, size, createdAt: Date.now() }
      saveRegistry(registry)
      await refresh()
    } catch (err) {
      alert(`Failed to start warehouse: ${err.message}`)
    } finally {
      setCreating(false)
    }
  }

  const suspend = async (sid) => {
    setWarehouses(ws => ws.map(w => w.session_id === sid ? { ...w, status: 'stopping' } : w))
    try {
      await deleteSession(sid)
      const registry = loadRegistry()
      delete registry[sid]
      saveRegistry(registry)
      await refresh()
    } catch {
      await refresh()
    }
  }

  return (
    <div style={s.root}>
      <div style={s.header}>
        <h2 style={s.title}>Warehouses</h2>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <button style={s.refreshBtn} onClick={refresh} title="Refresh">
            <RefreshCw size={13} />
          </button>
          <div style={{ position: 'relative' }}>
            <button
              style={{ ...s.createBtn, ...(creating ? s.createBtnBusy : {}) }}
              onClick={() => !creating && setShowSizePicker(p => !p)}
              disabled={creating}
            >
              {creating
                ? <Loader size={13} style={{ animation: 'spin 1s linear infinite' }} />
                : <Zap size={13} />}
              {creating ? 'Starting…' : 'New Warehouse'}
              {!creating && <ChevronDown size={12} />}
            </button>
            {showSizePicker && (
              <div style={s.sizeMenu}>
                {SIZES.map(sz => (
                  <button key={sz} style={s.sizeOption} onClick={() => resume(sz)}>
                    <span style={s.sizeLabel}>{sz}</span>
                    <span style={s.sizeDetail}>{EXECUTOR_COUNTS[sz]} exec · ${HOURLY_RATE[sz].toFixed(2)}/hr</span>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {loading && warehouses.length === 0 ? (
        <div style={s.empty}><Loader size={18} style={{ animation: 'spin 1s linear infinite', color: 'var(--amber)' }} /></div>
      ) : warehouses.length === 0 ? (
        <div style={s.empty}>
          <p style={s.emptyText}>No warehouses running.</p>
          <p style={s.emptyHint}>Click "New Warehouse" to provision a Fargate Spark cluster.</p>
        </div>
      ) : (
        <div style={s.grid}>
          {warehouses.map(wh => (
            <WarehouseCard
              key={wh.session_id}
              wh={wh}
              queryCount={queryCounts[wh.session_id] || 0}
              onSuspend={() => suspend(wh.session_id)}
            />
          ))}
        </div>
      )}

      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  )
}

function WarehouseCard({ wh, queryCount, onSuspend }) {
  const stopping = wh.status === 'stopping'
  return (
    <div style={s.card}>
      <div style={s.cardTop}>
        <div style={s.cardName}>
          <span style={s.cardId}>{wh.name}</span>
          <StatusBadge status={stopping ? 'stopping' : wh.status} />
        </div>
        <button
          style={{ ...s.suspendBtn, ...(stopping ? s.suspendBtnBusy : {}) }}
          onClick={onSuspend}
          disabled={stopping}
        >
          {stopping
            ? <Loader size={11} style={{ animation: 'spin 1s linear infinite' }} />
            : <Square size={11} />}
          {stopping ? 'Stopping…' : 'Suspend'}
        </button>
      </div>

      <div style={s.cardMeta}>
        <MetaPair label="Size" value={wh.size} mono />
        <MetaPair label="Executors" value={`${EXECUTOR_COUNTS[wh.size] ?? '?'} active`} />
        <MetaPair label="Queries run" value={String(queryCount)} mono />
        <MetaPair label="Rate" value={`$${HOURLY_RATE[wh.size]?.toFixed(2) ?? '?'}/hr`} mono />
      </div>

      <div style={s.idRow}>
        <span style={s.sessionLabel}>Session</span>
        <span style={s.sessionId}>{wh.session_id.slice(0, 8)}…</span>
      </div>
    </div>
  )
}

function StatusBadge({ status }) {
  const cfg = {
    running:  { bg: 'rgba(34,197,94,0.1)',   border: 'rgba(34,197,94,0.3)',   color: '#22c55e', dot: true },
    stopping: { bg: 'rgba(239,68,68,0.08)',  border: 'rgba(239,68,68,0.25)',  color: 'var(--red)', dot: false },
  }
  const c = cfg[status] ?? cfg.running
  return (
    <div style={{ ...s.badge, background: c.bg, border: `1px solid ${c.border}`, color: c.color }}>
      {c.dot && <span style={{ ...s.dot, background: c.color }} />}
      {status}
    </div>
  )
}

function MetaPair({ label, value, mono }) {
  return (
    <div style={s.metaPair}>
      <span style={s.metaLabel}>{label}</span>
      <span style={{ ...s.metaVal, fontFamily: mono ? 'var(--font-mono)' : undefined }}>{value}</span>
    </div>
  )
}

const s = {
  root: { flex: 1, padding: 24, overflow: 'auto' },
  header: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 },
  title: { fontSize: 15, fontWeight: 500, color: 'var(--text-primary)' },
  refreshBtn: {
    width: 28, height: 28, display: 'flex', alignItems: 'center', justifyContent: 'center',
    background: 'var(--bg-raised)', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)',
    cursor: 'pointer', color: 'var(--text-dim)',
  },
  createBtn: {
    display: 'flex', alignItems: 'center', gap: 6, height: 30, padding: '0 12px',
    background: 'var(--amber-bg)', border: '1px solid var(--amber-border)',
    borderRadius: 'var(--radius-sm)', cursor: 'pointer', color: 'var(--amber)',
    fontSize: 12, fontFamily: 'var(--font-ui)', fontWeight: 500,
  },
  createBtnBusy: { opacity: 0.7, cursor: 'not-allowed' },
  sizeMenu: {
    position: 'absolute', top: 34, right: 0, zIndex: 10, minWidth: 180,
    background: 'var(--bg-raised)', border: '1px solid var(--border)', borderRadius: 'var(--radius)',
    boxShadow: '0 8px 24px rgba(0,0,0,0.4)', overflow: 'hidden',
  },
  sizeOption: {
    display: 'flex', alignItems: 'center', justifyContent: 'space-between', width: '100%',
    padding: '8px 14px', background: 'none', border: 'none', cursor: 'pointer',
    borderBottom: '1px solid var(--border-dim)',
  },
  sizeLabel: { fontFamily: 'var(--font-mono)', fontSize: 12, fontWeight: 600, color: 'var(--amber)' },
  sizeDetail: { fontSize: 11, color: 'var(--text-dim)', fontFamily: 'var(--font-mono)' },
  grid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 12 },
  card: {
    background: 'var(--bg-surface)', border: '1px solid var(--amber-border)',
    borderRadius: 'var(--radius-lg)', padding: 16, display: 'flex', flexDirection: 'column', gap: 12,
  },
  cardTop: { display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8 },
  cardName: { display: 'flex', alignItems: 'center', gap: 8 },
  cardId: { fontFamily: 'var(--font-mono)', fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' },
  suspendBtn: {
    display: 'flex', alignItems: 'center', gap: 4, height: 24, padding: '0 8px',
    background: 'rgba(239,68,68,0.06)', border: '1px solid rgba(239,68,68,0.25)',
    borderRadius: 'var(--radius-sm)', cursor: 'pointer', color: 'var(--red)',
    fontSize: 11, fontFamily: 'var(--font-ui)', flexShrink: 0,
  },
  suspendBtnBusy: { opacity: 0.6, cursor: 'not-allowed' },
  badge: {
    display: 'flex', alignItems: 'center', gap: 5, padding: '2px 8px',
    borderRadius: 100, fontSize: 11, fontFamily: 'var(--font-mono)',
  },
  dot: { width: 5, height: 5, borderRadius: '50%', boxShadow: '0 0 4px currentColor' },
  cardMeta: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px 16px' },
  metaPair: { display: 'flex', flexDirection: 'column', gap: 1 },
  metaLabel: { fontSize: 10, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--text-dim)' },
  metaVal: { fontSize: 12, color: 'var(--text-primary)' },
  idRow: { display: 'flex', alignItems: 'center', gap: 8, borderTop: '1px solid var(--border-dim)', paddingTop: 10 },
  sessionLabel: { fontSize: 10, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.06em' },
  sessionId: { fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-dim)' },
  empty: { display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', flex: 1, gap: 8, minHeight: 200 },
  emptyText: { fontSize: 13, color: 'var(--text-secondary)' },
  emptyHint: { fontSize: 12, color: 'var(--text-dim)' },
}
