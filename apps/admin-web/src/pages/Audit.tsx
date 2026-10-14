import { useEffect, useState } from 'react'
import { dateTime } from '@tochno/shared'
import { api } from '../auth'

interface A {
  id: number; tenant_id: number | null; user_id: number | null; action: string; entity: string
  entity_id: string; detail: unknown; created_at: string
}

export default function Audit() {
  const [rows, setRows] = useState<A[]>([])
  const [err, setErr] = useState('')
  useEffect(() => { api.get<A[]>('/api/admin/audit?limit=200').then(setRows).catch((e) => setErr(e.message)) }, [])
  return (
    <>
      <div className="page-head"><div><h1>Журнал дій</h1><div className="muted">Останні 200 подій по всіх клієнтах</div></div></div>
      {err && <div className="alert error">{err}</div>}
      <div className="card scroll-x" style={{ padding: 0 }}>
        <table className="t">
          <thead><tr><th>Час</th><th>Клієнт</th><th>Користувач</th><th>Дія</th><th>Об’єкт</th><th>Деталі</th></tr></thead>
          <tbody>{rows.map((r) => (
            <tr key={r.id}>
              <td className="muted">{dateTime(r.created_at)}</td><td>{r.tenant_id ?? '—'}</td><td>{r.user_id ?? '—'}</td>
              <td><span className="badge">{r.action}</span></td><td>{r.entity} {r.entity_id}</td>
              <td className="mono muted">{r.detail ? JSON.stringify(r.detail) : ''}</td>
            </tr>
          ))}</tbody>
        </table>
      </div>
    </>
  )
}
