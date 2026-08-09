import { useState } from 'react'
import { Database, Table2, ChevronRight, ChevronDown, Hash, Type, Calendar } from 'lucide-react'

import { OfflineBanner } from '../components/OfflineBanner'

// Live demo schema, mirrors the e2e script's seed (scripts/e2e_demo.py):
// 10M orders joined against 1M customers via the Spark Connect server on :15002.
const CATALOG = {
  'spark_catalog': {
    default: {
      name: 'default',
      tables: {
        orders: [
          { name: 'id',           type: 'INT' },
          { name: 'customer_id',  type: 'INT' },
          { name: 'product_id',   type: 'INT' },
          { name: 'amount',       type: 'DECIMAL(10,2)' },
          { name: 'order_date',   type: 'STRING' },
        ],
        customers: [
          { name: 'customer_id',  type: 'INT' },
          { name: 'name',         type: 'STRING' },
          { name: 'region',       type: 'STRING' },
          { name: 'tier',         type: 'INT' },
        ],
      },
    },
  },
}

// Sample rows, real values from the seeded parquet files.
const SAMPLE_ROWS = {
  'spark_catalog.default.customers': [
    { customer_id: 1,     name: 'user_1',    region: 'north',   tier: 1 },
    { customer_id: 2,     name: 'user_2',    region: 'south',   tier: 2 },
    { customer_id: 3,     name: 'user_3',    region: 'east',    tier: 0 },
    { customer_id: 4,     name: 'user_4',    region: 'west',    tier: 1 },
    { customer_id: 5,     name: 'user_5',    region: 'central', tier: 2 },
    { customer_id: 6,     name: 'user_6',    region: 'north',   tier: 0 },
  ],
  'spark_catalog.default.orders': [
    { id: 1, customer_id: 1, product_id: 1,   amount: '1.00', order_date: '2024-01-02' },
    { id: 2, customer_id: 2, product_id: 2,   amount: '2.00', order_date: '2024-01-03' },
    { id: 3, customer_id: 3, product_id: 3,   amount: '3.00', order_date: '2024-01-04' },
    { id: 4, customer_id: 4, product_id: 4,   amount: '4.00', order_date: '2024-01-05' },
    { id: 5, customer_id: 5, product_id: 5,   amount: '5.00', order_date: '2024-01-06' },
    { id: 6, customer_id: 6, product_id: 6,   amount: '6.00', order_date: '2024-01-07' },
  ],
}

function typeIcon(type) {
  if (type.startsWith('BIGINT') || type.startsWith('DECIMAL') || type.startsWith('INT'))
    return <Hash size={11} style={{ color: 'var(--blue)' }} />
  if (type.startsWith('TIMESTAMP') || type.startsWith('DATE'))
    return <Calendar size={11} style={{ color: 'var(--purple)' }} />
  return <Type size={11} style={{ color: 'var(--green)' }} />
}

export function DataExplorer({ gatewayOnline }) {
  const [openDbs, setOpenDbs] = useState({ 'spark_catalog': true })
  const [openTables, setOpenTables] = useState({ 'spark_catalog.default': true })
  const [selected, setSelected] = useState('spark_catalog.default.customers')

  const toggleDb = db => setOpenDbs(s => ({ ...s, [db]: !s[db] }))
  const toggleTable = key => setOpenTables(s => ({ ...s, [key]: !s[key] }))
  const selectTable = key => setSelected(key)

  const parts = selected.split('.')
  const selDb = parts[0], selSchema = parts[1] ?? '', selTable = parts[2] ?? ''
  const cols = CATALOG[selDb]?.[selSchema]?.tables?.[selTable]
  const rows = SAMPLE_ROWS[selected]

  return (
    <div style={s.root}>
      {!gatewayOnline && <OfflineBanner />}
      {/* Tree */}
      <div style={s.tree}>
        <div style={s.treeHeader}>Catalog</div>
        {Object.entries(CATALOG).map(([db, schemas]) => (
          <div key={db}>
            <button style={s.dbRow} onClick={() => toggleDb(db)}>
              {openDbs[db] ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
              <Database size={13} style={{ color: 'var(--amber)', flexShrink: 0 }} />
              <span style={s.dbName}>{db}</span>
            </button>
            {openDbs[db] && Object.entries(schemas).map(([schema, schemaObj]) => {
              const schKey = `${db}.${schema}`
              const isOpen = openTables[schKey]
              const isSel = selected === schKey
              return (
                <div key={schema}>
                  <button
                    style={{ ...s.tableRow, ...(isSel ? s.tableRowSel : {}) }}
                    onClick={() => { toggleTable(schKey); selectTable(schKey) }}
                  >
                    {isOpen ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
                    <Table2 size={12} style={{ color: 'var(--text-dim)', flexShrink: 0 }} />
                    <span style={s.tableName}>{schema}</span>
                  </button>
                  {isOpen && Object.entries(schemaObj.tables).map(([table, tableCols]) => {
                    const key = `${db}.${schema}.${table}`
                    const isTblSel = selected === key
                    return (
                      <div key={table}>
                        <button
                          style={{ ...s.colRowBtn, ...(isTblSel ? s.tableRowSel : {}) }}
                          onClick={() => selectTable(key)}
                        >
                          <Table2 size={11} style={{ color: 'var(--text-dim)', flexShrink: 0 }} />
                          <span style={s.tableName}>{table}</span>
                        </button>
                        {isTblSel && tableCols.map(col => (
                          <div key={col.name} style={s.colRow}>
                            {typeIcon(col.type)}
                            <span style={s.colName}>{col.name}</span>
                            <span style={s.colType}>{col.type}</span>
                          </div>
                        ))}
                      </div>
                    )
                  })}
                </div>
              )
            })}
          </div>
        ))}
      </div>

      {/* Detail */}
      <div style={s.detail}>
        {cols ? (
          <>
            <div style={s.detailHeader}>
              <span style={s.detailTitle}>{selected}</span>
              <span style={s.detailCount}>{cols.length} columns</span>
            </div>
            <table style={s.colTable}>
              <thead>
                <tr>
                  {['Column', 'Type'].map(h => (
                    <th key={h} style={s.th}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {cols.map((col, i) => (
                  <tr key={col.name} style={i % 2 === 0 ? {} : s.altRow}>
                    <td style={s.td}>
                      <div style={s.colNameCell}>
                        {typeIcon(col.type)}
                        <span style={s.colNameMain}>{col.name}</span>
                      </div>
                    </td>
                    <td style={{ ...s.td, fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-dim)' }}>
                      {col.type}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            {rows && (
              <>
                <div style={s.sampleHeader}>Sample rows</div>
                <div style={s.sampleWrap}>
                  <table style={s.sampleTable}>
                    <thead>
                      <tr>
                        {Object.keys(rows[0]).map(k => (
                          <th key={k} style={s.sampleTh}>{k}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((r, i) => (
                        <tr key={i} style={i % 2 === 0 ? {} : s.altRow}>
                          {Object.values(r).map((v, j) => (
                            <td key={j} style={s.sampleTd}>{String(v)}</td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </>
        ) : (
          <div style={s.empty}>
            <Database size={24} style={{ color: 'var(--text-dim)', marginBottom: 8 }} />
            <span style={s.emptyText}>Select a table to inspect its schema</span>
          </div>
        )}
      </div>
    </div>
  )
}

const s = {
  root: {
    flex: 1,
    display: 'flex',
    overflow: 'hidden',
  },
  tree: {
    width: 240,
    flexShrink: 0,
    borderRight: '1px solid var(--border-dim)',
    overflow: 'auto',
    background: 'var(--bg-surface)',
  },
  treeHeader: {
    padding: '10px 14px 6px',
    fontSize: 10,
    letterSpacing: '0.08em',
    textTransform: 'uppercase',
    color: 'var(--text-dim)',
    fontWeight: 500,
    borderBottom: '1px solid var(--border-dim)',
  },
  dbRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
    width: '100%',
    padding: '7px 14px',
    background: 'none',
    border: 'none',
    cursor: 'pointer',
    color: 'var(--text-secondary)',
    fontSize: 12,
    fontFamily: 'var(--font-ui)',
    textAlign: 'left',
  },
  dbName: {
    fontWeight: 500,
    color: 'var(--text-primary)',
  },
  tableRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 5,
    width: '100%',
    padding: '5px 14px 5px 28px',
    background: 'none',
    border: 'none',
    cursor: 'pointer',
    color: 'var(--text-secondary)',
    fontSize: 12,
    fontFamily: 'var(--font-ui)',
    textAlign: 'left',
  },
  colRowBtn: {
    display: 'flex',
    alignItems: 'center',
    gap: 5,
    width: '100%',
    padding: '4px 14px 4px 44px',
    background: 'none',
    border: 'none',
    cursor: 'pointer',
    color: 'var(--text-secondary)',
    fontSize: 12,
    fontFamily: 'var(--font-mono)',
    textAlign: 'left',
  },
  tableRowSel: {
    background: 'var(--amber-bg)',
    color: 'var(--text-primary)',
  },
  tableName: {},
  colRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
    padding: '3px 14px 3px 60px',
    fontSize: 11,
    fontFamily: 'var(--font-mono)',
    color: 'var(--text-dim)',
  },
  colName: {
    flex: 1,
    color: 'var(--text-secondary)',
  },
  colType: {
    color: 'var(--text-dim)',
    fontSize: 10,
  },
  sampleHeader: {
    padding: '12px 20px 6px',
    fontSize: 10,
    letterSpacing: '0.06em',
    textTransform: 'uppercase',
    color: 'var(--text-dim)',
    fontWeight: 500,
  },
  sampleWrap: {
    overflowX: 'auto',
    margin: '0 20px 16px',
    border: '1px solid var(--border-dim)',
    borderRadius: 'var(--radius)',
  },
  sampleTable: {
    width: '100%',
    borderCollapse: 'collapse',
    fontSize: 11.5,
    fontFamily: 'var(--font-mono)',
  },
  sampleTh: {
    padding: '6px 12px',
    textAlign: 'left',
    fontSize: 10,
    letterSpacing: '0.04em',
    textTransform: 'uppercase',
    color: 'var(--amber)',
    background: 'var(--bg-surface)',
    borderBottom: '1px solid var(--border-dim)',
    whiteSpace: 'nowrap',
  },
  sampleTd: {
    padding: '5px 12px',
    borderBottom: '1px solid var(--border-dim)',
    color: 'var(--text-mono)',
    whiteSpace: 'nowrap',
  },
  detail: {
    flex: 1,
    overflow: 'auto',
    display: 'flex',
    flexDirection: 'column',
  },
  detailHeader: {
    display: 'flex',
    alignItems: 'center',
    gap: 12,
    padding: '14px 20px',
    borderBottom: '1px solid var(--border-dim)',
    flexShrink: 0,
  },
  detailTitle: {
    fontFamily: 'var(--font-mono)',
    fontSize: 13,
    fontWeight: 600,
    color: 'var(--text-primary)',
  },
  detailCount: {
    fontSize: 11,
    fontFamily: 'var(--font-mono)',
    color: 'var(--text-dim)',
    padding: '2px 8px',
    background: 'var(--bg-raised)',
    border: '1px solid var(--border)',
    borderRadius: 100,
  },
  colTable: {
    width: '100%',
    borderCollapse: 'collapse',
    fontSize: 12,
  },
  th: {
    padding: '8px 20px',
    textAlign: 'left',
    fontSize: 10,
    letterSpacing: '0.06em',
    textTransform: 'uppercase',
    color: 'var(--text-dim)',
    fontWeight: 500,
    borderBottom: '1px solid var(--border)',
    background: 'var(--bg-surface)',
    position: 'sticky',
    top: 0,
  },
  td: {
    padding: '8px 20px',
    borderBottom: '1px solid var(--border-dim)',
    color: 'var(--text-secondary)',
  },
  colNameCell: {
    display: 'flex',
    alignItems: 'center',
    gap: 7,
  },
  colNameMain: {
    fontFamily: 'var(--font-mono)',
    fontSize: 12,
    color: 'var(--text-primary)',
  },
  altRow: {
    background: 'rgba(255,255,255,0.012)',
  },
  empty: {
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    color: 'var(--text-dim)',
  },
  emptyText: {
    fontSize: 12,
    color: 'var(--text-dim)',
  },
}
