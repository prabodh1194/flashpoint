import { Sun, Moon, Bell, Settings } from 'lucide-react'

const VIEW_LABELS = {
  worksheet:  'Worksheets',
  warehouses: 'Warehouses',
  history:    'Query History',
  explorer:   'Data Explorer',
}

export function Topbar({ view, theme, onThemeToggle }) {
  return (
    <header style={styles.topbar}>
      <div style={styles.left}>
        <span style={styles.viewLabel}>{VIEW_LABELS[view] ?? view}</span>
        <StatusPill />
      </div>

      <div style={styles.right}>
        <IconBtn onClick={onThemeToggle} title="Toggle theme">
          {theme === 'dark' ? <Sun size={14} /> : <Moon size={14} />}
        </IconBtn>
        <IconBtn title="Notifications">
          <Bell size={14} />
        </IconBtn>
        <IconBtn title="Settings">
          <Settings size={14} />
        </IconBtn>
        <Avatar />
      </div>
    </header>
  )
}

function StatusPill() {
  return (
    <div style={styles.pill}>
      <span style={styles.dot} />
      <span style={styles.pillText}>connected</span>
    </div>
  )
}

function IconBtn({ children, onClick, title }) {
  return (
    <button style={styles.iconBtn} onClick={onClick} title={title}>
      {children}
    </button>
  )
}

function Avatar() {
  return (
    <div style={styles.avatar} title="Account">
      <span style={styles.avatarText}>P</span>
    </div>
  )
}

const styles = {
  topbar: {
    height: 'var(--topbar-h)',
    background: 'var(--bg-surface)',
    borderBottom: '1px solid var(--border-dim)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '0 16px 0 20px',
    flexShrink: 0,
    gap: 12,
  },
  left: {
    display: 'flex',
    alignItems: 'center',
    gap: 12,
  },
  viewLabel: {
    fontWeight: 500,
    fontSize: 13,
    color: 'var(--text-primary)',
    letterSpacing: '0.01em',
  },
  pill: {
    display: 'flex',
    alignItems: 'center',
    gap: 5,
    background: 'var(--amber-bg)',
    border: '1px solid var(--amber-border)',
    borderRadius: 100,
    padding: '2px 8px',
  },
  dot: {
    width: 5,
    height: 5,
    borderRadius: '50%',
    background: 'var(--green)',
    boxShadow: '0 0 4px var(--green)',
  },
  pillText: {
    fontSize: 11,
    fontFamily: 'var(--font-mono)',
    color: 'var(--amber)',
    letterSpacing: '0.04em',
  },
  right: {
    display: 'flex',
    alignItems: 'center',
    gap: 4,
  },
  iconBtn: {
    width: 28,
    height: 28,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    background: 'none',
    border: 'none',
    cursor: 'pointer',
    color: 'var(--text-secondary)',
    borderRadius: 'var(--radius-sm)',
    transition: 'color 0.12s, background 0.12s',
  },
  avatar: {
    width: 26,
    height: 26,
    borderRadius: '50%',
    background: 'var(--amber-bg)',
    border: '1px solid var(--amber-border)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    cursor: 'pointer',
    marginLeft: 4,
  },
  avatarText: {
    fontFamily: 'var(--font-mono)',
    fontSize: 11,
    fontWeight: 600,
    color: 'var(--amber)',
  },
}
