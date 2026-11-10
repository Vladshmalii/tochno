import { FormEvent, useCallback, useEffect, useRef, useState } from 'react'
import { api, useAuth } from '../auth'

interface C { id: number; name: string; tax_id: string; iban: string }

export default function Contractors() {
  const { me } = useAuth()
  const canEdit = me?.role === 'owner' || me?.role === 'accountant'
  const [rows, setRows] = useState<C[]>([])
  const [q, setQ] = useState('')
  const [form, setForm] = useState({ name: '', tax_id: '', iban: '' })
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')
  const file = useRef<HTMLInputElement>(null)

  const load = useCallback(() => api.get<C[]>(`/api/contractors?q=${encodeURIComponent(q)}`).then(setRows).catch((e) => setErr(e.message)), [q])
  useEffect(() => { const t = setTimeout(load, 250); return () => clearTimeout(t) }, [load])

  async function add(e: FormEvent) {
    e.preventDefault(); setErr('')
    try { await api.post('/api/contractors', form); setForm({ name: '', tax_id: '', iban: '' }); load() } catch (x: any) { setErr(x.message) }
  }
  async function importCsv(f: File) {
    setErr(''); setMsg('')
    const fd = new FormData(); fd.append('file', f)
    try { const r = await api.upload<{ added: number; skipped: number }>('/api/contractors/import', fd); setMsg(`Додано: ${r.added}, пропущено дублікатів: ${r.skipped}`); load() } catch (x: any) { setErr(x.message) }
  }

  return (
    <>
      <div className="page-head">
        <div><h1>Контрагенти</h1><div className="muted">Довідник для автозвірки: збіг за ЄДРПОУ/ІПН, контроль зміни IBAN</div></div>
        {canEdit && <>
          <button className="btn" onClick={() => file.current?.click()}>Імпорт CSV</button>
          <input ref={file} type="file" hidden accept=".csv,.txt" onChange={(e) => { if (e.target.files?.[0]) importCsv(e.target.files[0]); e.target.value = '' }} />
        </>}
      </div>
      {err && <div className="alert error">{err}</div>}
      {msg && <div className="alert info">{msg}</div>}

      {canEdit && (
        <form className="card row" style={{ marginBottom: 16, alignItems: 'flex-end' }} onSubmit={add}>
          <div style={{ flex: 2, minWidth: 200 }}><label className="f">Назва</label><input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></div>
          <div style={{ flex: 1, minWidth: 120 }}><label className="f">ЄДРПОУ / ІПН</label><input value={form.tax_id} onChange={(e) => setForm({ ...form, tax_id: e.target.value })} /></div>
          <div style={{ flex: 2, minWidth: 200 }}><label className="f">IBAN</label><input value={form.iban} onChange={(e) => setForm({ ...form, iban: e.target.value })} /></div>
          <button className="btn primary">Додати</button>
        </form>
      )}

      <input style={{ maxWidth: 300, marginBottom: 12 }} placeholder="Пошук" value={q} onChange={(e) => setQ(e.target.value)} />
      <div className="card scroll-x" style={{ padding: 0 }}>
        {rows.length === 0 ? <div className="empty">Довідник порожній. Додайте контрагентів або імпортуйте CSV (колонки «Назва», «ЄДРПОУ», «IBAN»).</div> : (
          <table className="t">
            <thead><tr><th>Назва</th><th>ЄДРПОУ / ІПН</th><th>IBAN</th><th /></tr></thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.id}>
                  <td>{c.name}</td><td className="mono">{c.tax_id || '—'}</td><td className="mono">{c.iban || '—'}</td>
                  <td className="num">{canEdit && <button className="btn sm danger" onClick={() => { if (window.confirm(`Видалити «${c.name}»?`)) api.del(`/api/contractors/${c.id}`).then(load) }}>Видалити</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  )
}
