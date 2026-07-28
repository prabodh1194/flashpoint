const BASE = import.meta.env.VITE_GATEWAY_URL || 'http://3.86.115.219:8080'

export async function createWarehouse(size = 'XS') {
  const r = await fetch(`${BASE}/warehouses`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ size }),
  })
  if (!r.ok) throw new Error(`createWarehouse: ${r.status} ${await r.text()}`)
  return r.json()
}

export async function deleteWarehouse(sessionId) {
  await fetch(`${BASE}/warehouses/${sessionId}`, { method: 'DELETE' })
}

export async function suspendWarehouse(sessionId) {
  const r = await fetch(`${BASE}/warehouses/${sessionId}/suspend`, { method: 'POST' })
  if (!r.ok) throw new Error(`suspend: ${r.status}`)
  return r.json()
}

export async function resumeWarehouse(sessionId) {
  const r = await fetch(`${BASE}/warehouses/${sessionId}/resume`, { method: 'POST' })
  if (!r.ok) throw new Error(`resume: ${r.status} ${await r.text()}`)
  return r.json()
}

export async function resizeWarehouse(sessionId, size) {
  const r = await fetch(`${BASE}/warehouses/${sessionId}/resize`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ size }),
  })
  if (!r.ok) throw new Error(`resize: ${r.status} ${await r.text()}`)
  return r.json()
}

export async function runQuery(sessionId, sql) {
  const r = await fetch(`${BASE}/warehouses/${sessionId}/query`, {
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

export async function listWarehouses() {
  const r = await fetch(`${BASE}/warehouses`)
  if (!r.ok) throw new Error(`listWarehouses: ${r.status}`)
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
