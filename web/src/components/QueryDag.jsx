import { useMemo, useState } from 'react'
import { Droplet, Zap } from 'lucide-react'

// Hand-rolled layered (Sugiyama-style) DAG of a Spark SQL execution plan.
// Layout is computed in JS from the edge list — no graph library (Beacon #19).

const NODE_W = 150
const NODE_H = 46
const COL_GAP = 40   // horizontal gap between sibling nodes
const ROW_GAP = 54   // vertical gap between layers
const PAD = 28

export function QueryDag({ profile }) {
  const [hover, setHover] = useState(null)  // { node, x, y }

  const layout = useMemo(() => profile ? computeLayout(profile) : null, [profile])

  if (!profile || !profile.nodes?.length) return null

  const { positioned, edges, width, height, maxDuration } = layout

  return (
    <div style={s.wrap}>
      <div style={s.header}>
        <span style={s.title}>Query Profile</span>
        <Legend />
      </div>

      <div style={s.canvas}>
        <svg width={width} height={height} style={{ display: 'block' }}>
          {/* edges first, under nodes */}
          {edges.map((e, i) => (
            <path
              key={i}
              d={edgePath(e.fromPos, e.toPos)}
              fill="none"
              stroke={e.is_shuffle ? 'var(--amber)' : 'var(--border)'}
              strokeWidth={e.is_shuffle ? 2.5 : 1.25}
              opacity={e.is_shuffle ? 0.85 : 0.55}
            />
          ))}

          {positioned.map(p => (
            <NodeBox
              key={p.node.id}
              p={p}
              maxDuration={maxDuration}
              onEnter={() => setHover({ node: p.node, x: p.x + NODE_W / 2, y: p.y })}
              onLeave={() => setHover(null)}
            />
          ))}
        </svg>

        {hover && <Tooltip node={hover.node} x={hover.x} y={hover.y} />}
      </div>
    </div>
  )
}

function NodeBox({ p, maxDuration, onEnter, onLeave }) {
  const { node, x, y } = p
  const fill = heatColor(node.duration_ms, maxDuration)
  return (
    <g transform={`translate(${x},${y})`} onMouseEnter={onEnter} onMouseLeave={onLeave} style={{ cursor: 'pointer' }}>
      <rect
        width={NODE_W} height={NODE_H} rx={6}
        fill={fill}
        stroke={node.is_shuffle ? 'var(--amber)' : 'var(--border)'}
        strokeWidth={node.is_shuffle ? 1.5 : 1}
      />
      <text x={10} y={19} style={s.nodeName}>{shorten(node.name)}</text>
      <text x={10} y={35} style={s.nodeMeta}>
        {node.duration_ms != null ? `${node.duration_ms} ms` : (node.metrics['number of output rows'] ? `${node.metrics['number of output rows']} rows` : '')}
      </text>
      {node.has_spill && <Badge x={NODE_W - 18} icon="spill" />}
      {node.has_skew && <Badge x={NODE_W - 34} icon="skew" />}
    </g>
  )
}

function Badge({ x, icon }) {
  return (
    <g transform={`translate(${x},6)`}>
      <circle cx={6} cy={6} r={8} fill="var(--bg-base)" stroke="var(--red)" strokeWidth={1} />
      <foreignObject x={-1} y={-1} width={14} height={14}>
        {icon === 'spill'
          ? <Droplet size={10} style={{ color: 'var(--red)' }} />
          : <Zap size={10} style={{ color: 'var(--red)' }} />}
      </foreignObject>
    </g>
  )
}

function Tooltip({ node, x, y }) {
  return (
    <div style={{ ...tt.box, left: x, top: y - 8 }}>
      <div style={tt.name}>{node.name}</div>
      {node.duration_ms != null && <div style={tt.row}><span style={tt.k}>duration</span><span style={tt.v}>{node.duration_ms} ms</span></div>}
      {Object.entries(node.metrics).slice(0, 10).map(([k, v]) => (
        <div key={k} style={tt.row}><span style={tt.k}>{k}</span><span style={tt.v}>{v}</span></div>
      ))}
    </div>
  )
}

function Legend() {
  return (
    <div style={s.legend}>
      <span style={s.legendItem}><span style={{ ...s.swatch, background: 'var(--amber)' }} />shuffle</span>
      <span style={s.legendItem}><Droplet size={10} style={{ color: 'var(--red)' }} />spill</span>
      <span style={s.legendItem}><span style={{ ...s.swatch, background: heatColor(100, 100) }} />slow</span>
    </div>
  )
}

// ---- layout ----

function computeLayout(profile) {
  const nodes = profile.nodes
  const byId = new Map(nodes.map(n => [n.id, n]))
  const parents = new Map(nodes.map(n => [n.id, []]))   // id -> [parent ids]
  const children = new Map(nodes.map(n => [n.id, []]))  // id -> [child ids]

  // Spark edges run child(fromId) -> parent(toId). We draw top-down with the
  // root operator (AdaptiveSparkPlan) at the top, so "layer 0" = the final node.
  for (const e of profile.edges) {
    if (!byId.has(e.from) || !byId.has(e.to)) continue
    children.get(e.to).push(e.from)   // parent .to has child .from
    parents.get(e.from).push(e.to)
  }

  // Layer = longest path from a root (node with no parent), going downward.
  const layer = new Map()
  const roots = nodes.filter(n => parents.get(n.id).length === 0).map(n => n.id)
  const assign = (id, depth, seen) => {
    if (seen.has(id)) return
    seen.add(id)
    layer.set(id, Math.max(layer.get(id) ?? 0, depth))
    for (const c of children.get(id)) assign(c, depth + 1, seen)
    seen.delete(id)
  }
  for (const r of roots) assign(r, 0, new Set())
  // any unreached node (cycle guard) -> layer 0
  for (const n of nodes) if (!layer.has(n.id)) layer.set(n.id, 0)

  // group by layer, order within layer by barycenter of parents' slots
  const layers = new Map()
  for (const n of nodes) {
    const l = layer.get(n.id)
    if (!layers.has(l)) layers.set(l, [])
    layers.get(l).push(n.id)
  }
  const sortedLayerKeys = [...layers.keys()].sort((a, b) => a - b)

  const slot = new Map()  // id -> x slot index within its layer
  for (const l of sortedLayerKeys) {
    const ids = layers.get(l)
    ids.sort((a, b) => bary(a, parents, slot) - bary(b, parents, slot))
    ids.forEach((id, i) => slot.set(id, i))
  }

  const maxSlots = Math.max(...[...layers.values()].map(a => a.length))
  const width = PAD * 2 + maxSlots * NODE_W + (maxSlots - 1) * COL_GAP
  const height = PAD * 2 + (sortedLayerKeys.length) * NODE_H + (sortedLayerKeys.length - 1) * ROW_GAP

  const pos = new Map()  // id -> {x, y}
  for (const l of sortedLayerKeys) {
    const ids = layers.get(l)
    const layerWidth = ids.length * NODE_W + (ids.length - 1) * COL_GAP
    const startX = (width - layerWidth) / 2
    ids.forEach((id, i) => {
      pos.set(id, {
        x: startX + i * (NODE_W + COL_GAP),
        y: PAD + l * (NODE_H + ROW_GAP),
      })
    })
  }

  const positioned = nodes.map(n => ({ node: n, x: pos.get(n.id).x, y: pos.get(n.id).y }))
  const edges = profile.edges
    .filter(e => pos.has(e.from) && pos.has(e.to))
    .map(e => ({
      is_shuffle: e.is_shuffle,
      // draw from parent (top, .to) down to child (bottom, .from)
      fromPos: pos.get(e.to),
      toPos: pos.get(e.from),
    }))

  const durations = nodes.map(n => n.duration_ms).filter(d => d != null)
  const maxDuration = durations.length ? Math.max(...durations) : 0

  return { positioned, edges, width, height, maxDuration }
}

function bary(id, parents, slot) {
  const ps = parents.get(id).map(p => slot.get(p)).filter(v => v != null)
  if (!ps.length) return 0
  return ps.reduce((a, b) => a + b, 0) / ps.length
}

function edgePath(from, to) {
  // from = parent (top center bottom edge), to = child (bottom, top edge)
  const x1 = from.x + NODE_W / 2, y1 = from.y + NODE_H
  const x2 = to.x + NODE_W / 2, y2 = to.y
  const my = (y1 + y2) / 2
  return `M ${x1} ${y1} C ${x1} ${my}, ${x2} ${my}, ${x2} ${y2}`
}

// cool (fast) -> amber -> red (slow)
function heatColor(duration, max) {
  if (duration == null || max <= 0) return 'var(--bg-raised)'
  const t = Math.min(1, duration / max)
  if (t < 0.5) {
    // bg-raised -> amber
    const a = t / 0.5
    return mix([38, 40, 46], [245, 158, 11], a)
  }
  const a = (t - 0.5) / 0.5
  return mix([245, 158, 11], [239, 68, 68], a)
}

function mix(c1, c2, t) {
  const r = Math.round(c1[0] + (c2[0] - c1[0]) * t)
  const g = Math.round(c1[1] + (c2[1] - c1[1]) * t)
  const b = Math.round(c1[2] + (c2[2] - c1[2]) * t)
  return `rgb(${r},${g},${b})`
}

function shorten(name) {
  return name.length > 20 ? name.slice(0, 19) + '…' : name
}

// ---- styles ----
const s = {
  wrap: { padding: '12px 16px', borderTop: '1px solid var(--border-dim)' },
  header: { display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 },
  title: { fontSize: 11, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--text-dim)', fontWeight: 500 },
  legend: { display: 'flex', gap: 12, alignItems: 'center' },
  legendItem: { display: 'flex', alignItems: 'center', gap: 4, fontSize: 10, color: 'var(--text-dim)', fontFamily: 'var(--font-mono)' },
  swatch: { width: 10, height: 10, borderRadius: 2, display: 'inline-block' },
  canvas: { position: 'relative', overflow: 'auto', maxHeight: '48vh' },
  nodeName: { fontFamily: 'var(--font-ui)', fontSize: 11, fontWeight: 600, fill: 'var(--text-primary)' },
  nodeMeta: { fontFamily: 'var(--font-mono)', fontSize: 9.5, fill: 'var(--text-secondary)' },
}

const tt = {
  box: {
    position: 'absolute', transform: 'translate(-50%, -100%)', zIndex: 20,
    background: 'var(--bg-raised)', border: '1px solid var(--border)', borderRadius: 'var(--radius)',
    padding: '8px 10px', minWidth: 180, maxWidth: 280, boxShadow: '0 6px 20px rgba(0,0,0,0.4)',
    pointerEvents: 'none',
  },
  name: { fontFamily: 'var(--font-ui)', fontSize: 11.5, fontWeight: 600, color: 'var(--amber)', marginBottom: 5 },
  row: { display: 'flex', justifyContent: 'space-between', gap: 12, fontSize: 10, fontFamily: 'var(--font-mono)', lineHeight: '1.5em' },
  k: { color: 'var(--text-dim)', whiteSpace: 'nowrap' },
  v: { color: 'var(--text-mono)', textAlign: 'right' },
}
