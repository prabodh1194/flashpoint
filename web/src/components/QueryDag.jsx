import { useMemo, useState } from 'react'
import { Droplet, Zap, ArrowDown, Repeat } from 'lucide-react'

// Snowflake-style query profile: a clean vertical operator tree (execution order,
// top = data source, bottom = final result) where each node carries an inline
// "% of execution time" bar — the bottleneck glows. A side panel ranks the most
// expensive operators. We only ever show REAL Spark-reported durations; operators
// Spark doesn't time (Exchange, Range, ...) show their true metric instead of a
// fabricated bar (Beacon #19).

export function QueryDag({ profile }) {
  const model = useMemo(() => profile ? buildModel(profile) : null, [profile])
  const [selected, setSelected] = useState(null)

  if (!model || !model.spine.length) return null
  const { spine, totalMs, totalRows, totalShuffleBytes, hasSpill, ranked } = model

  return (
    <div style={s.root}>
      <div style={s.treeCol}>
        <div style={s.colHead}>EXECUTION TREE</div>
        <div style={s.tree}>
          {spine.map((row, i) => (
            <div key={row.node.id}>
              {row.shuffleBefore && <ShuffleBoundary />}
              {i > 0 && !row.shuffleBefore && <Connector />}
              <OpCard
                row={row}
                selected={selected === row.node.id}
                onSelect={() => setSelected(selected === row.node.id ? null : row.node.id)}
              />
            </div>
          ))}
        </div>
      </div>

      <aside style={s.side}>
        <div style={s.colHead}>PROFILE</div>
        <div style={s.statGrid}>
          <Stat label="Total time" value={fmtMs(totalMs)} accent />
          <Stat label="Rows" value={totalRows != null ? fmtInt(totalRows) : '—'} />
          <Stat label="Shuffled" value={totalShuffleBytes || '—'} />
          <Stat label="Spill" value={hasSpill ? 'yes' : 'none'} danger={hasSpill} />
        </div>

        <div style={s.sideHead}>Most expensive nodes</div>
        <div style={s.rankList}>
          {ranked.length === 0 && <div style={s.noData}>No per-operator timings reported.</div>}
          {ranked.map(r => (
            <button
              key={r.node.id}
              style={{ ...s.rankRow, ...(selected === r.node.id ? s.rankRowActive : {}) }}
              onClick={() => setSelected(selected === r.node.id ? null : r.node.id)}
            >
              <span style={s.rankName}>{r.node.name}</span>
              <span style={s.rankBarTrack}>
                <span style={{ ...s.rankBarFill, width: `${r.pct}%`, background: heat(r.pct) }} />
              </span>
              <span style={s.rankPct}>{r.pct.toFixed(1)}%</span>
            </button>
          ))}
        </div>
      </aside>
    </div>
  )
}

function OpCard({ row, selected, onSelect }) {
  const { node, pct, primaryMetric } = row
  return (
    <button style={{ ...s.card, ...(selected ? s.cardSel : {}) }} onClick={onSelect}>
      <div style={s.cardTop}>
        <span style={s.opName}>{node.name}</span>
        <span style={s.badges}>
          {node.has_spill && <Droplet size={11} style={{ color: 'var(--red)' }} />}
          {node.has_skew && <Zap size={11} style={{ color: 'var(--red)' }} />}
        </span>
      </div>

      {pct != null ? (
        <>
          <div style={s.barTrack}>
            <span style={{ ...s.barFill, width: `${Math.max(pct, 1.5)}%`, background: heat(pct) }} />
          </div>
          <div style={s.cardMeta}>
            <span style={{ color: heat(pct), fontWeight: 600 }}>{pct.toFixed(1)}%</span>
            <span style={s.metaDim}>{fmtMs(node.duration_ms)}</span>
          </div>
        </>
      ) : (
        <div style={s.cardMeta}>
          <span style={s.metaDim}>{primaryMetric || 'no timing reported'}</span>
        </div>
      )}

      {selected && <NodeDetail node={node} />}
    </button>
  )
}

function NodeDetail({ node }) {
  const entries = Object.entries(node.metrics).filter(([, v]) => v && v !== '0' && v !== '0.0 B')
  return (
    <div style={s.detail}>
      {entries.slice(0, 12).map(([k, v]) => (
        <div key={k} style={s.detailRow}>
          <span style={s.detailK}>{k}</span>
          <span style={s.detailV}>{v}</span>
        </div>
      ))}
    </div>
  )
}

function ShuffleBoundary() {
  return (
    <div style={s.shuffle}>
      <span style={s.shuffleLine} />
      <span style={s.shuffleTag}><Repeat size={10} /> shuffle</span>
      <span style={s.shuffleLine} />
    </div>
  )
}

function Connector() {
  return (
    <div style={s.connector}>
      <ArrowDown size={13} style={{ color: 'var(--text-dim)' }} />
    </div>
  )
}

function Stat({ label, value, accent, danger }) {
  return (
    <div style={s.stat}>
      <div style={s.statLabel}>{label}</div>
      <div style={{ ...s.statValue, ...(accent ? { color: 'var(--amber)' } : {}), ...(danger ? { color: 'var(--red)' } : {}) }}>
        {value}
      </div>
    </div>
  )
}

// ---- model ----

function buildModel(profile) {
  const nodes = profile.nodes
  // Spark lists SQL plan nodes in reverse-topological order: the data source
  // (highest nodeId, e.g. Range) first, the final operator (AdaptiveSparkPlan,
  // id 0) last. Some wrapper nodes (WholeStageCodegen, AQEShuffleRead) carry no
  // edges, so an edge-walk would drop them. The node array order IS the
  // execution order once we sort by descending id — use it directly for the spine.
  const exec = [...nodes].sort((a, b) => b.id - a.id)

  const totalMs = exec.reduce((a, n) => a + (n.duration_ms || 0), 0)

  const spine = exec.map(n => ({
    node: n,
    pct: n.duration_ms != null && totalMs > 0 ? (n.duration_ms / totalMs) * 100 : null,
    primaryMetric: primaryMetric(n),
    shuffleBefore: n.is_shuffle,
  }))

  const ranked = spine
    .filter(r => r.pct != null)
    .sort((a, b) => b.pct - a.pct)
    .slice(0, 6)

  const totalRows = leafRows(exec)
  const totalShuffleBytes = maxMetric(exec, 'shuffle bytes written')
  const hasSpill = exec.some(n => n.has_spill)

  return { spine, totalMs, totalRows, totalShuffleBytes, hasSpill, ranked }
}

function primaryMetric(n) {
  const m = n.metrics || {}
  if (n.is_shuffle && m['shuffle bytes written']) return `${m['shuffle bytes written']} shuffled`
  if (m['number of output rows']) return `${m['number of output rows']} rows`
  if (m['data size']) return m['data size']
  if (m['number of partitions']) return `${m['number of partitions']} partitions`
  return null
}

function leafRows(exec) {
  for (const n of exec) {
    const v = n.metrics?.['number of output rows']
    if (v) return parseInt(v.replace(/,/g, ''), 10)
  }
  return null
}

function maxMetric(exec, key) {
  let best = null
  for (const n of exec) if (n.metrics?.[key]) best = n.metrics[key]
  return best
}

// cool → amber → red by percentage of total time
function heat(pct) {
  if (pct == null) return 'var(--border)'
  const t = Math.min(1, pct / 60)  // 60%+ is fully hot
  if (t < 0.5) return mix([90, 96, 112], [245, 158, 11], t / 0.5)
  return mix([245, 158, 11], [239, 68, 68], (t - 0.5) / 0.5)
}
function mix(a, b, t) {
  const c = i => Math.round(a[i] + (b[i] - a[i]) * t)
  return `rgb(${c(0)},${c(1)},${c(2)})`
}

function fmtMs(ms) {
  if (ms == null) return '—'
  if (ms < 1000) return `${ms} ms`
  return `${(ms / 1000).toFixed(2)} s`
}
function fmtInt(n) { return n.toLocaleString() }

// ---- styles ----
const COL_W = 300

const s = {
  root: { display: 'flex', gap: 0, height: '100%', overflow: 'hidden', background: 'var(--bg-base)' },
  treeCol: { flex: 1, overflow: 'auto', padding: '16px 0 32px' },
  colHead: {
    fontSize: 10, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--text-dim)',
    fontWeight: 600, padding: '0 20px 10px',
  },
  tree: { display: 'flex', flexDirection: 'column', alignItems: 'center' },

  card: {
    width: COL_W, textAlign: 'left', display: 'block', cursor: 'pointer',
    background: 'var(--bg-surface)', border: '1px solid var(--border)', borderRadius: 8,
    padding: '10px 12px', fontFamily: 'var(--font-ui)',
    transition: 'border-color 0.12s, background 0.12s',
  },
  cardSel: { borderColor: 'var(--amber)', background: 'var(--bg-raised)' },
  cardTop: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 },
  opName: { fontSize: 12.5, fontWeight: 600, color: 'var(--text-primary)' },
  badges: { display: 'flex', gap: 4, alignItems: 'center' },
  barTrack: { height: 6, borderRadius: 3, background: 'var(--bg-base)', overflow: 'hidden', marginBottom: 6 },
  barFill: { display: 'block', height: '100%', borderRadius: 3, transition: 'width 0.3s' },
  cardMeta: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontFamily: 'var(--font-mono)', fontSize: 10.5 },
  metaDim: { color: 'var(--text-dim)' },

  detail: {
    marginTop: 10, paddingTop: 10, borderTop: '1px solid var(--border-dim)',
    display: 'flex', flexDirection: 'column', gap: 3,
  },
  detailRow: { display: 'flex', justifyContent: 'space-between', gap: 12, fontFamily: 'var(--font-mono)', fontSize: 10 },
  detailK: { color: 'var(--text-dim)' },
  detailV: { color: 'var(--text-mono)', textAlign: 'right' },

  connector: { display: 'flex', justifyContent: 'center', height: 18, alignItems: 'center' },
  shuffle: { display: 'flex', alignItems: 'center', gap: 8, width: COL_W, padding: '6px 0' },
  shuffleLine: { flex: 1, height: 1, background: 'var(--amber)', opacity: 0.4 },
  shuffleTag: {
    display: 'flex', alignItems: 'center', gap: 4, fontSize: 9.5, fontFamily: 'var(--font-mono)',
    color: 'var(--amber)', letterSpacing: '0.04em',
  },

  side: {
    width: 280, flexShrink: 0, borderLeft: '1px solid var(--border-dim)',
    background: 'var(--bg-surface)', padding: '16px 0', overflow: 'auto',
  },
  statGrid: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 1, background: 'var(--border-dim)', margin: '0 16px 16px', borderRadius: 8, overflow: 'hidden' },
  stat: { background: 'var(--bg-base)', padding: '10px 12px' },
  statLabel: { fontSize: 9.5, letterSpacing: '0.05em', textTransform: 'uppercase', color: 'var(--text-dim)', marginBottom: 4 },
  statValue: { fontSize: 14, fontWeight: 600, fontFamily: 'var(--font-mono)', color: 'var(--text-primary)' },

  sideHead: { fontSize: 10, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--text-dim)', fontWeight: 600, padding: '4px 16px 8px' },
  rankList: { display: 'flex', flexDirection: 'column', gap: 2, padding: '0 10px' },
  noData: { fontSize: 11, color: 'var(--text-dim)', padding: '6px 6px', fontStyle: 'italic' },
  rankRow: {
    display: 'flex', alignItems: 'center', gap: 8, padding: '6px 6px', cursor: 'pointer',
    background: 'none', border: 'none', borderRadius: 6, width: '100%', textAlign: 'left',
  },
  rankRowActive: { background: 'var(--bg-raised)' },
  rankName: { fontSize: 11, color: 'var(--text-secondary)', width: 96, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' },
  rankBarTrack: { flex: 1, height: 5, borderRadius: 3, background: 'var(--bg-base)', overflow: 'hidden' },
  rankBarFill: { display: 'block', height: '100%', borderRadius: 3 },
  rankPct: { fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)', width: 40, textAlign: 'right' },
}
