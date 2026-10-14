import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ModuleInfo } from '@tochno/shared'
import { api, useAuth } from '../auth'

const MODULE_ROUTE: Record<string, string> = {
  docs_extract: '/documents', reconcile: '/contractors', reports: '/reports', identity: '/identity',
  knowledge: '/knowledge',
}

interface Dash {
  review_total: number
  failed_total: number
  series: { date: string; count: number }[]
  attention: { id: number; module: string; filename: string; name: string; errors: number; flags: number }[]
}
interface Usage { plan: string; docs_used: number; docs_limit: number }

function Bars({ series }: { series: Dash['series'] }) {
  const max = Math.max(...series.map((s) => s.count), 1)
  return (
    <div role="img" aria-label="Документів за останні 14 днів" style={{ display: 'flex', alignItems: 'flex-end', gap: 4, height: 90 }}>
      {series.map((s) => (
        <div key={s.date} title={`${s.date}: ${s.count}`} style={{ flex: 1, minWidth: 4, height: `${Math.max((s.count / max) * 100, s.count ? 8 : 2)}%`, background: s.count ? 'var(--accent)' : 'var(--border)', borderRadius: 3 }} />
      ))}
    </div>
  )
}

export default function Dashboard() {
  const { me, has } = useAuth()
  const [dash, setDash] = useState<Dash | null>(null)
  const [usage, setUsage] = useState<Usage | null>(null)
  const [mods, setMods] = useState<ModuleInfo[]>([])

  useEffect(() => {
    api.get<ModuleInfo[]>('/api/modules').then(setMods).catch(() => {})
    api.get<Usage>('/api/usage').then(setUsage).catch(() => {})
    api.get<Dash>('/api/dashboard').then(setDash).catch(() => {})
  }, [])

  const pct = usage && usage.docs_limit ? Math.min(100, (usage.docs_used / usage.docs_limit) * 100) : 0
  const hasDocs = has('docs_extract') || has('identity') || has('reports')

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Вітаємо, {me?.full_name || me?.tenant_name}</h1>
          <div className="muted">Що потребує вашої уваги сьогодні</div>
        </div>
        {has('docs_extract') && <Link to="/documents" className="btn primary">Завантажити документи</Link>}
      </div>

      {hasDocs && dash && (
        <>
          <div className="grid cols-3" style={{ marginBottom: 16 }}>
            <div className="card stat"><div className="l">Очікують перевірки</div><div className="v">{dash.review_total}</div></div>
            <div className="card stat">
              <div className="l">Не розпізнано (помилка)</div>
              <div className="v" style={{ color: dash.failed_total ? 'var(--err)' : undefined }}>{dash.failed_total}</div>
            </div>
            {usage && (
              <div className="card stat">
                <div className="l">Документів у цьому місяці</div>
                <div className="v">{usage.docs_used}{usage.docs_limit ? ` / ${usage.docs_limit}` : ' / ∞'}</div>
                {usage.docs_limit > 0 && <div className={`bar${pct > 90 ? ' hot' : ''}`} style={{ marginTop: 8 }}><div style={{ width: `${pct}%` }} /></div>}
              </div>
            )}
          </div>

          <div className="grid cols-2" style={{ marginBottom: 24 }}>
            <div className="card">
              <h2>Потребують уваги</h2>
              {dash.attention.length === 0 ? <div className="muted">Усе перевірено 🎉</div> : dash.attention.map((a) => (
                <Link key={a.id} to={`/doc/${a.id}`} className="row" style={{ justifyContent: 'space-between', padding: '8px 0', borderBottom: '1px solid var(--border)', color: 'inherit' }}>
                  <span>{a.name || a.filename}<span className="muted"> · {a.filename}</span></span>
                  {a.errors > 0 ? <span className="badge err">{a.errors} крит.</span> : a.flags > 0 ? <span className="badge warn">{a.flags}</span> : <span className="badge ok">чисто</span>}
                </Link>
              ))}
            </div>
            <div className="card">
              <h2>Навантаження за 14 днів</h2>
              <Bars series={dash.series} />
              <div className="row muted" style={{ justifyContent: 'space-between', fontSize: 12, marginTop: 8 }}>
                <span>{dash.series[0]?.date.slice(5)}</span>
                <span>Усього: {dash.series.reduce((n, s) => n + s.count, 0)}</span>
                <span>сьогодні</span>
              </div>
            </div>
          </div>
        </>
      )}

      <h2>Модулі</h2>
      <div className="grid cols-3">
        {mods.map((m) => (
          <div key={m.code} className="card">
            <div className="row" style={{ justifyContent: 'space-between' }}>
              <strong>{m.name}</strong>
              {m.enabled ? <span className="badge ok">Підключено</span> : <span className="badge">Не підключено</span>}
            </div>
            <p className="muted">{m.description}</p>
            {m.enabled ? <Link to={MODULE_ROUTE[m.code] ?? '/'}>Відкрити →</Link> : <Link to={`/locked/${m.code}`}>Дізнатись більше →</Link>}
          </div>
        ))}
      </div>
    </>
  )
}
