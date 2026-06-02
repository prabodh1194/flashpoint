import { useState, useEffect } from 'react'
import { CheckCircle, XCircle, RotateCcw } from 'lucide-react'
import { fetchHistory } from '../api'

export function History() {
  const [history, setHistory] = useState([])
  const [loading, setLoading] = useState(true)

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
            <tr key={q.query_id} style={i % 2 === 0 ? {} : s.altRow}>
              <td style={s.td}><StatusIcon status={q.status} /></td>
              <td style={{ ...s.td, ...s.sqlCell }}>
                <span style={s.sql}>{q.sql}</span>
              </td>
              <td style={{ ...s.td, ...s.mono }}>{q.duration_ms}ms</td>
              <td style={{ ...s.td, ...s.mono }}>{q.row_count.toLocaleString()}</td>
              <td style={{ ...s.td, ...s.mono, color: 'var(--amber)' }}>dev-xs</td>
              <td style={{ ...s.td, ...s.mono, color: 'var(--text-dim)' }}>{q.ts}</td>
              <td style={s.td}>
                <button style={s.rerunBtn} title="Re-run">
                  <RotateCcw size={11} />
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
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
    padding: 24,
    overflow: 'auto',
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    gap: 12,
    marginBottom: 16,
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
  table: {
    width: '100%',
    borderCollapse: 'collapse',
    fontSize: 12,
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
