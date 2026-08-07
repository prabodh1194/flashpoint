const BASE = import.meta.env.VITE_GATEWAY_URL || 'http://localhost:8080'

export class GatewayOfflineError extends Error {
  constructor() {
    super('Gateway is offline — sleeping to save cost')
    this.name = 'GatewayOfflineError'
  }
}

function _wrap(fn) {
  return async (...args) => {
    try {
      return await fn(...args)
    } catch (e) {
      if (e instanceof TypeError && e.message.includes('fetch')) throw new GatewayOfflineError()
      throw e
    }
  }
}

const _request = _wrap(async (method, path, body) => {
  const opts = { method, headers: { 'Content-Type': 'application/json' } }
  if (body) opts.body = JSON.stringify(body)
  const r = await fetch(`${BASE}${path}`, opts)
  if (!r.ok) throw new Error(`${method} ${path}: ${r.status} ${(await r.text()).slice(0, 200)}`)
  if (r.status === 204) return null
  return r.json()
})

export async function createWarehouse(name, size = 'XS') {
  return _request('POST', '/warehouses', { name, size })
}

export async function deleteWarehouse(name) {
  return _request('DELETE', `/warehouses/${name}`)
}

export async function suspendWarehouse(name) {
  return _request('POST', `/warehouses/${name}/suspend`)
}

export async function resumeWarehouse(name) {
  return _request('POST', `/warehouses/${name}/resume`)
}

export async function resizeWarehouse(name, size) {
  return _request('POST', `/warehouses/${name}/resize`, { size })
}

export async function runQuery(name, sql) {
  return _request('POST', `/warehouses/${name}/query`, { sql })
}

export async function listWarehouses() {
  return _request('GET', '/warehouses')
}

export async function fetchHistory() {
  return _request('GET', '/history')
}

export async function fetchQueryById(queryId) {
  return _request('GET', `/history/${queryId}`)
}

export async function healthz() {
  return _request('GET', '/healthz')
}
