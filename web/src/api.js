const BASE = import.meta.env.VITE_GATEWAY_URL || 'http://3.86.115.219:8080'

export async function createWarehouse(name, size = 'XS') {
  const r = await fetch(`${BASE}/warehouses`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, size }),
  })
  if (!r.ok) throw new Error(`createWarehouse: ${r.status} ${await r.text()}`)
  return r.json()
}

export async function deleteWarehouse(name) {
  await fetch(`${BASE}/warehouses/${name}`, { method: 'DELETE' })
}

export async function suspendWarehouse(name) {
  const r = await fetch(`${BASE}/warehouses/${name}/suspend`, { method: 'POST' })
  if (!r.ok) throw new Error(`suspend: ${r.status}`)
  return r.json()
}

export async function resumeWarehouse(name) {
  const r = await fetch(`${BASE}/warehouses/${name}/resume`, { method: 'POST' })
  if (!r.ok) throw new Error(`resume: ${r.status} ${await r.text()}`)
  return r.json()
}

export async function resizeWarehouse(name, size) {
  const r = await fetch(`${BASE}/warehouses/${name}/resize`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ size }),
  })
  if (!r.ok) throw new Error(`resize: ${r.status} ${await r.text()}`)
  return r.json()
}

export async function runQuery(name, sql) {
  const r = await fetch(`${BASE}/warehouses/${name}/query`, {
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
  return r.json()
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
