import { Logo } from '@tochno/shared'
import { FormEvent, useState } from 'react'
import { Navigate, NavLink, Outlet, Route, Routes } from 'react-router-dom'
import { useAuth } from './auth'
import Overview from './pages/Overview'
import Tenants from './pages/Tenants'
import TenantDetail from './pages/TenantDetail'
import Plans from './pages/Plans'
import Audit from './pages/Audit'

function Login() {
  const { me, login } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [err, setErr] = useState('')
  if (me) return <Navigate to="/" replace />
  const submit = async (e: FormEvent) => {
    e.preventDefault(); setErr('')
    try { await login(email, password) } catch (x: any) { setErr(x.message) }
  }
  return (
    <div className="auth-wrap">
      <form className="card auth-card" onSubmit={submit}>
        <Logo size={32} suffix="Admin" />
        <p className="muted" style={{ marginTop: 0 }}>Панель керування платформою</p>
        {err && <div className="alert error">{err}</div>}
        <div className="field"><label className="f">Email</label><input required autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} /></div>
        <div className="field"><label className="f">Пароль</label><input type="password" required autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} /></div>
        <button className="btn primary" style={{ width: '100%', justifyContent: 'center' }}>Увійти</button>
      </form>
    </div>
  )
}

function Shell() {
  const { me, logout } = useAuth()
  if (!me) return <Navigate to="/login" replace />
  return (
    <div className="shell">
      <aside className="sidebar">
        <Logo suffix="Admin" />
        <nav className="nav">
          <NavLink to="/" end>Огляд</NavLink>
          <NavLink to="/tenants">Клієнти</NavLink>
          <NavLink to="/plans">Тарифи та модулі</NavLink>
          <NavLink to="/audit">Журнал дій</NavLink>
        </nav>
        <div className="sidebar-foot">
          <div className="muted">{me.email}</div>
          <button className="btn sm" style={{ marginTop: 8 }} onClick={logout}>Вийти</button>
        </div>
      </aside>
      <main className="main"><Outlet /></main>
    </div>
  )
}

export default function App() {
  const { loading } = useAuth()
  if (loading) return <div className="auth-wrap muted">Завантаження…</div>
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<Shell />}>
        <Route index element={<Overview />} />
        <Route path="tenants" element={<Tenants />} />
        <Route path="tenants/:id" element={<TenantDetail />} />
        <Route path="plans" element={<Plans />} />
        <Route path="audit" element={<Audit />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
