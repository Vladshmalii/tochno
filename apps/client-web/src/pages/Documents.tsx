import { DragEvent, useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { DocRow, DocStatus, money, dateTime, STATUS_LABEL } from '@tochno/shared'
import { api, useAuth } from '../auth'

interface Page { total: number; items: DocRow[] }
interface TypeInfo { code: string; name: string }

const TONE: Record<DocStatus, string> = {
  queued: '', processing: 'accent', review: 'warn', approved: 'ok', rejected: '', failed: 'err',
}

export interface ModuleView {
  module: string
  title: string
  subtitle: string
  name: string            // назва колонки «суб’єкт»
  number: string          // назва колонки «номер/період»
  amount: string | null   // назва колонки суми (null — не показувати)
  search: string
}

export const VIEWS: Record<string, ModuleView> = {
  docs_extract: {
    module: 'docs_extract', title: 'Документи', subtitle: 'Завантажте рахунки, акти чи накладні — AI витягне дані для перевірки',
    name: 'Постачальник', number: '№', amount: 'Сума', search: 'Пошук: файл, постачальник, номер, ЄДРПОУ',
  },
  identity: {
    module: 'identity', title: 'Кадри: документи особи', subtitle: 'Паспорт, ID-картка, довідка ІПН — розпізнавання з перевіркою ІПН і MRZ',
    name: 'Особа', number: 'Номер документа', amount: null, search: 'Пошук: ПІБ, ІПН, номер',
  },
  reports: {
    module: 'reports', title: 'Бухгалтерські звіти', subtitle: 'Банківські виписки, баланс, звіт про фінансові результати — з розрахунком показників',
    name: 'Підприємство / власник', number: 'Період / дата', amount: 'Ключова сума', search: 'Пошук: компанія, файл',
  },
}

export default function Documents({ view }: { view: ModuleView }) {
  const nav = useNavigate()
  const { me } = useAuth()
  const canUpload = me?.role === 'owner' || me?.role === 'accountant'
  const [types, setTypes] = useState<TypeInfo[]>([])
  const [docType, setDocType] = useState('')
  const [status, setStatus] = useState('')
  const [q, setQ] = useState('')
  const [page, setPage] = useState<Page>({ total: 0, items: [] })
  const [over, setOver] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [sel, setSel] = useState<Set<number>>(new Set())
  const [msg, setMsg] = useState('')
  const input = useRef<HTMLInputElement>(null)

  const load = useCallback(() =>
    api.get<Page>(`/api/docs?module=${view.module}&page_size=50&status=${status}&q=${encodeURIComponent(q)}`)
      .then(setPage).catch((e) => setErr(e.message)),
  [view.module, status, q])

  useEffect(() => {
    api.get<TypeInfo[]>(`/api/docs/types?module=${view.module}`).then((t) => { setTypes(t); setDocType(t[0]?.code ?? '') }).catch(() => {})
  }, [view.module])
  useEffect(() => { const t = setTimeout(load, 250); return () => clearTimeout(t) }, [load])

  const pending = page.items.some((d) => d.status === 'queued' || d.status === 'processing')
  useEffect(() => {
    if (!pending) return
    const t = setInterval(load, 2000)
    return () => clearInterval(t)
  }, [pending, load])

  const toggle = (id: number) => setSel((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n })
  const reviewable = page.items.filter((d) => d.status === 'review')
  const allSel = reviewable.length > 0 && reviewable.every((d) => sel.has(d.id))

  async function bulkApprove() {
    setErr(''); setMsg('')
    try {
      const r = await api.post<{ approved: number[]; skipped: { id: number; reason: string }[] }>('/api/docs/bulk-approve', { ids: Array.from(sel) })
      setMsg(`Затверджено: ${r.approved.length}${r.skipped.length ? `, пропущено: ${r.skipped.length} (є критичні попередження — перевірте вручну)` : ''}`)
      setSel(new Set()); await load()
    } catch (e: any) { setErr(e.message) }
  }

  async function upload(files: FileList | File[]) {
    if (!files.length || !docType) return
    setBusy(true); setErr('')
    const form = new FormData()
    Array.from(files).forEach((f) => form.append('files', f))
    form.append('doc_type', docType)
    try { await api.upload('/api/docs', form); await load() } catch (e: any) { setErr(e.message) } finally { setBusy(false) }
  }
  const onDrop = (e: DragEvent) => { e.preventDefault(); setOver(false); if (canUpload) upload(e.dataTransfer.files) }

  return (
    <>
      <div className="page-head">
        <div><h1>{view.title}</h1><div className="muted">{view.subtitle}</div></div>
        <div className="row">
          <button className="btn" onClick={() => api.download(`/api/docs/export.xlsx?module=${view.module}`, `${view.module}.xlsx`)}>Експорт Excel</button>
          <button className="btn" onClick={() => api.download(`/api/docs/export.csv?module=${view.module}`, `${view.module}.csv`)}>CSV</button>
        </div>
      </div>

      {err && <div className="alert error">{err}</div>}
      {msg && <div className="alert info">{msg}</div>}

      {canUpload && (
        <div className="card" style={{ marginBottom: 16 }}>
          <div className="row" style={{ marginBottom: 12 }}>
            <label className="f" style={{ margin: 0 }}>Тип документа</label>
            <select style={{ width: 260 }} value={docType} onChange={(e) => setDocType(e.target.value)}>
              {types.map((t) => <option key={t.code} value={t.code}>{t.name}</option>)}
            </select>
          </div>
          <div className={`drop${over ? ' over' : ''}`} role="button" tabIndex={0}
            onClick={() => input.current?.click()} onKeyDown={(e) => e.key === 'Enter' && input.current?.click()}
            onDragOver={(e) => { e.preventDefault(); setOver(true) }} onDragLeave={() => setOver(false)} onDrop={onDrop}>
            {busy ? 'Завантаження…' : 'Перетягніть файли сюди або натисніть для вибору (PDF, зображення, Word, Excel)'}
          </div>
          <input ref={input} type="file" multiple hidden accept=".pdf,.png,.jpg,.jpeg,.webp,.docx,.doc,.xlsx,.xls,.txt,.csv"
            onChange={(e) => { if (e.target.files) upload(e.target.files); e.target.value = '' }} />
        </div>
      )}

      <div className="row" style={{ marginBottom: 12 }}>
        <input style={{ maxWidth: 320 }} placeholder={view.search} value={q} onChange={(e) => setQ(e.target.value)} />
        <select style={{ width: 180 }} value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">Усі статуси</option>
          {Object.entries(STATUS_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <span className="muted">{page.total} шт.</span>
        {canUpload && sel.size > 0 && <button className="btn primary" onClick={bulkApprove}>Затвердити вибрані ({sel.size})</button>}
      </div>

      <div className="card scroll-x" style={{ padding: 0 }}>
        {page.items.length === 0 ? <div className="empty">Документів поки немає</div> : (
          <table className="t">
            <thead><tr>
              <th style={{ width: 32 }}>{canUpload && <input type="checkbox" style={{ width: 'auto' }} aria-label="Вибрати всі на перевірці" checked={allSel}
                onChange={() => setSel(allSel ? new Set() : new Set(reviewable.map((d) => d.id)))} />}</th>
              <th>Файл</th><th>{view.name}</th><th>{view.number}</th>{view.amount && <th className="num">{view.amount}</th>}
              <th>Статус</th><th>Попередження</th><th>Додано</th>
            </tr></thead>
            <tbody>
              {page.items.map((d) => (
                <tr key={d.id} className="click" onClick={() => nav(`/doc/${d.id}`)}>
                  <td onClick={(e) => e.stopPropagation()}>{canUpload && d.status === 'review' &&
                    <input type="checkbox" style={{ width: 'auto' }} aria-label={`Вибрати ${d.filename}`} checked={sel.has(d.id)} onChange={() => toggle(d.id)} />}</td>
                  <td>{d.filename}</td>
                  <td>{d.supplier_name || <span className="muted">—</span>}</td>
                  <td>{d.doc_number || '—'}</td>
                  {view.amount && <td className="num">{d.amount ? money(d.amount, d.currency) : '—'}</td>}
                  <td><span className={`badge ${TONE[d.status]}`}>{STATUS_LABEL[d.status]}</span></td>
                  <td>
                    {d.error_count > 0 ? <span className="badge err">{d.error_count} крит.</span>
                      : d.flag_count > 0 ? <span className="badge warn">{d.flag_count}</span> : <span className="muted">—</span>}
                  </td>
                  <td className="muted">{dateTime(d.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  )
}
