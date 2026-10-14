import { useEffect, useState } from 'react'
import { api } from '../auth'

interface O {
  tenants: number; active: number; suspended: number; mrr: number; docs_month: number; failed_month: number
  tokens_in: number; tokens_out: number; by_plan: Record<string, number>
}

export default function Overview() {
  const [o, setO] = useState<O | null>(null)
  const [err, setErr] = useState('')
  const [jobs, setJobs] = useState<Record<string, number>>({})
  useEffect(() => {
    api.get<O>('/api/admin/overview').then(setO).catch((e) => setErr(e.message))
    api.get<{ jobs: Record<string, number> }>('/api/admin/health').then((h) => setJobs(h.jobs)).catch(() => {})
  }, [])
  if (err) return <div className="alert error">{err}</div>
  if (!o) return null
  const failRate = o.docs_month ? Math.round((o.failed_month / o.docs_month) * 100) : 0
  return (
    <>
      <div className="page-head"><div><h1>Огляд платформи</h1><div className="muted">Поточний місяць</div></div></div>
      <div className="grid cols-4" style={{ marginBottom: 16 }}>
        <div className="card stat"><div className="l">Клієнтів (активних)</div><div className="v">{o.active} <span className="muted" style={{ fontSize: 14 }}>/ {o.tenants}</span></div></div>
        <div className="card stat"><div className="l">MRR (за тарифами)</div><div className="v">${o.mrr}</div></div>
        <div className="card stat"><div className="l">Документів за місяць</div><div className="v">{o.docs_month}</div></div>
        <div className="card stat"><div className="l">Помилки обробки</div><div className="v">{o.failed_month} <span className="muted" style={{ fontSize: 14 }}>({failRate}%)</span></div></div>
      </div>
      <div className="grid cols-2">
        <div className="card"><h2>Черга обробки</h2>
          {['queued', 'running', 'failed'].map((k) => <div key={k} className="row" style={{ justifyContent: 'space-between' }}><span>{{ queued: 'В черзі', running: 'Виконується', failed: 'Збійні задачі' }[k]}</span><strong style={{ color: k === 'failed' && jobs[k] ? 'var(--err)' : undefined }}>{jobs[k] ?? 0}</strong></div>)}
        </div>
        <div className="card"><h2>Клієнти за тарифами</h2>
          {Object.entries(o.by_plan).map(([k, v]) => <div key={k} className="row" style={{ justifyContent: 'space-between' }}><span>{k}</span><strong>{v}</strong></div>)}
        </div>
        <div className="card"><h2>Витрата LLM-токенів</h2>
          <div className="row" style={{ justifyContent: 'space-between' }}><span>Вхідні</span><strong>{o.tokens_in.toLocaleString('uk-UA')}</strong></div>
          <div className="row" style={{ justifyContent: 'space-between' }}><span>Вихідні</span><strong>{o.tokens_out.toLocaleString('uk-UA')}</strong></div>
          <p className="muted">Основа для розрахунку собівартості на клієнта.</p>
        </div>
      </div>
    </>
  )
}
