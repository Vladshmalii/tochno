import { FormEvent, useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { dateTime } from '@tochno/shared'
import { api } from '../auth'

export interface TenantRow {
  id: number; name: string; status: string; plan: string; plan_name: string; modules: string[]; modules_override: string[] | null
  doc_limit: number; doc_limit_override: number | null; docs_used: number; users: number; tokens_in: number; tokens_out: number
  contact_email: string; notes: string; created_at: string; last_activity: string | null; trial_ends_at: string | null
}

export default function Tenants() {
  const nav = useNavigate()
  const [rows, setRows] = useState<TenantRow[]>([])
  const [q, setQ] = useState('')
  const [plans, setPlans] = useState<{ code: string; name: string }[]>([])
  const [show, setShow] = useState(false)
  const [f, setF] = useState({ name: '', plan: 'trial', owner_email: '', owner_name: '', owner_password: '' })
  const [err, setErr] = useState('')

  const load = useCallback(() => api.get<TenantRow[]>(`/api/admin/tenants?q=${encodeURIComponent(q)}`).then(setRows).catch((e) => setErr(e.message)), [q])
  useEffect(() => { const t = setTimeout(load, 250); return () => clearTimeout(t) }, [load])
  useEffect(() => { api.get<typeof plans>('/api/admin/plans').then(setPlans) }, [])

  async function create(e: FormEvent) {
    e.preventDefault(); setErr('')
    try { const t = await api.post<TenantRow>('/api/admin/tenants', f); nav(`/tenants/${t.id}`) } catch (x: any) { setErr(x.message) }
  }

  return (
    <>
      <div className="page-head">
        <div><h1>Клієнти</h1><div className="muted">Підключені компанії, тарифи та використання</div></div>
        <div className="row">
          <button className="btn" onClick={() => api.download('/api/admin/usage.csv', 'usage.csv')}>Звіт використання (CSV)</button>
          <button className="btn primary" onClick={() => setShow(!show)}>{show ? 'Скасувати' : '+ Новий клієнт'}</button>
        </div>
      </div>
      {err && <div className="alert error">{err}</div>}
      {show && (
        <form className="card row" style={{ marginBottom: 16, alignItems: 'flex-end' }} onSubmit={create}>
          <div style={{ flex: 2, minWidth: 180 }}><label className="f">Компанія</label><input required value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></div>
          <div style={{ width: 140 }}><label className="f">Тариф</label>
            <select value={f.plan} onChange={(e) => setF({ ...f, plan: e.target.value })}>{plans.map((p) => <option key={p.code} value={p.code}>{p.name}</option>)}</select></div>
          <div style={{ flex: 2, minWidth: 180 }}><label className="f">Email власника</label><input type="email" required value={f.owner_email} onChange={(e) => setF({ ...f, owner_email: e.target.value })} /></div>
          <div style={{ flex: 1, minWidth: 120 }}><label className="f">Ім’я</label><input value={f.owner_name} onChange={(e) => setF({ ...f, owner_name: e.target.value })} /></div>
          <div style={{ flex: 1, minWidth: 140 }}><label className="f">Пароль (≥8)</label><input type="password" required minLength={8} value={f.owner_password} onChange={(e) => setF({ ...f, owner_password: e.target.value })} /></div>
          <button className="btn primary">Створити</button>
        </form>
      )}
      <input style={{ maxWidth: 300, marginBottom: 12 }} placeholder="Пошук за назвою / email" value={q} onChange={(e) => setQ(e.target.value)} />
      <div className="card scroll-x" style={{ padding: 0 }}>
        {rows.length === 0 ? <div className="empty">Клієнтів ще немає</div> : (
          <table className="t">
            <thead><tr><th>Клієнт</th><th>Тариф</th><th>Модулі</th><th className="num">Документи (міс.)</th><th className="num">Користувачі</th><th>Остання активність</th><th>Статус</th></tr></thead>
            <tbody>
              {rows.map((t) => (
                <tr key={t.id} className="click" onClick={() => nav(`/tenants/${t.id}`)}>
                  <td><strong>{t.name}</strong><div className="muted">{t.contact_email}</div></td>
                  <td><span className="badge accent">{t.plan_name}</span></td>
                  <td>{t.modules.length}{t.modules_override && <span className="badge warn" style={{ marginLeft: 6 }}>custom</span>}</td>
                  <td className="num">{t.docs_used}{t.doc_limit ? ` / ${t.doc_limit}` : ' / ∞'}</td>
                  <td className="num">{t.users}</td>
                  <td className="muted">{dateTime(t.last_activity)}</td>
                  <td>{t.status === 'active' ? <span className="badge ok">Активний</span> : <span className="badge err">Призупинено</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  )
}
