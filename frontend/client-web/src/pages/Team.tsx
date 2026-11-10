import { FormEvent, useCallback, useEffect, useState } from 'react'
import { dateTime } from '@tochno/shared'
import { api, useAuth } from '../auth'

interface U { id: number; email: string; full_name: string; role: string; is_active: boolean; last_login_at: string | null }
const ROLE: Record<string, string> = { owner: 'Власник', accountant: 'Бухгалтер', viewer: 'Перегляд' }

export default function Team() {
  const { me } = useAuth()
  const isOwner = me?.role === 'owner'
  const [users, setUsers] = useState<U[]>([])
  const [f, setF] = useState({ email: '', full_name: '', role: 'accountant', password: '' })
  const [err, setErr] = useState('')

  const load = useCallback(() => api.get<U[]>('/api/team').then(setUsers).catch((e) => setErr(e.message)), [])
  useEffect(() => { load() }, [load])

  async function add(e: FormEvent) {
    e.preventDefault(); setErr('')
    try { await api.post('/api/team', f); setF({ email: '', full_name: '', role: 'accountant', password: '' }); load() } catch (x: any) { setErr(x.message) }
  }

  return (
    <>
      <div className="page-head"><div><h1>Команда</h1><div className="muted">Користувачі вашої компанії та їхні ролі</div></div></div>
      {err && <div className="alert error">{err}</div>}
      {isOwner && (
        <form className="card row" style={{ marginBottom: 16, alignItems: 'flex-end' }} onSubmit={add}>
          <div style={{ flex: 1, minWidth: 180 }}><label className="f">Email</label><input type="email" required value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></div>
          <div style={{ flex: 1, minWidth: 140 }}><label className="f">Ім’я</label><input value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} /></div>
          <div style={{ width: 140 }}><label className="f">Роль</label>
            <select value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })}>
              {Object.entries(ROLE).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select></div>
          <div style={{ flex: 1, minWidth: 140 }}><label className="f">Тимчасовий пароль</label><input type="password" required minLength={8} value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} /></div>
          <button className="btn primary">Додати</button>
        </form>
      )}
      <div className="card scroll-x" style={{ padding: 0 }}>
        <table className="t">
          <thead><tr><th>Користувач</th><th>Роль</th><th>Останній вхід</th><th>Статус</th><th /></tr></thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id}>
                <td><strong>{u.full_name || u.email}</strong><div className="muted">{u.email}</div></td>
                <td>{ROLE[u.role] ?? u.role}</td>
                <td className="muted">{dateTime(u.last_login_at)}</td>
                <td>{u.is_active ? <span className="badge ok">Активний</span> : <span className="badge">Вимкнено</span>}</td>
                <td className="num">{isOwner && u.id !== me?.id && <button className="btn sm" onClick={() => api.patch(`/api/team/${u.id}?active=${!u.is_active}`).then(load)}>{u.is_active ? 'Вимкнути' : 'Увімкнути'}</button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}
