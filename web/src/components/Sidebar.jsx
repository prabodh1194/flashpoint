import { FileCode2, Database, History, BarChart3, ChevronRight, Zap } from 'lucide-react'

const NAV_ITEMS = [
  { id: 'worksheet',  label: 'Worksheets',   icon: FileCode2 },
  { id: 'warehouses', label: 'Warehouses',   icon: Zap },
  { id: 'history',    label: 'Query History', icon: History },
  { id: 'explorer',   label: 'Data Explorer', icon: Database },
]

export function Sidebar({ active, onNav, open, onToggle }) {
  return (
    <nav style={{ ...styles.nav, width: open ? 'var(--nav-w-open)' : 'var(--nav-w)' }}>
      {/* Logo / toggle */}
      <button style={styles.logoBtn} onClick={onToggle} title="Toggle nav">
        <span style={styles.logoMark}>⬡</span>
        {open && <span style={styles.logoText}>Flashpoint</span>}
      </button>

      <div style={styles.divider} />

      {/* Nav items */}
      {NAV_ITEMS.map(({ id, label, icon: Icon }) => {
        const isActive = active === id
        return (
          <button
            key={id}
            style={{
              ...styles.navItem,
              ...(isActive ? styles.navItemActive : {}),
            }}
            onClick={() => onNav(id)}
            title={!open ? label : undefined}
          >
            <Icon size={16} style={{ flexShrink: 0, color: isActive ? 'var(--amber)' : 'inherit' }} />
            {open && <span style={styles.navLabel}>{label}</span>}
            {open && isActive && (
              <ChevronRight size={12} style={{ marginLeft: 'auto', color: 'var(--amber)', opacity: 0.6 }} />
            )}
          </button>
        )
      })}

      {/* Bottom accent line */}
      <div style={styles.bottomAccent} />
    </nav>
  )
}

const styles = {
  nav: {
    height: '100%',
    background: 'var(--bg-surface)',
    borderRight: '1px solid var(--border-dim)',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'stretch',
    flexShrink: 0,
    transition: 'width 0.18s ease',
    overflow: 'hidden',
    position: 'relative',
  },
  logoBtn: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    height: 'var(--topbar-h)',
    padding: '0 16px',
    background: 'none',
    border: 'none',
    cursor: 'pointer',
    color: 'var(--amber)',
    flexShrink: 0,
    whiteSpace: 'nowrap',
    overflow: 'hidden',
  },
  logoMark: {
    fontSize: 18,
    lineHeight: 1,
    flexShrink: 0,
  },
  logoText: {
    fontFamily: 'var(--font-mono)',
    fontSize: 12,
    fontWeight: 600,
    letterSpacing: '0.08em',
    textTransform: 'uppercase',
    color: 'var(--text-primary)',
  },
  divider: {
    height: 1,
    background: 'var(--border-dim)',
    margin: '0 0 4px',
  },
  navItem: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    height: 36,
    padding: '0 16px',
    background: 'none',
    border: 'none',
    cursor: 'pointer',
    color: 'var(--text-secondary)',
    fontSize: 13,
    fontFamily: 'var(--font-ui)',
    whiteSpace: 'nowrap',
    overflow: 'hidden',
    transition: 'color 0.12s, background 0.12s',
    borderRadius: 0,
  },
  navItemActive: {
    color: 'var(--text-primary)',
    background: 'var(--amber-bg)',
    borderLeft: '2px solid var(--amber)',
    paddingLeft: 14,
  },
  navLabel: {
    fontSize: 13,
    fontWeight: 400,
  },
  bottomAccent: {
    marginTop: 'auto',
    height: 2,
    background: 'linear-gradient(90deg, var(--amber) 0%, transparent 100%)',
    opacity: 0.4,
  },
}
