import { useState, useEffect } from 'react'
import { ArrowLeft, Clock, Rows, Hash, CheckCircle, XCircle } from 'lucide-react'
import { fetchQueryById } from '../api'
import { QueryDag } from '../components/QueryDag'

export function QueryProfile({ queryId, onBack }) {
  const [query, setQuery] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchQueryById(queryId)
      .then(data => setQuery(data))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [queryId])

  if (loading) return <div style={s.loading}>Loading…</div>
  if (!query) return <div style={s.error}>Query not found.</div>

  const profile = query.profile
  const hasProfile = profile && profile.nodes && profile.nodes.length > 0

  return (
    <div style={s.root}>
      <div style={s.header}>
        <button style={s.backBtn} onClick={onBack}>
          <ArrowLeft size={14} />
          <span>Back to History</span>
        </button>
        <div style={s.meta}>
          <span style={s.qid}>
            <Hash size={11} style={{ color: 'var(--amber)' }} />
            {query.query_id}
          </span>
          {query.status === 'success'
            ? <CheckCircle size={14} style={{ color: 'var(--green)' }} />
            : <XCircle size={14} style={{ color: 'var(--red)' }} />
          }
          <span style={{ ...s.metaItem, color: query.status === 'success' ? 'var(--green)' : 'var(--red)' }}>
            {query.status}
          </span>
          <span style={s.metaItem}><Clock size={11} /> {query.duration_ms}ms</span>
          <span style={s.metaItem}><Rows size={11} /> {query.row_count.toLocaleString()} rows</span>
          <span style={{ ...s.metaItem, color: 'var(--amber)' }}>{query.name}</span>
        </div>
      </div>

      <div style={s.sqlBar}>
        <pre style={s.sqlText}>{query.sql}</pre>
      </div>

      <div style={s.dag}>
        {hasProfile
          ? <QueryDag profile={profile} />
          : <div style={s.noProfile}>No profile data available for this query.</div>
        }
      </div>
    </div>
  )
}

const s = {
  root: {
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
    overflow: 'hidden',
  },
  loading: {
    flex: 1,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    color: 'var(--text-dim)',
    fontSize: 13,
  },
  error: {
    flex: 1,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    color: 'var(--red)',
    fontSize: 13,
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '12px 20px',
    borderBottom: '1px solid var(--border)',
    flexShrink: 0,
    gap: 16,
  },
  backBtn: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
    background: 'none',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius)',
    padding: '6px 12px',
    cursor: 'pointer',
    color: 'var(--text-secondary)',
    fontSize: 12,
    fontFamily: 'inherit',
  },
  meta: {
    display: 'flex',
    alignItems: 'center',
    gap: 12,
  },
  qid: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 5,
    fontFamily: 'var(--font-mono)',
    fontSize: 11.5,
    color: 'var(--text-mono)',
    background: 'var(--amber-bg)',
    border: '1px solid var(--amber-border)',
    borderRadius: 4,
    padding: '2px 8px',
  },
  metaItem: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 4,
    fontFamily: 'var(--font-mono)',
    fontSize: 11.5,
    color: 'var(--text-secondary)',
  },
  sqlBar: {
    padding: '10px 20px',
    borderBottom: '1px solid var(--border-dim)',
    flexShrink: 0,
  },
  sqlText: {
    fontFamily: 'var(--font-mono)',
    fontSize: 12.5,
    color: 'var(--text-mono)',
    background: 'var(--bg-raised)',
    border: '1px solid var(--border-dim)',
    borderRadius: 'var(--radius)',
    padding: '10px 14px',
    margin: 0,
    overflowX: 'auto',
    whiteSpace: 'pre-wrap',
    wordBreak: 'break-word',
    lineHeight: '1.6em',
  },
  dag: {
    flex: 1,
    overflow: 'auto',
    padding: 20,
  },
  noProfile: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    height: '100%',
    color: 'var(--text-dim)',
    fontSize: 13,
  },
}
