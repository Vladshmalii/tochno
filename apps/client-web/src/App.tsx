import { Logo } from '@tochno/shared'
import { Navigate, NavLink, Outlet, Route, Routes } from 'react-router-dom'
import { dateTime } from '@tochno/shared'
import { useAuth } from './auth'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import Documents, { VIEWS } from './pages/Documents'
import DocumentReview from './pages/DocumentReview'
import Contractors from './pages/Contractors'
import Knowledge from './pages/Knowledge'
import Team from './pages/Team'
import Settings from './pages/Settings'
import Locked from './pages/Locked'

const NAV: { code: string; to: string; label: string }[] = [
  { code: 'docs_extract', to: '/documents', label: 'Документи' },
  { code: 'reconcile', to: '/contractors', label: 'Контрагенти' },
  { code: 'reports', to: '/reports', label: 'Бухгалтерські звіти' },
  { code: 'identity', to: '/identity', label: 'Кадри' },
  { code: 'knowledge', to: '/knowledge', label: 'База знань' },
]

function Shell() {
  const { me, has, logout } = useAuth()
  if (!me) return <Navigate to="/login" replace />
  const trialDays = me.trial_ends_at ? Math.ceil((new Date(me.trial_ends_at + 'Z').getTime() - Date.now()) / 86400000) : null
  return (
    <div className="shell">
      <aside className="sidebar">
        <Logo />
        <nav className="nav">
          <NavLink to="/" end>Огляд</NavLink>
          <div className="nav-section">Модулі</div>
          {NAV.map((n) => has(n.code)
            ? <NavLink key={n.code} to={n.to}>{n.label}</NavLink>
            : <NavLink key={n.code} to={`/locked/${n.code}`} className="locked">{n.label}<span className="badge">🔒</span></NavLink>)}
          <div className="nav-section">Акаунт</div>
          <NavLink to="/team">Команда</NavLink>
          <NavLink to="/settings">Налаштування</NavLink>
        </nav>
        <div className="sidebar-foot">
          <div><strong>{me.tenant_name}</strong></div>
          <div className="muted">{me.full_name || me.email}</div>
          <div className="row" style={{ marginTop: 8 }}>
            <span className="badge accent">{me.plan}</span>
            <button className="btn sm" onClick={logout}>Вийти</button>
          </div>
        </div>
      </aside>
      <main className="main">
        {trialDays !== null && (
          <div className={`alert ${trialDays <= 3 ? 'warning' : 'info'}`}>
            Пробний період: {trialDays > 0 ? `залишилось ${trialDays} дн. (до ${dateTime(me.trial_ends_at)})` : 'завершився'}. Щоб продовжити, зверніться до менеджера для вибору тарифу.
          </div>
        )}
        <Outlet />
      </main>
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
        <Route index element={<Dashboard />} />
        <Route path="documents" element={<Documents view={VIEWS.docs_extract} />} />
        <Route path="identity" element={<Documents view={VIEWS.identity} />} />
        <Route path="reports" element={<Documents view={VIEWS.reports} />} />
        <Route path="doc/:id" element={<DocumentReview />} />
        <Route path="contractors" element={<Contractors />} />
        <Route path="knowledge" element={<Knowledge />} />
        <Route path="team" element={<Team />} />
        <Route path="settings" element={<Settings />} />
        <Route path="locked/:code" element={<Locked />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
