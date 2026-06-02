import { Zap, Play, Square, Settings, TrendingUp } from 'lucide-react'

const WH_DATA = [
  { id: 'dev-xs',  size: 'XS', status: 'running', executors: 2, queries: 1, cost: '$0.08/hr' },
  { id: 'prod-s',  size: 'S',  status: 'suspended', executors: 0, queries: 0, cost: '$0.16/hr' },
  { id: 'etl-m',   size: 'M',  status: 'suspended', executors: 0, queries: 0, cost: '$0.32/hr' },
]

const SIZE_CORES = { XS: 2, S: 4, M: 8, L: 16, XL: 32 }

export function Warehouses() {
  return (
    <div style={s.root}>
      <div style={s.header}>
        <h2 style={s.title}>Warehouses</h2>
        <button style={s.createBtn}>
          <Zap size={13} />
          New Warehouse
        </button>
      </div>

      <div style={s.grid}>
        {WH_DATA.map(wh => (
          <WarehouseCard key={wh.id} wh={wh} />
        ))}
      </div>
    </div>
  )
}

function WarehouseCard({ wh }) {
  const isRunning = wh.status === 'running'
  return (
    <div style={{ ...s.card, ...(isRunning ? s.cardRunning : {}) }}>
      <div style={s.cardTop}>
        <div style={s.cardName}>
          <span style={s.cardId}>{wh.id}</span>
          <StatusBadge status={wh.status} />
        </div>
        <div style={s.cardActions}>
          {isRunning ? (
            <ActionBtn icon={<Square size={12} />} label="Suspend" danger />
          ) : (
            <ActionBtn icon={<Play size={12} />} label="Resume" />
          )}
          <ActionBtn icon={<Settings size={12} />} label="Configure" />
        </div>
      </div>

      <div style={s.cardMeta}>
        <MetaPair label="Size" value={wh.size} mono />
        <MetaPair label="Executors" value={isRunning ? `${wh.executors} active` : '—'} />
        <MetaPair label="Active queries" value={String(wh.queries)} mono />
        <MetaPair label="Rate" value={wh.cost} mono />
      </div>

      {isRunning && (
        <div style={s.utilBar}>
          <div style={s.utilLabel}>CPU utilisation</div>
          <div style={s.utilTrack}>
            <div style={{ ...s.utilFill, width: '34%' }} />
          </div>
          <span style={s.utilPct}>34%</span>
        </div>
      )}
    </div>
  )
}

function StatusBadge({ status }) {
  const colors = {
    running:   { bg: 'rgba(34,197,94,0.1)',  border: 'rgba(34,197,94,0.3)',  color: '#22c55e' },
    suspended: { bg: 'rgba(139,147,168,0.1)', border: 'rgba(139,147,168,0.2)', color: '#8b93a8' },
  }
  const c = colors[status] ?? colors.suspended
  return (
    <div style={{ ...s.badge, background: c.bg, border: `1px solid ${c.border}`, color: c.color }}>
      {status === 'running' && <span style={{ ...s.dot, background: c.color }} />}
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

function ActionBtn({ icon, label, danger }) {
  return (
    <button style={{ ...s.actionBtn, ...(danger ? s.actionBtnDanger : {}) }}>
      {icon}
      <span>{label}</span>
    </button>
  )
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
    justifyContent: 'space-between',
    marginBottom: 20,
  },
  title: {
    fontSize: 15,
    fontWeight: 500,
    color: 'var(--text-primary)',
  },
  createBtn: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
    height: 30,
    padding: '0 14px',
    background: 'var(--amber-bg)',
    border: '1px solid var(--amber-border)',
    borderRadius: 'var(--radius-sm)',
    cursor: 'pointer',
    color: 'var(--amber)',
    fontSize: 12,
    fontFamily: 'var(--font-ui)',
    fontWeight: 500,
  },
  grid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))',
    gap: 12,
  },
  card: {
    background: 'var(--bg-surface)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius-lg)',
    padding: 16,
    display: 'flex',
    flexDirection: 'column',
    gap: 12,
  },
  cardRunning: {
    border: '1px solid var(--amber-border)',
    background: 'var(--bg-surface)',
  },
  cardTop: {
    display: 'flex',
    alignItems: 'flex-start',
    justifyContent: 'space-between',
    gap: 8,
  },
  cardName: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
  },
  cardId: {
    fontFamily: 'var(--font-mono)',
    fontSize: 13,
    fontWeight: 600,
    color: 'var(--text-primary)',
  },
  cardActions: {
    display: 'flex',
    gap: 6,
  },
  badge: {
    display: 'flex',
    alignItems: 'center',
    gap: 5,
    padding: '2px 8px',
    borderRadius: 100,
    fontSize: 11,
    fontFamily: 'var(--font-mono)',
  },
  dot: {
    width: 5,
    height: 5,
    borderRadius: '50%',
  },
  cardMeta: {
    display: 'grid',
    gridTemplateColumns: '1fr 1fr',
    gap: '8px 16px',
  },
  metaPair: {
    display: 'flex',
    flexDirection: 'column',
    gap: 1,
  },
  metaLabel: {
    fontSize: 10,
    letterSpacing: '0.06em',
    textTransform: 'uppercase',
    color: 'var(--text-dim)',
  },
  metaVal: {
    fontSize: 12,
    color: 'var(--text-primary)',
  },
  utilBar: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    borderTop: '1px solid var(--border-dim)',
    paddingTop: 10,
  },
  utilLabel: {
    fontSize: 11,
    color: 'var(--text-dim)',
    minWidth: 100,
  },
  utilTrack: {
    flex: 1,
    height: 4,
    background: 'var(--border)',
    borderRadius: 2,
    overflow: 'hidden',
  },
  utilFill: {
    height: '100%',
    background: 'var(--amber)',
    borderRadius: 2,
    transition: 'width 0.3s ease',
  },
  utilPct: {
    fontSize: 11,
    fontFamily: 'var(--font-mono)',
    color: 'var(--text-secondary)',
    minWidth: 32,
    textAlign: 'right',
  },
  actionBtn: {
    display: 'flex',
    alignItems: 'center',
    gap: 4,
    height: 24,
    padding: '0 8px',
    background: 'var(--bg-raised)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius-sm)',
    cursor: 'pointer',
    color: 'var(--text-secondary)',
    fontSize: 11,
    fontFamily: 'var(--font-ui)',
  },
  actionBtnDanger: {
    color: 'var(--red)',
    borderColor: 'rgba(239,68,68,0.3)',
    background: 'rgba(239,68,68,0.06)',
  },
}
