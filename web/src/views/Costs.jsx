import { useState, useEffect, useCallback } from 'react'
import {
  Wallet, Cpu, Server, HardDrive, Database, Boxes, Archive, Network,
  RefreshCw, Loader, Clock, Pause,
} from 'lucide-react'
import { ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, Cell } from 'recharts'

import { fetchResources, fetchCosts, suspendWarehouse } from '../api'
import { OfflineBanner } from '../components/OfflineBanner'
import { navigate } from '../router'

function fmtUsd(v) {
  if (v == null) return '—'
  if (v < 0.01) return `$${v.toFixed(4)}`
  return `$${v.toFixed(2)}`
}

function fmtUptime(h) {
  if (h == null) return '—'
  if (h < 24) return `${h.toFixed(1)}h`
  return `${(h / 24).toFixed(1)}d`
}

function shortId(id) {
  const clean = String(id).split('/').pop()
  return clean.length > 30 ? `${clean.slice(0, 30)}…` : clean
}

const KIND_META = {
  fargate:  { icon: Cpu,      label: 'Fargate' },
  ec2:      { icon: Server,   label: 'Gateway EC2' },
  ebs:      { icon: HardDrive,label: 'EBS Volume' },
  dynamodb: { icon: Database, label: 'DynamoDB' },
  s3:       { icon: Archive,  label: 'S3' },
  ecr:      { icon: Boxes,    label: 'ECR' },
  vpc:      { icon: Network,  label: 'VPC' },
  logs:     { icon: Clock,    label: 'Log Groups' },
  other:    { icon: Boxes,    label: 'Other' },
}

const KIND_ORDER = ['fargate', 'ec2', 'ebs', 'dynamodb', 's3', 'ecr', 'logs', 'vpc', 'other']

function liveish(state) {
  return state === 'running' || state === 'in-use' || state === 'active'
}

function StateDot({ state }) {
  const color = liveish(state) ? 'var(--green)' : 'var(--text-dim)'
  return (
    <span style={{
      width: 6, height: 6, borderRadius: '50%', background: color, flexShrink: 0,
    }} />
  )
}

export function Costs({ gatewayOnline }) {
  const [costs, setCosts] = useState(null)
  const [resources, setResources] = useState(null)
  const [loading, setLoading] = useState(true)
  const [suspendName, setSuspendName] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [c, r] = await Promise.all([fetchCosts(30), fetchResources()])
      setCosts(c)
      setResources(r)
    } catch (e) {
      console.error('costs load failed', e)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const doSuspend = async (name) => {
    setSuspendName(name)
    try {
      await suspendWarehouse(name)
      await load()
    } finally {
      setSuspendName(null)
    }
  }

  const totals = costs?.totals ?? {}
  const projection = costs?.projection ?? { monthly_usd: 0, budget_usd: 0, over_budget: false, spike_days: [] }
  const perWh = costs?.per_warehouse ?? []
  const days = costs?.days ?? []
  const rows = resources?.resources ?? []
  const grouped = KIND_ORDER
    .map(kind => ({ kind, rows: rows.filter(r => r.kind === kind) }))
    .filter(g => g.rows.length > 0)
  const lastDay = days.length ? days[days.length - 1].date : null

  return (
    <div style={s.root}>
      {!gatewayOnline && <OfflineBanner message="Cost Center unavailable while the gateway is asleep." />}

      <div style={s.header}>
        <h2 style={s.title}>Cost Center</h2>
        <span style={s.sub}>
          {costs?.source === 'cost-explorer' ? 'Cost Explorer · ~24h lag' : 'metered · live'}
        </span>
        <button style={s.refresh} onClick={load} title="Refresh">
          {loading
            ? <Loader size={13} style={{ animation: 'spin 1s linear infinite' }} />
            : <RefreshCw size={13} />}
        </button>
      </div>

      {/* Stat strip */}
      <div style={s.stats}>
        <Stat label="Today" value={fmtUsd(totals.today)} live />
        <Stat label="Last 7 days" value={fmtUsd(totals.d7)} />
        <Stat label="Last 30 days" value={fmtUsd(totals.d30)} />
        <Stat
          label="Projected month"
          value={fmtUsd(projection.monthly_usd)}
          sub={`budget ${fmtUsd(projection.budget_usd)}`}
          warn={projection.over_budget}
        />
        <Stat
          label="Active resources"
          value={rows.filter(r => liveish(r.state)).length}
          sub={`${rows.length} tracked total`}
        />
      </div>

      {projection.over_budget && (
        <div style={s.banner}>
          <span>Projected month of {fmtUsd(projection.monthly_usd)} exceeds the {fmtUsd(projection.budget_usd)} budget — consider suspending idle warehouses.</span>
        </div>
      )}

      {/* Daily spend chart */}
      <div style={s.card}>
        <div style={s.cardHead}>
          <span style={s.cardTitle}>Daily spend</span>
          {costs?.source === 'cost-explorer' && <span style={s.badge}>Cost Explorer</span>}
        </div>
        <div style={s.chartWrap}>
          {days.length > 0 ? (
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={days} margin={{ top: 8, right: 8, bottom: 0, left: -18 }}>
                <XAxis
                  dataKey="date"
                  tick={{ fill: 'var(--text-dim)', fontSize: 10, fontFamily: 'var(--font-mono)' }}
                  tickFormatter={d => d.slice(5)}
                  interval={Math.ceil(days.length / 10)}
                  axisLine={{ stroke: 'var(--border-dim)' }}
                  tickLine={false}
                />
                <YAxis
                  tick={{ fill: 'var(--text-dim)', fontSize: 10, fontFamily: 'var(--font-mono)' }}
                  tickFormatter={v => `$${v.toFixed(2)}`}
                  axisLine={false}
                  tickLine={false}
                />
                <Tooltip
                  contentStyle={{
                    background: 'var(--bg-raised)', border: '1px solid var(--border)',
                    borderRadius: 'var(--radius)', fontFamily: 'var(--font-mono)', fontSize: 11,
                  }}
                  labelStyle={{ color: 'var(--text-secondary)' }}
                  itemStyle={{ color: 'var(--amber)' }}
                  formatter={v => [fmtUsd(v), 'spend']}
                />
                <Bar dataKey="total_usd" radius={[2, 2, 0, 0]}>
                  {days.map((d, i) => (
                    <Cell
                      key={i}
                      fill={projection.spike_days.includes(d.date) ? 'var(--red)' : 'var(--amber)'}
                      opacity={projection.spike_days.includes(d.date) ? 1 : (d.date === lastDay ? 1 : 0.35)}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div style={s.emptyText}>No cost data yet — run a query to start metering.</div>
          )}
        </div>
      </div>

      {/* Resources */}
      <div style={s.sectionTitle}>
        <span style={s.cardTitle}>Resources</span>
        <span style={s.sub}>{rows.length} tracked</span>
      </div>
      {grouped.map(g => {
        const Icon = KIND_META[g.kind]?.icon ?? Boxes
        return (
          <div key={g.kind} style={s.card}>
            <div style={s.cardHead}>
              <span style={s.kindLabel}>{KIND_META[g.kind]?.label ?? g.kind}</span>
              <span style={s.sub}>{g.rows.length}</span>
            </div>
            <table style={s.table}>
              <thead>
                <tr>
                  <th style={s.th}>Resource</th>
                  <th style={s.th}>State</th>
                  <th style={s.th}>Spec</th>
                  <th style={s.th}>Uptime</th>
                  <th style={s.th}>Est. monthly</th>
                  <th style={s.th}>Warehouse</th>
                  <th style={s.th} />
                </tr>
              </thead>
              <tbody>
                {g.rows.map(r => (
                  <tr key={r.id} style={s.tr}>
                    <td style={s.td}>
                      <div style={s.resCell}>
                        <Icon size={12} style={{ color: 'var(--amber)', flexShrink: 0 }} />
                        <span style={s.resName}>{shortId(r.id)}</span>
                      </div>
                    </td>
                    <td style={s.td}>
                      <div style={s.resCell}>
                        <StateDot state={r.state} />
                        <span style={s.stateText}>{r.state}</span>
                      </div>
                    </td>
                    <td style={s.td}>{r.type || '—'}</td>
                    <td style={{ ...s.td, ...s.mono }}>{fmtUptime(r.uptime_h)}</td>
                    <td style={{ ...s.td, ...s.mono }}>
                      {r.monthly_est != null ? `${fmtUsd(r.monthly_est)}/mo` : '—'}
                    </td>
                    <td style={s.td}>
                      {r.warehouse
                        ? (
                          <button style={s.whChip} onClick={() => navigate('/warehouses')}>
                            {r.warehouse}
                          </button>
                        )
                        : <span style={s.infraTag}>infra</span>}
                    </td>
                    <td style={s.td}>
                      {r.state === 'running' && r.warehouse && (
                        <button
                          style={s.actionBtn}
                          onClick={() => doSuspend(r.warehouse)}
                          disabled={suspendName === r.warehouse}
                          title={`Suspend ${r.warehouse}`}
                        >
                          {suspendName === r.warehouse
                            ? <Loader size={11} style={{ animation: 'spin 1s linear infinite' }} />
                            : <Pause size={11} />}
                          Suspend
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      })}

      {grouped.length === 0 && !loading && (
        <div style={s.empty}><span style={s.emptyText}>No resources found yet.</span></div>
      )}

      {/* Per-warehouse spend */}
      <div style={s.sectionTitle}><span style={s.cardTitle}>Warehouse spend</span></div>
      <div style={s.card}>
        <table style={s.table}>
          <thead>
            <tr>
              {['Warehouse', 'Size', 'Status', 'Today', '7d', '30d'].map(h => (
                <th key={h} style={s.th}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {perWh.map(w => (
              <tr key={w.name} style={s.tr}>
                <td style={s.td}>
                  <div style={s.resCell}>
                    <Wallet size={12} style={{ color: 'var(--amber)', flexShrink: 0 }} />
                    <span style={s.resName}>{w.name}</span>
                  </div>
                </td>
                <td style={{ ...s.td, ...s.mono }}>{w.size}</td>
                <td style={s.td}>
                  <div style={s.resCell}>
                    <StateDot state={w.status} />
                    <span style={s.stateText}>{w.status}</span>
                  </div>
                </td>
                <td style={{ ...s.td, ...s.mono, color: 'var(--amber)' }}>{fmtUsd(w.today)}</td>
                <td style={{ ...s.td, ...s.mono }}>{fmtUsd(w.d7)}</td>
                <td style={{ ...s.td, ...s.mono }}>{fmtUsd(w.d30)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {perWh.length === 0 && (
          <div style={s.emptyHint}>No metered warehouses yet — run a query to start accruing.</div>
        )}
      </div>

      <div style={s.footnote}>
        {costs?.source === 'meters'
          ? 'Live meter data (Cost Explorer not configured or still propagating).'
          : 'Cost Explorer totals lag up to ~24h; today is fused with live meters.'}
      </div>
    </div>
  )
}

function Stat({ label, value, sub, live, warn }) {
  return (
    <div style={s.stat}>
      <span style={s.statLabel}>{label}</span>
      <span style={{
        ...s.statValue,
        ...(live ? { color: 'var(--amber)' } : {}),
        ...(warn ? { color: 'var(--red)' } : {}),
      }}>{value}</span>
      {sub && <span style={s.statSub}>{sub}</span>}
    </div>
  )
}

const s = {
  root: { flex: 1, overflow: 'auto', padding: '20px 24px', maxWidth: 1100, width: '100%' },
  header: { display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 },
  title: { fontSize: 18, fontWeight: 600, color: 'var(--text-primary)', margin: 0 },
  sub: { fontSize: 11, color: 'var(--text-dim)', fontFamily: 'var(--font-mono)' },
  refresh: {
    marginLeft: 'auto', background: 'var(--bg-raised)', border: '1px solid var(--border)',
    borderRadius: 'var(--radius)', color: 'var(--text-secondary)', cursor: 'pointer',
    padding: '5px 8px', display: 'flex', alignItems: 'center',
  },
  stats: {
    display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))',
    gap: 10, marginBottom: 16,
  },
  stat: {
    background: 'var(--bg-surface)', border: '1px solid var(--border-dim)',
    borderRadius: 'var(--radius)', padding: '12px 14px',
    display: 'flex', flexDirection: 'column', gap: 4,
  },
  statLabel: {
    fontSize: 10, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--text-dim)',
  },
  statValue: {
    fontSize: 20, fontWeight: 600, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)',
  },
  statSub: { fontSize: 11, color: 'var(--text-dim)' },
  banner: {
    background: 'var(--red)', color: '#fff', borderRadius: 'var(--radius)',
    padding: '10px 14px', marginBottom: 16, fontSize: 12, fontWeight: 500,
  },
  card: {
    background: 'var(--bg-surface)', border: '1px solid var(--border-dim)',
    borderRadius: 'var(--radius)', marginBottom: 16, overflow: 'hidden',
  },
  cardHead: { display: 'flex', alignItems: 'center', gap: 8, padding: '12px 16px 8px' },
  cardTitle: { fontSize: 12, fontWeight: 600, color: 'var(--text-primary)' },
  badge: {
    fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--amber)',
    background: 'var(--amber-bg)', border: '1px solid var(--amber-border)',
    borderRadius: 100, padding: '1px 7px',
  },
  chartWrap: { height: 180, padding: '0 12px 12px', display: 'flex', alignItems: 'center' },
  sectionTitle: { display: 'flex', alignItems: 'center', gap: 10, margin: '4px 0 10px' },
  kindLabel: { fontSize: 12, fontWeight: 600, color: 'var(--text-primary)' },
  table: { width: '100%', borderCollapse: 'collapse' },
  th: {
    textAlign: 'left', padding: '6px 16px', fontSize: 10, letterSpacing: '0.05em',
    textTransform: 'uppercase', color: 'var(--text-dim)', fontWeight: 500,
    borderBottom: '1px solid var(--border-dim)', whiteSpace: 'nowrap',
  },
  tr: { borderBottom: '1px solid var(--border-dim)' },
  td: { padding: '7px 16px', fontSize: 12, color: 'var(--text-secondary)' },
  resCell: { display: 'flex', alignItems: 'center', gap: 7, minWidth: 0 },
  resName: { color: 'var(--text-primary)', fontFamily: 'var(--font-mono)', fontSize: 11.5 },
  stateText: { fontSize: 11, color: 'var(--text-secondary)' },
  mono: { fontFamily: 'var(--font-mono)', fontSize: 11.5, color: 'var(--text-mono)' },
  whChip: {
    background: 'var(--amber-bg)', border: '1px solid var(--amber-border)', color: 'var(--amber)',
    borderRadius: 100, padding: '1px 8px', fontSize: 10, fontFamily: 'var(--font-mono)',
    cursor: 'pointer',
  },
  infraTag: { fontSize: 10, color: 'var(--text-dim)', fontFamily: 'var(--font-mono)' },
  actionBtn: {
    display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 11,
    background: 'none', border: '1px solid var(--border)', color: 'var(--amber)',
    borderRadius: 'var(--radius-sm)', padding: '3px 8px', cursor: 'pointer', whiteSpace: 'nowrap',
  },
  empty: { padding: '40px 20px', textAlign: 'center' },
  emptyText: { fontSize: 13, color: 'var(--text-secondary)' },
  emptyHint: { padding: '12px 16px', fontSize: 12, color: 'var(--text-dim)' },
  footnote: { padding: '0 4px 24px', fontSize: 11, color: 'var(--text-dim)' },
}
