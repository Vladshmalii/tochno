import { useEffect, useState } from 'react'
import { api } from '../auth'

interface P { id: number; code: string; name: string; price_month: number; doc_limit_month: number; modules: string[] }
interface M { code: string; name: string }

export default function Plans() {
  const [plans, setPlans] = useState<P[]>([])
  const [mods, setMods] = useState<M[]>([])
  const [err, setErr] = useState('')
  const [saved, setSaved] = useState<number | null>(null)
  useEffect(() => {
    api.get<P[]>('/api/admin/plans').then(setPlans).catch((e) => setErr(e.message))
    api.get<M[]>('/api/admin/modules').then(setMods)
  }, [])

  const upd = (id: number, patch: Partial<P>) => setPlans(plans.map((p) => (p.id === id ? { ...p, ...patch } : p)))
  const save = async (p: P) => {
    setErr('')
    try {
      await api.patch(`/api/admin/plans/${p.id}`, { name: p.name, price_month: p.price_month, doc_limit_month: p.doc_limit_month, modules: p.modules })
      setSaved(p.id); setTimeout(() => setSaved(null), 1500)
    } catch (x: any) { setErr(x.message) }
  }

  return (
    <>
      <div className="page-head"><div><h1>Тарифи та модулі</h1><div className="muted">Зміна тарифу впливає на всіх клієнтів без індивідуальних налаштувань</div></div></div>
      {err && <div className="alert error">{err}</div>}
      <div className="grid cols-2">
        {plans.map((p) => (
          <div className="card" key={p.id}>
            <div className="row" style={{ justifyContent: 'space-between' }}><h2 style={{ margin: 0 }}>{p.name}</h2><span className="badge">{p.code}</span></div>
            <div className="row" style={{ margin: '12px 0' }}>
              <div style={{ flex: 1 }}><label className="f">Ціна / міс, $</label><input type="number" min={0} value={p.price_month} onChange={(e) => upd(p.id, { price_month: Number(e.target.value) })} /></div>
              <div style={{ flex: 1 }}><label className="f">Документів / міс (0 = ∞)</label><input type="number" min={0} value={p.doc_limit_month} onChange={(e) => upd(p.id, { doc_limit_month: Number(e.target.value) })} /></div>
            </div>
            {mods.map((m) => (
              <label key={m.code} className="row" style={{ marginBottom: 6, cursor: 'pointer' }}>
                <input type="checkbox" style={{ width: 'auto' }} checked={p.modules.includes(m.code)}
                  onChange={() => upd(p.id, { modules: p.modules.includes(m.code) ? p.modules.filter((x) => x !== m.code) : [...p.modules, m.code] })} />
                {m.name}
              </label>
            ))}
            <div className="row" style={{ marginTop: 10 }}>
              <button className="btn primary" onClick={() => save(p)}>Зберегти</button>
              {saved === p.id && <span className="badge ok">Збережено</span>}
            </div>
          </div>
        ))}
      </div>
    </>
  )
}
