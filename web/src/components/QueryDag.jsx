import { useMemo, useState, useCallback } from 'react'
import { Droplet, Zap, ArrowUp } from 'lucide-react'

// Snowflake-style query profile: a compact operator tree (result at top,
// data sources fanning out below — join inputs render side-by-side, not
// stacked). Cards show name + % bar + time + rows; every column treatment
// lives in the sidebar on selection. WholeStageCodegen wrappers (which Spark
// reports as edgeless nodes) are placed as slim stage chips using the id-gap
// rule: a chip sits between the real nodes it wraps (Beacon #19).

export function QueryDag({ profile }) {
  const model = useMemo(() => profile ? buildModel(profile) : null, [profile])
  const [selected, setSelected] = useState(null)

  const select = useCallback(id => setSelected(prev => (prev === id ? null : id)), [])

  if (!model || model.rootId == null) return null
  const { totalRows, totalShuffleBytes, hasSpill, ranked, peakParallelism } = model
  const selRow = selected != null ? model.byId.get(selected) : null

  return (
    <div style={s.root}>
      <div style={s.treeCol}>
        <div style={s.colHead}>EXECUTION TREE</div>
        <div style={s.tree}>
          <Branch id={model.rootId} model={model} selected={selected} onSelect={select} />
        </div>
      </div>

      <aside style={s.side}>
        <div style={s.colHead}>PROFILE</div>
        <div style={s.statGrid}>
          <Stat label="Duration" value={fmtMs(profile.duration_ms)} accent />
          <Stat label="Rows" value={totalRows != null ? fmtInt(totalRows) : '—'} />
          <Stat label="Shuffled" value={totalShuffleBytes || '—'} />
          <Stat label="Spill" value={hasSpill ? 'yes' : 'none'} danger={hasSpill} />
          <Stat label="Peak parallel" value={`×${peakParallelism}`} />
        </div>

        {selRow && <SelectedNode row={selRow} />}

        <div style={s.sideHead}>Most expensive nodes</div>
        <div style={s.rankList}>
          {ranked.length === 0 && <div style={s.noData}>No per-operator timings reported.</div>}
          {ranked.map(r => (
            <button
              key={r.node.id}
              style={{ ...s.rankRow, ...(selected === r.node.id ? s.rankRowActive : {}) }}
              onClick={() => select(r.node.id)}
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

// ---- tree rendering ----

function Branch({ id, model, selected, onSelect }) {
  const node = model.byId.get(id)
  if (!node) return null
  if (node.isWsg) return <StageChip node={node.node} pct={node.pct} />

  const kids = model.children.get(id) || []
  const isRoot = id === model.rootId
  const card = row => <OpCard row={row} selected={selected === id} onSelect={onSelect} isRoot={isRoot} />
  if (kids.length === 0) return card(node)

  if (kids.length === 1) {
    return (
      <div style={s.col}>
        {card(node)}
        <Connector />
        {model.stageChips.get(kids[0])?.map(c => <StageChip key={c.node.id} node={c.node} pct={c.pct} />)}
        <Branch id={kids[0]} model={model} selected={selected} onSelect={onSelect} />
      </div>
    )
  }

  // fan-out: multiple inputs (a join) render side-by-side below the parent
  return (
    <div style={s.col}>
      {card(node)}
      <Connector />
      <div style={s.fanBar} />
      <div style={s.fanRow}>
        {kids.map(k => (
          <div key={k} style={s.fanCol}>
            {model.stageChips.get(k)?.map(c => <StageChip key={c.node.id} node={c.node} pct={c.pct} />)}
            <Branch id={k} model={model} selected={selected} onSelect={onSelect} />
          </div>
        ))}
      </div>
    </div>
  )
}

function OpCard({ row, selected, onSelect, isRoot }) {
  const { node, pct } = row
  const rowCount = node.metrics?.['number of output rows']
  const perTask = node.median_task_ms
  const tasks = node.task_count
  const location = scanLocation(node)
  const condition = filterCondition(node)
  const join = row.join
  return (
    <button style={{ ...s.card, ...(isRoot ? s.cardRoot : {}), ...(selected ? s.cardSel : {}) }} onClick={() => onSelect(node.id)}>
      <div style={s.cardTop}>
        <span style={s.opName}>{node.name}</span>
        <span style={s.badges}>
          {node.has_spill && <Droplet size={11} style={{ color: 'var(--red)' }} />}
          {node.has_skew && <Zap size={11} style={{ color: 'var(--red)' }} />}
        </span>
      </div>
      {location && (
        <div style={s.locLine} title={location.full}>
          <span style={s.locTable}>{location.table}</span>
          <span style={s.locPath}>{location.path}</span>
        </div>
      )}
      {condition && (
        <div style={s.locLine} title={condition}>
          <span style={s.condOp}>WHERE</span>
          <span style={s.locPath}>{condition}</span>
        </div>
      )}
      {join && (
        <div style={s.locLine} title={join.on}>
          <span style={s.condOp}>{join.type}</span>
          <span style={s.locPath}>{join.on}</span>
        </div>
      )}
      {pct != null ? (
        <div style={s.barTrack}>
          <span style={{ ...s.barFill, width: `${Math.max(pct, 1.5)}%`, background: heat(pct) }} />
        </div>
      ) : null}
      <div style={s.cardMeta}>
        {pct != null ? (
          <span style={{ color: heat(pct), fontWeight: 600 }}>{pct.toFixed(1)}%</span>
        ) : (
          <span />
        )}
        <span style={s.metaDim}>{fmtMs(node.duration_ms)}</span>
      </div>
      <div style={s.rowLine}>
        {rowCount ? <span>{rowCount} rows</span> : <span>{row.primaryMetric || ''}</span>}
        {tasks ? <span style={s.concurrency}>×{tasks}</span> : null}
        {perTask && tasks ? <span style={s.metaDim}>~{fmtMs(perTask)}/task</span> : null}
      </div>
    </button>
  )
}

function StageChip({ node, pct }) {
  return (
    <div style={s.chip}>
      <span style={s.chipName}>{node.name}</span>
      {pct != null && (
        <span style={s.chipBarTrack}>
          <span style={{ ...s.chipBarFill, width: `${Math.max(pct, 1.5)}%`, background: heat(pct) }} />
        </span>
      )}
      <span style={s.chipMeta}>
        {fmtMs(node.duration_ms)}
        {node.task_count ? ` ×${node.task_count}` : ''}
      </span>
    </div>
  )
}

// Sidebar panel for the selected node: full operator name, every column
// treatment and metric value — untruncated (cards stay compact, this is the
// "read it all" view).
function SelectedNode({ row }) {
  const { node, pct } = row
  const entries = Object.entries(node.metrics).filter(([, v]) => v && v !== '0' && v !== '0.0 B')
  return (
    <div style={s.sel}>
      <div style={s.sideHead}>Selected node</div>
      <div style={s.selCard}>
        <div style={s.selTop}>
          <span style={s.selName}>{node.name}</span>
          <span style={s.selPct}>{pct != null ? `${pct.toFixed(1)}%` : ''}</span>
        </div>
        {pct != null && (
          <div style={s.selMeta}>{fmtMs(node.duration_ms)}</div>
        )}

        {node.treatments?.length > 0 && (
          <div style={s.treat}>
            {node.treatments.map((tr, i) => (
              <div key={i} style={i > 0 ? s.treatGroup : undefined}>
                {node.treatments.length > 1 && (
                  <div style={s.treatOp}>{tr.operator}</div>
                )}
                {tr.entries.map(([k, v], j) => (
                  <div key={j} style={s.treatRow}>
                    <span style={s.treatK}>{k}</span>
                    <span style={s.selTreatV}>{v}</span>
                  </div>
                ))}
              </div>
            ))}
          </div>
        )}

        {entries.length > 0 && (
          <div style={s.detail}>
            {entries.slice(0, 12).map(([k, v]) => (
              <div key={k} style={s.detailRow}>
                <span style={s.detailK}>{k}</span>
                <span style={s.detailV}>{v}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function Connector() {
  return (
    <div style={s.connector}>
      <ArrowUp size={13} style={{ color: 'var(--text-dim)' }} />
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

  // edges point from child (toward data source) to parent (toward result):
  // parent receives data FROM child. Root is the node that is never a child.
  const children = new Map()
  const isChild = new Set()
  for (const e of profile.edges) {
    if (!children.has(e.to)) children.set(e.to, [])
    children.get(e.to).push(e.from)
    isChild.add(e.from)
  }
  for (const kids of children.values()) kids.sort((a, b) => b - a)

  const rootId = nodes.find(n => /^AdaptiveSparkPlan/.test(n.name))?.id
    ?? nodes.find(n => !isChild.has(n.id) && !isWsg(n))?.id
    ?? 0

  const isWsg = n => /^WholeStageCodegen/.test(n.name)

  // WholeStageCodegen nodes carry no edges; Spark numbers them between the
  // real nodes they wrap, so a chip belongs in the gap (parentId < wsg < childId).
  const stageChips = new Map()
  for (const e of profile.edges) {
    const chips = nodes.filter(
      n => isWsg(n) && n.id > e.to && n.id < e.from
    )
    if (chips.length) stageChips.set(e.from, chips.map(n => ({ node: n, pct: pctOf(n, nodes) })))
  }

  const byId = new Map()
  const totalMs = nodes.reduce((a, n) => a + (n.duration_ms || 0), 0)

  // Which table does each scan node read? Used to qualify join keys.
  const tableByScan = new Map()
  for (const n of nodes) {
    const loc = scanLocation(n)
    if (loc) tableByScan.set(n.id, loc.table)
  }
  const tableUnder = id => {
    const stack = [id]
    while (stack.length) {
      const cur = stack.pop()
      if (tableByScan.has(cur)) return tableByScan.get(cur)
      for (const k of children.get(cur) || []) stack.push(k)
    }
    return null
  }
  const hasBroadcastUnder = id => {
    const stack = [id]
    while (stack.length) {
      const cur = stack.pop()
      if (/^Broadcast/.test(byId.get(cur)?.node?.name || '')) return true
      for (const k of children.get(cur) || []) stack.push(k)
    }
    return false
  }

  // Joins report left/right keys without table names; Spark's plan doesn't say
  // which side is which, but the broadcast (build) side is always the right
  // input — so qualify: orders.customer_id = customers.customer_id.
  const joinDetail = new Map()
  for (const n of nodes) {
    if (!/Join/.test(n.name)) continue
    const kids = children.get(n.id) || []
    if (kids.length < 2) continue
    const entries = n.treatments?.flatMap(t => t.entries) ?? []
    const entry = k => entries.find(([key]) => key.startsWith(k))?.[1]
    const leftKey = entry('Left keys')?.replace(/^\[|\]$/g, '')
    const rightKey = entry('Right keys')?.replace(/^\[|\]$/g, '')
    const type = entry('Join type')?.toUpperCase()
    if (!leftKey || !rightKey) continue
    let leftId = kids[0]
    let rightId = kids[1]
    if (!hasBroadcastUnder(rightId) && hasBroadcastUnder(leftId)) {
      ;[leftId, rightId] = [rightId, leftId]
    }
    const leftT = tableUnder(leftId)
    const rightT = tableUnder(rightId)
    if (!leftT || !rightT) continue
    joinDetail.set(n.id, {
      type: type || 'JOIN',
      on: `${leftT}.${leftKey} = ${rightT}.${rightKey}`,
    })
  }

  for (const n of nodes) {
    byId.set(n.id, {
      node: n,
      isWsg: isWsg(n),
      pct: n.duration_ms != null && totalMs > 0 ? (n.duration_ms / totalMs) * 100 : null,
      primaryMetric: primaryMetric(n),
      join: joinDetail.get(n.id),
    })
  }

  const ranked = nodes
    .filter(n => n.duration_ms != null)
    .map(n => ({ node: n, pct: pctOf(n, nodes) }))
    .sort((a, b) => b.pct - a.pct)
    .slice(0, 6)

  const totalRows = leafRows(nodes)
  const totalShuffleBytes = maxMetric(nodes, 'shuffle bytes written')
  const hasSpill = nodes.some(n => n.has_spill)
  const peakParallelism = nodes.reduce((max, n) => Math.max(max, n.task_count || 1), 1)

  return { rootId, byId, children, stageChips, totalMs, totalRows, totalShuffleBytes, hasSpill, ranked, peakParallelism }
}

function pctOf(n, nodes) {
  const total = nodes.reduce((a, x) => a + (x.duration_ms || 0), 0)
  return n.duration_ms != null && total > 0 ? (n.duration_ms / total) * 100 : null
}

function primaryMetric(n) {
  if (n.summary_metric && !n.summary_metric.endsWith(' rows')) return n.summary_metric
  const m = n.metrics || {}
  if (n.is_shuffle && m['shuffle bytes written']) return `${m['shuffle bytes written']} shuffled`
  if (m['data size']) return m['data size']
  if (m['number of partitions']) return `${m['number of partitions']} partitions`
  return null
}

// Filters carry their predicate in the plan text ("Condition: isnotnull(...)");
// trivial detail, so it belongs on the card itself, not hidden in the sidebar.
function filterCondition(n) {
  if (n.name !== 'Filter') return null
  const c = n.treatments
    ?.flatMap(t => t.entries)
    .find(([k]) => k === 'Condition')
  return c ? c[1] : null
}

// Spark reports the physical path in the plan text ("Location: InMemoryFileIndex
// [file:/tmp/spark-data/orders]"); surface it on the card so scans say *what*
// they read, Snowflake-style (table name + path).
function scanLocation(n) {
  if (!/^Scan /.test(n.name)) return null
  const loc = n.treatments
    ?.flatMap(t => t.entries)
    .find(([k]) => k === 'Location')
  if (!loc) return null
  const m = loc[1].match(/\[([^\]]+)\]/)
  if (!m) return null
  const full = m[1].replace(/^file:/, '')
  const parts = full.split('/').filter(Boolean)
  return { table: parts[parts.length - 1] || full, path: full, full: m[1] }
}

function leafRows(nodes) {
  for (const n of nodes) {
    const v = n.metrics?.['number of output rows']
    if (v) return parseInt(v.replace(/,/g, ''), 10)
  }
  return null
}

function maxMetric(nodes, key) {
  let best = null
  for (const n of nodes) if (n.metrics?.[key]) best = n.metrics[key]
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
const COL_W = 290

const s = {
  root: { display: 'flex', gap: 0, height: '100%', overflow: 'hidden', background: 'var(--bg-base)' },
  treeCol: { flex: 1, overflow: 'auto', padding: '16px 0 32px' },
  colHead: {
    fontSize: 10, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--text-dim)',
    fontWeight: 600, padding: '0 20px 10px',
  },
  tree: { display: 'flex', flexDirection: 'column', alignItems: 'center', minWidth: 'fit-content', padding: '0 20px' },

  col: { display: 'flex', flexDirection: 'column', alignItems: 'center' },
  fanRow: { display: 'flex', gap: 28, alignItems: 'flex-start' },
  fanCol: { display: 'flex', flexDirection: 'column', alignItems: 'center' },
  fanBar: { width: '100%', height: 2, background: 'var(--border)', margin: '0 4px', minWidth: COL_W * 2 + 28 },

  card: {
    width: COL_W, textAlign: 'left', display: 'block', cursor: 'pointer',
    background: 'var(--bg-surface)', border: '1px solid var(--border)', borderRadius: 8,
    padding: '8px 11px', fontFamily: 'var(--font-ui)',
    transition: 'border-color 0.12s, background 0.12s',
  },
  cardRoot: {
    background: 'transparent', border: '1px dashed var(--border)',
    color: 'var(--text-dim)',
  },
  cardSel: { borderColor: 'var(--amber)', background: 'var(--bg-raised)' },
  cardTop: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 },
  opName: { fontSize: 12, fontWeight: 600, color: 'var(--text-primary)' },
  locLine: {
    display: 'flex', alignItems: 'baseline', gap: 6, marginBottom: 5,
    fontFamily: 'var(--font-mono)', fontSize: 9.5,
  },
  locTable: { color: 'var(--amber)', fontWeight: 600, whiteSpace: 'nowrap' },
  locPath: { color: 'var(--text-dim)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' },
  condOp: { color: 'var(--red)', fontWeight: 600, whiteSpace: 'nowrap' },
  badges: { display: 'flex', gap: 4, alignItems: 'center' },
  barTrack: { height: 5, borderRadius: 3, background: 'var(--bg-base)', overflow: 'hidden', marginBottom: 5 },
  barFill: { display: 'block', height: '100%', borderRadius: 3, transition: 'width 0.3s' },
  cardMeta: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontFamily: 'var(--font-mono)', fontSize: 10.5 },
  concurrency: { color: 'var(--amber)', fontWeight: 500 },
  rowLine: {
    display: 'flex', alignItems: 'center', gap: 8, marginTop: 4, paddingTop: 3,
    borderTop: '1px solid var(--border-dim)', fontSize: 9.5, color: 'var(--text-dim)',
    fontFamily: 'var(--font-mono)',
  },

  chip: {
    display: 'flex', alignItems: 'center', gap: 8, width: COL_W, boxSizing: 'border-box',
    padding: '3px 10px', margin: '2px 0',
    border: '1px dashed var(--amber-border)', borderRadius: 999,
    background: 'var(--amber-bg)', fontFamily: 'var(--font-mono)',
  },
  chipName: { fontSize: 9.5, color: 'var(--amber)', fontWeight: 600, whiteSpace: 'nowrap' },
  chipBarTrack: { flex: 1, height: 3, borderRadius: 2, background: 'var(--bg-base)', overflow: 'hidden' },
  chipBarFill: { display: 'block', height: '100%', borderRadius: 2 },
  chipMeta: { fontSize: 9, color: 'var(--text-dim)', whiteSpace: 'nowrap' },

  treat: { marginTop: 6, paddingTop: 5, borderTop: '1px solid var(--border-dim)', display: 'flex', flexDirection: 'column', gap: 3 },
  treatGroup: { marginTop: 4, paddingTop: 3, borderTop: '1px dashed var(--border-dim)' },
  treatOp: { fontSize: 9, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--amber)', fontWeight: 600, marginBottom: 2 },
  treatRow: { display: 'flex', justifyContent: 'space-between', gap: 10, fontFamily: 'var(--font-mono)', fontSize: 10, lineHeight: 1.4 },
  treatK: { color: 'var(--text-dim)', flexShrink: 0 },
  treatV: { color: 'var(--text-mono)', textAlign: 'right', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' },
  metaDim: { color: 'var(--text-dim)' },

  detail: {
    marginTop: 10, paddingTop: 10, borderTop: '1px solid var(--border-dim)',
    display: 'flex', flexDirection: 'column', gap: 3,
  },
  detailRow: { display: 'flex', justifyContent: 'space-between', gap: 12, fontFamily: 'var(--font-mono)', fontSize: 10 },
  detailK: { color: 'var(--text-dim)' },
  detailV: { color: 'var(--text-mono)', textAlign: 'right' },

  connector: { display: 'flex', justifyContent: 'center', height: 18, alignItems: 'center' },

  side: {
    width: 280, flexShrink: 0, borderLeft: '1px solid var(--border-dim)',
    background: 'var(--bg-surface)', padding: '16px 0', overflow: 'auto',
  },
  statGrid: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 1, background: 'var(--border-dim)', margin: '0 16px 16px', borderRadius: 8, overflow: 'hidden' },
  stat: { background: 'var(--bg-base)', padding: '10px 12px' },
  statLabel: { fontSize: 9.5, letterSpacing: '0.05em', textTransform: 'uppercase', color: 'var(--text-dim)', marginBottom: 4 },
  statValue: { fontSize: 14, fontWeight: 600, fontFamily: 'var(--font-mono)', color: 'var(--text-primary)' },

  sideHead: { fontSize: 10, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--text-dim)', fontWeight: 600, padding: '4px 16px 8px' },
  sel: { padding: '0 16px 16px', borderBottom: '1px solid var(--border-dim)', marginBottom: 14 },
  selCard: { background: 'var(--bg-base)', border: '1px solid var(--amber)', borderRadius: 8, padding: '10px 12px' },
  selTop: { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8, marginBottom: 4 },
  selName: { fontSize: 12, fontWeight: 600, color: 'var(--text-primary)', wordBreak: 'break-word', lineHeight: 1.35 },
  selPct: { fontSize: 10.5, fontFamily: 'var(--font-mono)', color: 'var(--amber)', flexShrink: 0 },
  selMeta: { fontSize: 10.5, fontFamily: 'var(--font-mono)', color: 'var(--text-dim)', marginBottom: 4 },
  selTreatV: { color: 'var(--text-mono)', textAlign: 'right', whiteSpace: 'normal', wordBreak: 'break-word', lineHeight: 1.4 },
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
