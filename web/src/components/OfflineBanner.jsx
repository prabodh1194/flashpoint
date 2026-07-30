import { WifiOff } from 'lucide-react'

export function OfflineBanner({ message }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 10,
      padding: '20px 24px', marginBottom: 0,
      background: 'rgba(139,147,168,0.06)', borderBottom: '1px solid var(--border-dim)',
      flexShrink: 0,
    }}>
      <WifiOff size={15} style={{ color: 'var(--text-dim)', flexShrink: 0 }} />
      <span style={{ fontSize: 12, color: 'var(--text-dim)', lineHeight: 1.5 }}>
        {message || 'Gateway is sleeping — run `tofu apply` to wake it.'}
      </span>
    </div>
  )
}
