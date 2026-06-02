const BASE = import.meta.env.VITE_GATEWAY_URL || 'http://3.86.115.219:8080'

export async function createSession() {
  const r = await fetch(`${BASE}/sessions`, { method: 'POST' })
  if (!r.ok) throw new Error(`createSession: ${r.status} ${await r.text()}`)
  return r.json()
}

export async function deleteSession(sessionId) {
  await fetch(`${BASE}/sessions/${sessionId}`, { method: 'DELETE' })
}

export async function runQuery(sessionId, sql) {
  const r = await fetch(`${BASE}/sessions/${sessionId}/query`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sql }),
  })
  if (!r.ok) {
    const detail = await r.json().then(j => j.detail).catch(() => r.statusText)
    throw new Error(detail)
  }
  return r.json()
}

export async function listSessions() {
  const r = await fetch(`${BASE}/sessions`)
  if (!r.ok) throw new Error(`listSessions: ${r.status}`)
  return r.json()  // { sessions: [id, ...], count: N }
}

export async function fetchHistory() {
  const r = await fetch(`${BASE}/history`)
  if (!r.ok) throw new Error(`history: ${r.status}`)
  return r.json()
}

export async function healthz() {
  const r = await fetch(`${BASE}/healthz`)
  return r.json()
}
