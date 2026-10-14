import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ApiError, DocFull, Extracted, Flag, MODULE_PATH, STATUS_LABEL } from '@tochno/shared'
import { api, useAuth } from '../auth'
import ReportView from './ReportView'

export default function DocumentReview() {
  const { id } = useParams()
  const nav = useNavigate()
  const { me } = useAuth()
  const canEdit = me?.role === 'owner' || me?.role === 'accountant'
  const [doc, setDoc] = useState<DocFull | null>(null)
  const [form, setForm] = useState<Extracted>({})
  const [dirty, setDirty] = useState(false)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [fileUrl, setFileUrl] = useState('')
  const [isImage, setIsImage] = useState(false)

  const load = useCallback(async () => {
    const d = await api.get<DocFull>(`/api/docs/${id}`)
    setDoc(d)
    setForm(d.extracted ?? {})
    setDirty(false)
  }, [id])

  useEffect(() => { load().catch((e) => setErr(e.message)) }, [load])

  useEffect(() => {
    if (!doc || !['queued', 'processing'].includes(doc.status)) return
    const t = setInterval(() => load().catch(() => {}), 1500)
    return () => clearInterval(t)
  }, [doc, load])

  // файл тягнемо з Authorization-заголовком і показуємо через blob-URL
  useEffect(() => {
    let url = ''
    api.blob(`/api/docs/${id}/file`).then((b) => {
      const previewable = b.type === 'application/pdf' || b.type.startsWith('image/')
      if (!previewable) return
      url = URL.createObjectURL(b)
      setIsImage(b.type.startsWith('image/'))
      setFileUrl(url)
    }).catch(() => {})
    return () => { if (url) URL.revokeObjectURL(url) }
  }, [id])

  const flagsFor = (k: string): Flag[] => (doc?.flags ?? []).filter((f) => f.field === k)

  async function run(fn: () => Promise<unknown>) {
    setBusy(true); setErr('')
    try { await fn() } catch (e) { setErr((e as ApiError).message) } finally { setBusy(false) }
  }

  const save = () => run(async () => {
    const d = await api.patch<DocFull>(`/api/docs/${id}`, { extracted: form })
    setDoc(d); setForm(d.extracted ?? {}); setDirty(false)
  })

  const back = doc ? MODULE_PATH[doc.module] ?? '/' : '/'

  // конвеєр: після рішення одразу відкриваємо наступний документ на перевірці
  const goNext = async () => {
    if (!doc) return nav(back)
    try {
      const r = await api.get<{ id: number | null }>(`/api/docs/next?module=${doc.module}&after=${doc.id}`)
      nav(r.id ? `/doc/${r.id}` : back)
    } catch { nav(back) }
  }

  const approve = () => run(async () => {
    if (dirty) await save()
    try {
      await api.post(`/api/docs/${id}/approve`)
      await goNext()
    } catch (e) {
      const ex = e as ApiError
      if (ex.status === 422 && window.confirm('Є критичні попередження. Затвердити все одно?')) {
        await api.post(`/api/docs/${id}/approve?force=true`)
        await goNext()
      } else throw e
    }
  })

  if (!doc) return err ? <div className="alert error">{err}</div> : null
  const processing = doc.status === 'queued' || doc.status === 'processing'
  const editable = canEdit && ['review', 'failed', 'rejected'].includes(doc.status)
  const items: any[] = form.line_items ?? []

  return (
    <>
      <div className="page-head">
        <div>
          <Link to={back}>← Назад до списку</Link>
          <h1>{doc.filename}</h1>
          <span className="badge">{STATUS_LABEL[doc.status]}</span>{' '}
          {doc.confidence && <span className={`badge ${doc.confidence === 'high' ? 'ok' : doc.confidence === 'low' ? 'err' : 'warn'}`}>впевненість: {doc.confidence}</span>}
        </div>
        {editable && (
          <div className="row">
            <button className="btn" disabled={busy} onClick={() => run(() => api.post(`/api/docs/${id}/reprocess`).then(load))}>Розпізнати знову</button>
            <button className="btn danger" disabled={busy || doc.status === 'rejected'} onClick={() => run(async () => { await api.post(`/api/docs/${id}/reject`); await goNext() })}>Відхилити</button>
            {dirty && <button className="btn" disabled={busy} onClick={save}>Зберегти</button>}
            <button className="btn primary" disabled={busy || doc.status !== 'review'} onClick={approve}>Затвердити і далі →</button>
          </div>
        )}
      </div>

      {err && <div className="alert error">{err}</div>}
      {processing && <div className="alert info">Документ обробляється… сторінка оновиться автоматично.</div>}
      {doc.status === 'failed' && <div className="alert error">Не вдалося розпізнати: {doc.error}</div>}

      {doc.view === 'report' && doc.metrics && !dirty && <div style={{ marginBottom: 16 }}><ReportView metrics={doc.metrics} data={doc.extracted ?? {}} /></div>}
      {doc.view === 'report' && dirty && <div className="alert warning">Є незбережені зміни — збережіть, щоб оновити розрахунки.</div>}

      <div className="split">
        <div className="preview">
          {fileUrl ? (isImage ? <img src={fileUrl} alt={doc.filename} /> : <iframe src={fileUrl} title={doc.filename} />)
            : <div className="empty">Попередній перегляд недоступний для цього формату</div>}
        </div>

        <div>
          {doc.flags.length > 0 && (
            <div style={{ marginBottom: 12 }}>
              {doc.flags.map((f, i) => <div key={i} className={`alert ${f.severity}`}>{f.message}</div>)}
            </div>
          )}
          {doc.match && doc.match.status !== 'no_directory' && (
            <div className={`alert ${doc.match.status === 'matched' ? 'info' : 'warning'}`}>
              {doc.match.status === 'matched' && <>Контрагента знайдено в довіднику: <strong>{doc.match.name}</strong></>}
              {doc.match.status === 'suggested' && <>Схожий контрагент (збіг {doc.match.score}%): <strong>{doc.match.name}</strong> — перевірте</>}
              {doc.match.status === 'ambiguous' && <>Кілька схожих контрагентів у довіднику — оберіть вручну</>}
              {doc.match.status === 'not_found' && <>Контрагента немає в довіднику</>}
            </div>
          )}

          <div className="card">
            <h2>Розпізнані дані</h2>
            {doc.fields.map(({ key, label, type }) => {
              const fl = flagsFor(key)
              const bad = fl.some((f) => f.severity === 'error')
              return (
                <div key={key} className={`field${bad ? ' bad' : ''}`}>
                  <label className="f" htmlFor={key}>{label}</label>
                  <input id={key} type={type === 'number' ? 'number' : 'text'} step={type === 'number' ? '0.01' : undefined}
                    placeholder={type === 'date' ? 'РРРР-ММ-ДД' : undefined}
                    disabled={!editable} value={form[key] ?? ''}
                    onChange={(e) => { setForm({ ...form, [key]: type === 'number' ? Number(e.target.value) : e.target.value }); setDirty(true) }} />
                  {fl.map((f, i) => <div key={i} className={`hint${f.severity === 'warning' ? ' warn' : ''}`}>{f.message}</div>)}
                </div>
              )
            })}
          </div>

          {items.length > 0 && (
            <div className="card scroll-x" style={{ marginTop: 16, padding: 0 }}>
              <table className="t">
                <thead><tr><th>Позиція</th><th className="num">К-сть</th><th className="num">Ціна</th><th className="num">Сума</th></tr></thead>
                <tbody>
                  {items.map((li, i) => (
                    <tr key={i}><td>{li.description}</td><td className="num">{li.quantity}</td><td className="num">{li.unit_price}</td><td className="num">{li.amount}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {doc.extracted?.notes && <p className="muted">Коментар AI: {doc.extracted.notes}</p>}
        </div>
      </div>
    </>
  )
}
