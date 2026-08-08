import { useEffect, useState } from 'react'

// Minimal hash router: every view owns a URL (e.g. #/history/59ccd824ad04e34f).
// Hash routing keeps deep links + reload working on any static host with zero
// server-side fallback config.

const DEFAULT = '/worksheets'

export function currentPath() {
  const h = window.location.hash.replace(/^#/, '')
  if (!h) return DEFAULT
  return h.startsWith('/') ? h : `/${h}`
}

export function useHashRoute() {
  const [path, setPath] = useState(currentPath)
  useEffect(() => {
    const onHash = () => setPath(currentPath())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])
  return path
}

export function navigate(path) {
  if (currentPath() === path) return
  window.location.hash = path
}
