import { useState, useEffect } from 'react'
import { CheckCircle, XCircle, RotateCcw, X, Hash, Clock, Rows } from 'lucide-react'
import { fetchHistory } from '../api'

export function History() {
  const [history, setHistory] = useState([])
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState(null)

  useEffect(() => {
    fetchHistory()
      .then(data => setHistory(data.history))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  return (
    <div style={s.root}>
      <div style={s.header}>
        <h2 style={s.title}>Query History</h2>
        <span style={s.count}>{loading ? '…' : `${history.length} queries`}</span>
      </div>

      <div style={s.body}>
        <table style={s.table}>
          <thead>
            <tr>
              {['Status', 'Query', 'Duration', 'Rows', 'Warehouse', 'Time', ''].map(h => (
                <th key={h} style={s.th}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {history.map((q, i) => (
              <tr
                key={q.query_id}
                style={{ ...(i % 2 === 0 ? {} : s.altRow), ...(selected?.query_id === q.query_id ? s.selectedRow : {}), cursor: 'pointer' }}
                onClick={() => setSelected(q)}
              >
                <td style={s.td}><StatusIcon status={q.status} /></td>
                <td style={{ ...s.td, ...s.sqlCell }}>
                  <span style={s.sql}>{q.sql}</span>
                </td>
                <td style={{ ...s.td, ...s.mono }}>{q.duration_ms}ms</td>
                <td style={{ ...s.td, ...s.mono }}>{q.row_count.toLocaleString()}</td>
                <td style={{ ...s.td, ...s.mono, color: 'var(--amber)' }}>dev-xs</td>
                <td style={{ ...s.td, ...s.mono, color: 'var(--text-dim)' }}>{q.ts}</td>
                <td style={s.td}>
                  <button style={s.rerunBtn} title="Re-run" onClick={e => e.stopPropagation()}>
                    <RotateCcw size={11} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {selected && <DetailPanel query={selected} onClose={() => setSelected(null)} />}
      </div>
    </div>
  )
}

function DetailPanel({ query, onClose }) {
  return (
    <div style={p.panel}>
      <div style={p.header}>
        <span style={p.title}>Query Detail</span>
        <button style={p.closeBtn} onClick={onClose}><X size={14} /></button>
      </div>

      <div style={p.section}>
        <div style={p.label}>Query ID</div>
        <div style={p.chip}>
          <Hash size={10} style={{ color: 'var(--amber)' }} />
          <span style={p.chipText}>{query.query_id}</span>
        </div>
      </div>

      <div style={p.section}>
        <div style={p.label}>Status</div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <StatusIcon status={query.status} />
          <span style={{ ...p.chipText, color: query.status === 'success' ? 'var(--green)' : 'var(--red)' }}>
            {query.status}
          </span>
        </div>
      </div>

      <div style={p.section}>
        <div style={p.statRow}>
          <div style={p.stat}>
            <Clock size={11} style={{ color: 'var(--text-dim)' }} />
            <span style={p.chipText}>{query.duration_ms}ms</span>
          </div>
          <div style={p.stat}>
            <Rows size={11} style={{ color: 'var(--text-dim)' }} />
            <span style={p.chipText}>{query.row_count.toLocaleString()} rows</span>
          </div>
          <span style={{ ...p.chipText, color: 'var(--text-dim)' }}>{query.ts}</span>
        </div>
      </div>

      <div style={p.section}>
        <div style={p.label}>SQL</div>
        <pre style={p.sqlBlock}>{query.sql}</pre>
      </div>
    </div>
  )
}

function StatusIcon({ status }) {
  if (status === 'success')
    return <CheckCircle size={14} style={{ color: 'var(--green)' }} />
  return <XCircle size={14} style={{ color: 'var(--red)' }} />
}

const s = {
  root: {
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
    overflow: 'hidden',
    padding: 24,
    paddingBottom: 0,
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    gap: 12,
    marginBottom: 16,
    flexShrink: 0,
  },
  title: {
    fontSize: 15,
    fontWeight: 500,
    color: 'var(--text-primary)',
  },
  count: {
    fontSize: 11,
    fontFamily: 'var(--font-mono)',
    color: 'var(--text-dim)',
    padding: '2px 8px',
    background: 'var(--bg-raised)',
    border: '1px solid var(--border)',
    borderRadius: 100,
  },
  body: {
    flex: 1,
    display: 'flex',
    overflow: 'hidden',
    gap: 0,
  },
  table: {
    flex: 1,
    borderCollapse: 'collapse',
    fontSize: 12,
    display: 'block',
    overflow: 'auto',
    height: '100%',
  },
  th: {
    padding: '8px 12px',
    textAlign: 'left',
    fontSize: 10,
    letterSpacing: '0.06em',
    textTransform: 'uppercase',
    color: 'var(--text-dim)',
    fontWeight: 500,
    borderBottom: '1px solid var(--border)',
    background: 'var(--bg-surface)',
    position: 'sticky',
    top: 0,
  },
  td: {
    padding: '7px 12px',
    borderBottom: '1px solid var(--border-dim)',
    verticalAlign: 'middle',
    color: 'var(--text-secondary)',
  },
  altRow: {
    background: 'rgba(255,255,255,0.012)',
  },
  selectedRow: {
    background: 'rgba(245,158,11,0.06)',
    borderLeft: '2px solid var(--amber)',
  },
  sqlCell: {
    maxWidth: 400,
  },
  sql: {
    fontFamily: 'var(--font-mono)',
    fontSize: 11.5,
    color: 'var(--text-mono)',
    display: 'block',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
    maxWidth: 380,
  },
  mono: {
    fontFamily: 'var(--font-mono)',
    fontSize: 11.5,
  },
  rerunBtn: {
    width: 24,
    height: 24,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    background: 'none',
    border: 'none',
    cursor: 'pointer',
    color: 'var(--text-dim)',
    borderRadius: 'var(--radius-sm)',
  },
}

const p = {
  panel: {
    width: 340,
    flexShrink: 0,
    borderLeft: '1px solid var(--border)',
    background: 'var(--bg-surface)',
    display: 'flex',
    flexDirection: 'column',
    overflow: 'hidden',
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '12px 16px',
    borderBottom: '1px solid var(--border-dim)',
    flexShrink: 0,
  },
  title: {
    fontSize: 12,
    fontWeight: 500,
    color: 'var(--text-primary)',
    letterSpacing: '0.02em',
  },
  closeBtn: {
    background: 'none',
    border: 'none',
    cursor: 'pointer',
    color: 'var(--text-dim)',
    display: 'flex',
    alignItems: 'center',
    padding: 2,
    borderRadius: 'var(--radius-sm)',
  },
  section: {
    padding: '12px 16px',
    borderBottom: '1px solid var(--border-dim)',
  },
  label: {
    fontSize: 10,
    letterSpacing: '0.06em',
    textTransform: 'uppercase',
    color: 'var(--text-dim)',
    marginBottom: 6,
  },
  chip: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 5,
    background: 'var(--amber-bg)',
    border: '1px solid var(--amber-border)',
    borderRadius: 4,
    padding: '3px 8px',
  },
  chipText: {
    fontFamily: 'var(--font-mono)',
    fontSize: 11.5,
    color: 'var(--text-mono)',
  },
  statRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 12,
  },
  stat: {
    display: 'flex',
    alignItems: 'center',
    gap: 4,
  },
  sqlBlock: {
    fontFamily: 'var(--font-mono)',
    fontSize: 11.5,
    color: 'var(--text-mono)',
    background: 'var(--bg-base)',
    border: '1px solid var(--border-dim)',
    borderRadius: 'var(--radius)',
    padding: '10px 12px',
    margin: 0,
    overflowX: 'auto',
    whiteSpace: 'pre-wrap',
    wordBreak: 'break-word',
    lineHeight: '1.6em',
  },
}
