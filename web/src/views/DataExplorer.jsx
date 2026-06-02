import { useState } from 'react'
import { Database, Table2, ChevronRight, ChevronDown, Hash, Type, Calendar } from 'lucide-react'

const CATALOG = {
  prod: {
    orders:  [
      { name: 'id',         type: 'BIGINT' },
      { name: 'customer_id',type: 'BIGINT' },
      { name: 'total',      type: 'DECIMAL(18,2)' },
      { name: 'dt',         type: 'DATE' },
      { name: 'status',     type: 'VARCHAR' },
    ],
    users: [
      { name: 'id',    type: 'BIGINT' },
      { name: 'email', type: 'VARCHAR' },
      { name: 'name',  type: 'VARCHAR' },
      { name: 'created_at', type: 'TIMESTAMP' },
    ],
  },
  staging: {
    events: [
      { name: 'event_id',  type: 'VARCHAR' },
      { name: 'user_id',   type: 'BIGINT' },
      { name: 'event_type',type: 'VARCHAR' },
      { name: 'ts',        type: 'TIMESTAMP' },
    ],
  },
}

function typeIcon(type) {
  if (type.startsWith('BIGINT') || type.startsWith('DECIMAL') || type.startsWith('INT'))
    return <Hash size={11} style={{ color: 'var(--blue)' }} />
  if (type.startsWith('TIMESTAMP') || type.startsWith('DATE'))
    return <Calendar size={11} style={{ color: 'var(--purple)' }} />
  return <Type size={11} style={{ color: 'var(--green)' }} />
}

export function DataExplorer() {
  const [openDbs, setOpenDbs] = useState({ prod: true })
  const [openTables, setOpenTables] = useState({})
  const [selected, setSelected] = useState(null)

  const toggleDb = db => setOpenDbs(s => ({ ...s, [db]: !s[db] }))
  const toggleTable = key => setOpenTables(s => ({ ...s, [key]: !s[key] }))
  const selectTable = (db, table) => setSelected(`${db}.${table}`)

  const [selDb, selTable] = selected?.split('.') ?? []
  const cols = selDb && selTable ? CATALOG[selDb]?.[selTable] : null

  return (
    <div style={s.root}>
      {/* Tree */}
      <div style={s.tree}>
        <div style={s.treeHeader}>Catalog</div>
        {Object.entries(CATALOG).map(([db, tables]) => (
          <div key={db}>
            <button style={s.dbRow} onClick={() => toggleDb(db)}>
              {openDbs[db] ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
              <Database size={13} style={{ color: 'var(--amber)', flexShrink: 0 }} />
              <span style={s.dbName}>{db}</span>
            </button>
            {openDbs[db] && Object.keys(tables).map(table => {
              const key = `${db}.${table}`
              const isOpen = openTables[key]
              const isSel = selected === key
              return (
                <div key={table}>
                  <button
                    style={{ ...s.tableRow, ...(isSel ? s.tableRowSel : {}) }}
                    onClick={() => { toggleTable(key); selectTable(db, table) }}
                  >
                    {isOpen ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
                    <Table2 size={12} style={{ color: 'var(--text-dim)', flexShrink: 0 }} />
                    <span style={s.tableName}>{table}</span>
                  </button>
                  {isOpen && CATALOG[db][table].map(col => (
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
  tableRowSel: {
    background: 'var(--amber-bg)',
    color: 'var(--text-primary)',
  },
  tableName: {},
  colRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
    padding: '3px 14px 3px 46px',
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
