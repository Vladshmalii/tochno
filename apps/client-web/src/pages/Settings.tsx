import { FormEvent, useCallback, useEffect, useState } from 'react'
import { dateTime } from '@tochno/shared'
import { api, useAuth } from '../auth'

interface Integrations {
  intake_token: string | null
  api_keys: { id: number; name: string; prefix: string; read_only: boolean; last_used_at: string | null; created_at: string }[]
  webhooks: { id: number; url: string; events: string[]; active: boolean; last_status: string }[]
  events: string[]
}

function Password() {
  const [f, setF] = useState({ current_password: '', new_password: '' })
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')
  async function submit(e: FormEvent) {
    e.preventDefault(); setMsg(''); setErr('')
    try { await api.post('/api/auth/change-password', f); setMsg('Пароль змінено'); setF({ current_password: '', new_password: '' }) } catch (x: any) { setErr(x.message) }
  }
  return (
    <form className="card" style={{ maxWidth: 420 }} onSubmit={submit}>
      <h2>Зміна пароля</h2>
      {msg && <div className="alert info">{msg}</div>}{err && <div className="alert error">{err}</div>}
      <div className="field"><label className="f">Поточний пароль</label><input type="password" autoComplete="current-password" required value={f.current_password} onChange={(e) => setF({ ...f, current_password: e.target.value })} /></div>
      <div className="field"><label className="f">Новий пароль (≥ 8 символів)</label><input type="password" autoComplete="new-password" minLength={8} required value={f.new_password} onChange={(e) => setF({ ...f, new_password: e.target.value })} /></div>
      <button className="btn primary">Змінити</button>
    </form>
  )
}

function Integrate() {
  const [d, setD] = useState<Integrations | null>(null)
  const [err, setErr] = useState('')
  const [newKey, setNewKey] = useState('')
  const [secret, setSecret] = useState('')
  const [k, setK] = useState({ name: '', read_only: false })
  const [url, setUrl] = useState('')
  const load = useCallback(() => api.get<Integrations>('/api/integrations').then(setD).catch((e) => setErr(e.message)), [])
  useEffect(() => { load() }, [load])
  if (!d) return err ? <div className="alert error">{err}</div> : null

  const intakeUrl = d.intake_token ? `${api.base}/api/intake/${d.intake_token}?doc_type=invoice` : ''
  const wrap = (fn: () => Promise<unknown>) => async () => { setErr(''); try { await fn(); await load() } catch (x: any) { setErr(x.message) } }

  return (
    <>
      {err && <div className="alert error">{err}</div>}
      <div className="card" style={{ marginBottom: 16 }}>
        <h2>Приймання документів (intake)</h2>
        <p className="muted">Надсилайте файли POST-запитом multipart (поле <code>files</code>) з пошти, Zapier, Make чи робота Bitrix24 — без логіну. Адреса — секрет, не публікуйте її.</p>
        <input readOnly value={intakeUrl} onFocus={(e) => e.target.select()} className="mono" />
        <button className="btn sm" style={{ marginTop: 8 }} onClick={wrap(async () => { if (window.confirm('Стара адреса перестане працювати. Продовжити?')) await api.post('/api/integrations/intake/rotate') })}>Згенерувати нову адресу</button>
      </div>

      <div className="card" style={{ marginBottom: 16 }}>
        <h2>API-ключі</h2>
        <p className="muted">Заголовок <code>X-API-Key</code>. Ключ діє від імені власника акаунта.</p>
        {newKey && <div className="alert info">Збережіть ключ зараз — він більше не показується:<br /><span className="mono">{newKey}</span></div>}
        <form className="row" style={{ marginBottom: 12 }} onSubmit={(e) => { e.preventDefault(); wrap(async () => { const r = await api.post<{ key: string }>('/api/integrations/api-keys', k); setNewKey(r.key); setK({ name: '', read_only: false }) })() }}>
          <input style={{ maxWidth: 240 }} required placeholder="Назва (напр. 1С)" value={k.name} onChange={(e) => setK({ ...k, name: e.target.value })} />
          <label className="row"><input type="checkbox" style={{ width: 'auto' }} checked={k.read_only} onChange={(e) => setK({ ...k, read_only: e.target.checked })} />лише читання</label>
          <button className="btn primary">Створити ключ</button>
        </form>
        {d.api_keys.length > 0 && (
          <table className="t"><thead><tr><th>Назва</th><th>Префікс</th><th>Режим</th><th>Остання активність</th><th /></tr></thead>
            <tbody>{d.api_keys.map((x) => (
              <tr key={x.id}><td>{x.name}</td><td className="mono">{x.prefix}…</td><td>{x.read_only ? 'читання' : 'повний'}</td><td className="muted">{dateTime(x.last_used_at)}</td>
                <td className="num"><button className="btn sm danger" onClick={wrap(async () => { if (window.confirm('Відкликати ключ?')) await api.del(`/api/integrations/api-keys/${x.id}`) })}>Відкликати</button></td></tr>
            ))}</tbody></table>
        )}
      </div>

      <div className="card">
        <h2>Вебхуки</h2>
        <p className="muted">Сповіщення про події ({d.events.join(', ')}). Кожен запит підписано HMAC SHA-256 у заголовку <code>X-Tochno-Signature</code>.</p>
        {secret && <div className="alert info">Секрет підпису (показується один раз): <span className="mono">{secret}</span></div>}
        <form className="row" style={{ marginBottom: 12 }} onSubmit={(e) => { e.preventDefault(); wrap(async () => { const r = await api.post<{ secret: string }>('/api/integrations/webhooks', { url }); setSecret(r.secret); setUrl('') })() }}>
          <input style={{ maxWidth: 420 }} type="url" required placeholder="https://example.com/hook" value={url} onChange={(e) => setUrl(e.target.value)} />
          <button className="btn primary">Додати</button>
        </form>
        {d.webhooks.length > 0 && (
          <table className="t"><thead><tr><th>URL</th><th>Статус</th><th>Остання доставка</th><th /></tr></thead>
            <tbody>{d.webhooks.map((h) => (
              <tr key={h.id}><td className="mono">{h.url}</td><td>{h.active ? <span className="badge ok">активний</span> : <span className="badge">вимкнено</span>}</td><td className="muted">{h.last_status || '—'}</td>
                <td className="num">
                  <button className="btn sm" onClick={wrap(() => api.patch(`/api/integrations/webhooks/${h.id}?active=${!h.active}`))}>{h.active ? 'Вимкнути' : 'Увімкнути'}</button>{' '}
                  <button className="btn sm danger" onClick={wrap(async () => { if (window.confirm('Видалити вебхук?')) await api.del(`/api/integrations/webhooks/${h.id}`) })}>Видалити</button>
                </td></tr>
            ))}</tbody></table>
        )}
      </div>
    </>
  )
}

interface TenantSettings { auto_approve_clean: boolean; telegram: { connected: boolean; bot_username: string; pair_code: string; chats: number } }

function Automation() {
  const [st, setSt] = useState<TenantSettings | null>(null)
  const [token, setToken] = useState('')
  const [err, setErr] = useState('')
  const load = useCallback(() => api.get<TenantSettings>('/api/settings').then(setSt).catch((e) => setErr(e.message)), [])
  useEffect(() => { load() }, [load])
  if (!st) return err ? <div className="alert error">{err}</div> : null
  const run = (fn: () => Promise<unknown>) => async () => { setErr(''); try { await fn(); await load() } catch (x: any) { setErr(x.message) } }

  return (
    <div className="grid cols-2" style={{ marginBottom: 16 }}>
      {err && <div className="alert error" style={{ gridColumn: '1 / -1' }}>{err}</div>}
      <div className="card">
        <h2>Автоматизація</h2>
        <label className="row" style={{ alignItems: 'flex-start', cursor: 'pointer' }}>
          <input type="checkbox" style={{ width: 'auto', marginTop: 4 }} checked={st.auto_approve_clean}
            onChange={run(() => api.put('/api/settings', { auto_approve_clean: !st.auto_approve_clean }))} />
          <span><strong>Авто-затвердження «чистих» документів</strong><br />
            <span className="muted">Документ без жодного попередження та з високою впевненістю розпізнавання одразу стає затвердженим. Усе інше, як і раніше, іде на перевірку людині. Кожне авто-затвердження фіксується в журналі.</span></span>
        </label>
      </div>
      <div className="card">
        <h2>Telegram-бот</h2>
        {st.telegram.connected ? (
          <>
            <p>Бот <strong>@{st.telegram.bot_username}</strong> підключено. Підключених чатів: {st.telegram.chats}.</p>
            <p className="muted">Щоб прив’язати чат, надішліть боту: <code>/bind {st.telegram.pair_code}</code>. Далі просто пересилайте йому рахунки — вони з’являться в «Документах».</p>
            <button className="btn danger sm" onClick={run(async () => { if (window.confirm('Відключити бота?')) await api.del('/api/settings/telegram') })}>Відключити</button>
          </>
        ) : (
          <>
            <p className="muted">Створіть бота в @BotFather, вставте його токен — і бухгалтери зможуть пересилати документи з телефона.</p>
            <form className="row" onSubmit={(e) => { e.preventDefault(); run(async () => { await api.put('/api/settings/telegram', { bot_token: token }); setToken('') })() }}>
              <input type="password" autoComplete="off" required minLength={20} placeholder="Токен бота" value={token} onChange={(e) => setToken(e.target.value)} />
              <button className="btn primary">Підключити</button>
            </form>
          </>
        )}
      </div>
    </div>
  )
}

interface AuditRow { id: number; action: string; entity: string; entity_id: string; user_id: number | null; created_at: string }

function AuditLog() {
  const [rows, setRows] = useState<AuditRow[]>([])
  useEffect(() => { api.get<AuditRow[]>('/api/audit?limit=100').then(setRows).catch(() => {}) }, [])
  return (
    <div className="card scroll-x" style={{ padding: 0, marginTop: 16 }}>
      <h2 style={{ padding: '16px 16px 0' }}>Журнал дій</h2>
      <table className="t">
        <thead><tr><th>Час</th><th>Дія</th><th>Об’єкт</th></tr></thead>
        <tbody>{rows.map((r) => <tr key={r.id}><td className="muted">{dateTime(r.created_at)}</td><td><span className="badge">{r.action}</span></td><td>{r.entity} {r.entity_id}</td></tr>)}</tbody>
      </table>
    </div>
  )
}

export default function Settings() {
  const { me } = useAuth()
  return (
    <>
      <div className="page-head"><div><h1>Налаштування</h1><div className="muted">{me?.email}</div></div></div>
      <div style={{ marginBottom: 16 }}><Password /></div>
      {me?.role === 'owner' ? <><Automation /><Integrate /><AuditLog /></> : <div className="muted">Інтеграції та автоматизація доступні власнику акаунта.</div>}
    </>
  )
}
