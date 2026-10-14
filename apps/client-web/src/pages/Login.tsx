import { Logo } from '@tochno/shared'
import { FormEvent, useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth'

export default function Login() {
  const { me, login, signup } = useAuth()
  const nav = useNavigate()
  const [mode, setMode] = useState<'login' | 'signup'>('login')
  const [v, setV] = useState({ company: '', full_name: '', email: '', password: '' })
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  if (me) return <Navigate to="/" replace />

  const set = (k: keyof typeof v) => (e: React.ChangeEvent<HTMLInputElement>) => setV({ ...v, [k]: e.target.value })

  async function submit(e: FormEvent) {
    e.preventDefault()
    setErr('')
    setBusy(true)
    try {
      if (mode === 'login') await login(v.email, v.password)
      else await signup(v)
      nav('/')
    } catch (x: any) {
      setErr(x.message || 'Помилка')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="auth-wrap">
      <form className="card auth-card" onSubmit={submit}>
        <Logo size={32} />
        <p className="muted" style={{ marginTop: 0 }}>
          {mode === 'login' ? 'Увійдіть до кабінету' : 'Створіть акаунт — 30 документів безкоштовно'}
        </p>
        {err && <div className="alert error">{err}</div>}
        {mode === 'signup' && (
          <>
            <div className="field"><label className="f">Компанія</label><input required value={v.company} onChange={set('company')} /></div>
            <div className="field"><label className="f">Ваше ім’я</label><input required value={v.full_name} onChange={set('full_name')} /></div>
          </>
        )}
        <div className="field"><label className="f">Email</label><input type="email" required autoComplete="username" value={v.email} onChange={set('email')} /></div>
        <div className="field">
          <label className="f">Пароль</label>
          <input type="password" required minLength={mode === 'signup' ? 8 : undefined}
            autoComplete={mode === 'login' ? 'current-password' : 'new-password'} value={v.password} onChange={set('password')} />
        </div>
        <button className="btn primary" style={{ width: '100%', justifyContent: 'center' }} disabled={busy}>
          {busy ? '…' : mode === 'login' ? 'Увійти' : 'Створити акаунт'}
        </button>
        <p className="muted" style={{ textAlign: 'center', marginBottom: 0 }}>
          {mode === 'login' ? 'Немає акаунта? ' : 'Вже є акаунт? '}
          <a href="#" onClick={(e) => { e.preventDefault(); setErr(''); setMode(mode === 'login' ? 'signup' : 'login') }}>
            {mode === 'login' ? 'Зареєструватись' : 'Увійти'}
          </a>
        </p>
      </form>
    </div>
  )
}
