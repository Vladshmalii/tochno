import { createContext, ReactNode, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { createApi, Me } from '@tochno/shared'

const TOKEN_KEY = 'dm_client_token'

const store = {
  get: () => { try { return localStorage.getItem(TOKEN_KEY) } catch { return null } },
  set: (t: string) => { try { localStorage.setItem(TOKEN_KEY, t) } catch { /* private mode */ } },
  clear: () => { try { localStorage.removeItem(TOKEN_KEY) } catch { /* private mode */ } },
}

// вхід «під клієнтом» зі служби підтримки: короткоживучий токен приходить у hash і одразу прибирається з адреси
if (typeof window !== 'undefined' && window.location.hash.startsWith('#imp=')) {
  store.set(decodeURIComponent(window.location.hash.slice(5)))
  window.history.replaceState(null, '', window.location.pathname)
}

let onUnauthorized: () => void = () => {}
export const api = createApi(TOKEN_KEY, () => onUnauthorized())

interface AuthCtx {
  me: Me | null
  loading: boolean
  login: (email: string, password: string) => Promise<void>
  signup: (v: { company: string; full_name: string; email: string; password: string }) => Promise<void>
  logout: () => void
  reload: () => Promise<void>
  has: (module: string) => boolean
}

const Ctx = createContext<AuthCtx>(null as unknown as AuthCtx)
export const useAuth = () => useContext(Ctx)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null)
  const [loading, setLoading] = useState(!!store.get())

  const logout = useCallback(() => { store.clear(); setMe(null) }, [])
  onUnauthorized = logout

  const reload = useCallback(async () => {
    try {
      const u = await api.get<Me>('/api/auth/me')
      // кабінет клієнта — не для адмінів платформи
      if (u.role === 'platform_admin') { logout(); return }
      setMe(u)
    } catch { logout() } finally { setLoading(false) }
  }, [logout])

  useEffect(() => { if (store.get()) reload() }, [reload])

  const accept = async (res: { access_token: string; user: Me }) => {
    if (res.user.role === 'platform_admin') throw new Error('Це акаунт адміністратора платформи — використайте адмін-панель')
    store.set(res.access_token)
    setMe(res.user)
  }

  const value = useMemo<AuthCtx>(() => ({
    me, loading, logout, reload,
    login: async (email, password) => accept(await api.post('/api/auth/login', { email, password })),
    signup: async (v) => accept(await api.post('/api/auth/signup', v)),
    has: (m) => !!me?.modules.includes(m),
  }), [me, loading, logout, reload])

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}
