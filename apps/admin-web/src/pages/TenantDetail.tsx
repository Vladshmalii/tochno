import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { dateTime } from '@tochno/shared'
import { api } from '../auth'
import type { TenantRow } from './Tenants'

interface Mod { code: string; name: string; description: string; ready: boolean }
interface U { id: number; email: string; full_name: string; role: string; is_active: boolean; last_login_at: string | null }

export default function TenantDetail() {
  const { id } = useParams()
  const [t, setT] = useState<TenantRow | null>(null)
  const [mods, setMods] = useState<Mod[]>([])
  const [plans, setPlans] = useState<{ code: string; name: string }[]>([])
  const [users, setUsers] = useState<U[]>([])
  const [sel, setSel] = useState<string[]>([])
  const [limit, setLimit] = useState('')
  const [notes, setNotes] = useState('')
  const [err, setErr] = useState('')
  const [saved, setSaved] = useState(false)

  const apply = (row: TenantRow) => {
    setT(row); setSel(row.modules); setLimit(row.doc_limit_override === null ? '' : String(row.doc_limit_override)); setNotes(row.notes)
  }
  const load = useCallback(async () => {
    const list = await api.get<TenantRow[]>('/api/admin/tenants')
    const row = list.find((x) => String(x.id) === id)
    if (row) apply(row)
    setUsers(await api.get<U[]>(`/api/admin/tenants/${id}/users`))
  }, [id])
  useEffect(() => {
    load().catch((e) => setErr(e.message))
    api.get<Mod[]>('/api/admin/modules').then(setMods)
    api.get<typeof plans>('/api/admin/plans').then(setPlans)
  }, [load])

  const patch = async (body: object) => {
    setErr('')
    try {
      apply(await api.patch<TenantRow>(`/api/admin/tenants/${id}`, body))
      setSaved(true); setTimeout(() => setSaved(false), 1500)
    } catch (x: any) { setErr(x.message) }
  }

  if (!t) return err ? <div className="alert error">{err}</div> : null
  const toggle = (c: string) => setSel(sel.includes(c) ? sel.filter((x) => x !== c) : [...sel, c])
  const tokens = t.tokens_in + t.tokens_out

  return (
    <>
      <div className="page-head">
        <div>
          <Link to="/tenants">← Клієнти</Link>
          <h1>{t.name}</h1>
          <span className="muted">Створено {dateTime(t.created_at)} · {t.contact_email}</span>
        </div>
        <div className="row">
          {saved && <span className="badge ok">Збережено</span>}
          <button className="btn" onClick={async () => {
            try {
              const r = await api.post<{ access_token: string; expires_minutes: number }>(`/api/admin/tenants/${id}/impersonate`)
              const base = (import.meta as any).env?.VITE_CLIENT_URL ?? 'http://localhost:5173'
              window.open(`${base}/#imp=${encodeURIComponent(r.access_token)}`, '_blank', 'noopener')
            } catch (x: any) { setErr(x.message) }
          }}>Увійти як клієнт</button>
          {t.status === 'active'
            ? <button className="btn danger" onClick={() => { if (window.confirm('Призупинити доступ клієнта?')) patch({ status: 'suspended' }) }}>Призупинити</button>
            : <button className="btn primary" onClick={() => patch({ status: 'active' })}>Відновити доступ</button>}
        </div>
      </div>
      {err && <div className="alert error">{err}</div>}

      <div className="grid cols-4" style={{ marginBottom: 16 }}>
        <div className="card stat"><div className="l">Документи (міс.)</div><div className="v">{t.docs_used}{t.doc_limit ? ` / ${t.doc_limit}` : ''}</div></div>
        <div className="card stat"><div className="l">Користувачі</div><div className="v">{t.users}</div></div>
        <div className="card stat"><div className="l">LLM-токени (міс.)</div><div className="v">{tokens.toLocaleString('uk-UA')}</div></div>
        <div className="card stat"><div className="l">Остання активність</div><div className="v" style={{ fontSize: 16 }}>{dateTime(t.last_activity)}</div></div>
      </div>

      <div className="grid cols-2">
        <div className="card">
          <h2>Тариф і модулі</h2>
          <div className="field"><label className="f">Тариф</label>
            <select value={t.plan} onChange={(e) => patch({ plan: e.target.value })}>{plans.map((p) => <option key={p.code} value={p.code}>{p.name}</option>)}</select></div>
          <label className="f">Підключені модулі {t.modules_override && <span className="badge warn">індивідуально</span>}</label>
          {mods.map((m) => (
            <label key={m.code} className="row" style={{ marginBottom: 8, alignItems: 'flex-start', cursor: 'pointer' }}>
              <input type="checkbox" style={{ width: 'auto', marginTop: 4 }} checked={sel.includes(m.code)} onChange={() => toggle(m.code)} />
              <span><strong>{m.name}</strong> {!m.ready && <span className="badge warn">скоро</span>}<br /><span className="muted">{m.description}</span></span>
            </label>
          ))}
          <div className="row">
            <button className="btn primary" onClick={() => patch({ modules_override: sel })}>Зберегти модулі</button>
            {t.modules_override && <button className="btn" onClick={() => patch({ clear_modules_override: true })}>Скинути до тарифу</button>}
          </div>
        </div>

        <div>
          {t.plan === 'trial' && (
            <div className="card" style={{ marginBottom: 16 }}>
              <h2>Пробний період</h2>
              <p className="muted">{t.trial_ends_at ? `Закінчується ${dateTime(t.trial_ends_at)}` : 'Без обмеження'}</p>
              <div className="row">
                <button className="btn" onClick={() => patch({ extend_trial_days: 7 })}>+7 днів</button>
                <button className="btn" onClick={() => patch({ extend_trial_days: 30 })}>+30 днів</button>
              </div>
            </div>
          )}
          <div className="card" style={{ marginBottom: 16 }}>
            <h2>Ліміт документів</h2>
            <div className="row">
              <input style={{ width: 120 }} type="number" min={0} placeholder="за тарифом" value={limit} onChange={(e) => setLimit(e.target.value)} />
              <button className="btn" onClick={() => patch(limit === '' ? { clear_doc_limit_override: true } : { doc_limit_override: Number(limit) })}>Зберегти</button>
            </div>
            <p className="muted">Порожньо — діє ліміт тарифу. 0 — без обмежень.</p>
          </div>
          <div className="card">
            <h2>Нотатки менеджера</h2>
            <textarea rows={4} value={notes} onChange={(e) => setNotes(e.target.value)} />
            <button className="btn" style={{ marginTop: 8 }} onClick={() => patch({ notes })}>Зберегти</button>
          </div>
        </div>
      </div>

      <h2 style={{ marginTop: 24 }}>Користувачі</h2>
      <div className="card scroll-x" style={{ padding: 0 }}>
        <table className="t">
          <thead><tr><th>Email</th><th>Ім’я</th><th>Роль</th><th>Останній вхід</th><th>Статус</th><th /></tr></thead>
          <tbody>{users.map((u) => (
            <tr key={u.id}><td>{u.email}</td><td>{u.full_name}</td><td>{u.role}</td><td className="muted">{dateTime(u.last_login_at)}</td>
              <td>{u.is_active ? <span className="badge ok">Активний</span> : <span className="badge">Вимкнено</span>}</td>
              <td className="num">
                <button className="btn sm" onClick={async () => {
                  const pw = window.prompt(`Новий пароль для ${u.email} (мін. 8 символів):`)
                  if (!pw) return
                  try { await api.post(`/api/admin/users/${u.id}/reset-password`, { new_password: pw }); setSaved(true); setTimeout(() => setSaved(false), 1500) } catch (x: any) { setErr(x.message) }
                }}>Скинути пароль</button>{' '}
                <button className="btn sm" onClick={() => api.patch(`/api/admin/users/${u.id}?active=${!u.is_active}`).then(load).catch((x) => setErr(x.message))}>{u.is_active ? 'Вимкнути' : 'Увімкнути'}</button>
              </td></tr>
          ))}</tbody>
        </table>
      </div>
    </>
  )
}
