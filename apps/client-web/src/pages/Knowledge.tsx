import { FormEvent, useCallback, useEffect, useRef, useState } from 'react'
import { dateTime } from '@tochno/shared'
import { api, useAuth } from '../auth'

interface Source { doc_id: number; title: string; snippet: string; score: number }
interface Msg { role: 'user' | 'bot'; text: string; sources?: Source[]; logId?: number; found?: boolean; vote?: number }
interface KDoc { id: number; title: string; filename: string; chars: number; chunks: number; created_at: string }
interface Gap { id: number; question: string; found: boolean; feedback: number | null; created_at: string }

function Chat() {
  const [msgs, setMsgs] = useState<Msg[]>([])
  const [q, setQ] = useState('')
  const [busy, setBusy] = useState(false)
  const end = useRef<HTMLDivElement>(null)
  useEffect(() => { end.current?.scrollIntoView({ behavior: 'smooth' }) }, [msgs])

  async function ask(e: FormEvent) {
    e.preventDefault()
    const question = q.trim()
    if (!question || busy) return
    setQ(''); setBusy(true)
    setMsgs((m) => [...m, { role: 'user', text: question }])
    try {
      const r = await api.post<{ log_id: number; answer: string; found: boolean; sources: Source[] }>('/api/knowledge/ask', { question })
      setMsgs((m) => [...m, { role: 'bot', text: r.answer, sources: r.sources, logId: r.log_id, found: r.found }])
    } catch (x: any) {
      setMsgs((m) => [...m, { role: 'bot', text: x.message, found: false }])
    } finally { setBusy(false) }
  }

  async function vote(i: number, value: number) {
    const m = msgs[i]
    if (!m.logId) return
    await api.post('/api/knowledge/feedback', { log_id: m.logId, value }).catch(() => {})
    setMsgs((all) => all.map((x, j) => (j === i ? { ...x, vote: value } : x)))
  }

  return (
    <div className="card" style={{ display: 'flex', flexDirection: 'column', height: '64vh' }}>
      <div style={{ flex: 1, overflow: 'auto', paddingRight: 4 }}>
        {msgs.length === 0 && <div className="empty">Задайте питання за вашими інструкціями — відповідь буде з посиланням на джерело.</div>}
        {msgs.map((m, i) => (
          <div key={i} style={{ display: 'flex', justifyContent: m.role === 'user' ? 'flex-end' : 'flex-start', marginBottom: 12 }}>
            <div style={{ maxWidth: '82%', background: m.role === 'user' ? 'var(--accent)' : 'var(--surface-2)', color: m.role === 'user' ? '#fff' : 'inherit', padding: '10px 14px', borderRadius: 12, whiteSpace: 'pre-wrap' }}>
              {m.text}
              {m.role === 'bot' && m.sources && m.sources.length > 0 && (
                <details style={{ marginTop: 8 }}>
                  <summary className="muted" style={{ cursor: 'pointer' }}>Джерела ({m.sources.length})</summary>
                  {m.sources.map((s, j) => <div key={j} className="muted" style={{ marginTop: 6, fontSize: 13 }}><strong>{s.title}</strong>: {s.snippet.slice(0, 220)}…</div>)}
                </details>
              )}
              {m.role === 'bot' && m.logId && (
                <div className="row" style={{ marginTop: 8 }}>
                  <button className="btn sm" disabled={m.vote !== undefined} onClick={() => vote(i, 1)} aria-label="Корисно">👍</button>
                  <button className="btn sm" disabled={m.vote !== undefined} onClick={() => vote(i, -1)} aria-label="Не допомогло">👎</button>
                </div>
              )}
            </div>
          </div>
        ))}
        {busy && <div className="muted">Шукаю відповідь…</div>}
        <div ref={end} />
      </div>
      <form className="row" onSubmit={ask} style={{ marginTop: 12, flexWrap: 'nowrap' }}>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Наприклад: коли здається інкасація?" aria-label="Питання" />
        <button className="btn primary" disabled={busy}>Запитати</button>
      </form>
    </div>
  )
}

function Base({ canEdit }: { canEdit: boolean }) {
  const [docs, setDocs] = useState<KDoc[]>([])
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [t, setT] = useState({ title: '', text: '' })
  const file = useRef<HTMLInputElement>(null)
  const load = useCallback(() => api.get<KDoc[]>('/api/knowledge/docs').then(setDocs).catch((e) => setErr(e.message)), [])
  useEffect(() => { load() }, [load])

  async function upload(files: FileList) {
    setBusy(true); setErr('')
    const fd = new FormData(); Array.from(files).forEach((f) => fd.append('files', f))
    try { await api.upload('/api/knowledge/docs', fd); await load() } catch (e: any) { setErr(e.message) } finally { setBusy(false) }
  }
  async function addText(e: FormEvent) {
    e.preventDefault(); setErr('')
    try { await api.post('/api/knowledge/docs/text', t); setT({ title: '', text: '' }); load() } catch (x: any) { setErr(x.message) }
  }

  return (
    <>
      {err && <div className="alert error">{err}</div>}
      {canEdit && (
        <div className="grid cols-2" style={{ marginBottom: 16 }}>
          <div className="card">
            <h2>Завантажити файли</h2>
            <p className="muted">Текстовий PDF, DOCX, XLSX, TXT. Скани без текстового шару не підтримуються.</p>
            <button className="btn primary" disabled={busy} onClick={() => file.current?.click()}>{busy ? 'Індексація…' : 'Вибрати файли'}</button>
            <input ref={file} type="file" multiple hidden accept=".pdf,.docx,.doc,.xlsx,.xls,.txt,.csv" onChange={(e) => { if (e.target.files) upload(e.target.files); e.target.value = '' }} />
          </div>
          <form className="card" onSubmit={addText}>
            <h2>Додати текстом</h2>
            <div className="field"><input placeholder="Назва інструкції" required value={t.title} onChange={(e) => setT({ ...t, title: e.target.value })} /></div>
            <div className="field"><textarea rows={4} required minLength={20} placeholder="Текст інструкції" value={t.text} onChange={(e) => setT({ ...t, text: e.target.value })} /></div>
            <button className="btn">Додати</button>
          </form>
        </div>
      )}
      <div className="card scroll-x" style={{ padding: 0 }}>
        {docs.length === 0 ? <div className="empty">База знань порожня</div> : (
          <table className="t">
            <thead><tr><th>Назва</th><th className="num">Фрагментів</th><th>Додано</th><th /></tr></thead>
            <tbody>{docs.map((d) => (
              <tr key={d.id}><td>{d.title}<div className="muted">{d.filename}</div></td><td className="num">{d.chunks}</td><td className="muted">{dateTime(d.created_at)}</td>
                <td className="num">{canEdit && <button className="btn sm danger" onClick={() => { if (window.confirm(`Видалити «${d.title}»?`)) api.del(`/api/knowledge/docs/${d.id}`).then(load) }}>Видалити</button>}</td></tr>
            ))}</tbody>
          </table>
        )}
      </div>
    </>
  )
}

function Gaps() {
  const [g, setG] = useState<{ total_questions: number; items: Gap[] } | null>(null)
  useEffect(() => { api.get<{ total_questions: number; items: Gap[] }>('/api/knowledge/gaps').then(setG).catch(() => {}) }, [])
  if (!g) return null
  return (
    <>
      <p className="muted">Питань усього: {g.total_questions}. Нижче — питання без відповіді або з оцінкою «не допомогло»: додайте відповідні інструкції.</p>
      <div className="card scroll-x" style={{ padding: 0 }}>
        {g.items.length === 0 ? <div className="empty">Прогалин поки немає</div> : (
          <table className="t"><thead><tr><th>Питання</th><th>Проблема</th><th>Коли</th></tr></thead>
            <tbody>{g.items.map((i) => (
              <tr key={i.id}><td>{i.question}</td><td>{i.found ? <span className="badge warn">Не допомогло</span> : <span className="badge err">Не знайдено</span>}</td><td className="muted">{dateTime(i.created_at)}</td></tr>
            ))}</tbody></table>
        )}
      </div>
    </>
  )
}

export default function Knowledge() {
  const { me } = useAuth()
  const canEdit = me?.role === 'owner' || me?.role === 'accountant'
  const [tab, setTab] = useState<'chat' | 'base' | 'gaps'>('chat')
  return (
    <>
      <div className="page-head"><div><h1>База знань</h1><div className="muted">AI-асистент відповідає лише за вашими інструкціями</div></div></div>
      <div className="row" style={{ marginBottom: 16 }}>
        <button className={`btn${tab === 'chat' ? ' primary' : ''}`} onClick={() => setTab('chat')}>Асистент</button>
        <button className={`btn${tab === 'base' ? ' primary' : ''}`} onClick={() => setTab('base')}>Матеріали</button>
        {canEdit && <button className={`btn${tab === 'gaps' ? ' primary' : ''}`} onClick={() => setTab('gaps')}>Прогалини</button>}
      </div>
      {tab === 'chat' && <Chat />}
      {tab === 'base' && <Base canEdit={canEdit} />}
      {tab === 'gaps' && <Gaps />}
    </>
  )
}
