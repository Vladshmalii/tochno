import { createContext, ReactNode, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { createApi, Me } from '@tochno/shared'

const TOKEN_KEY = 'dm_admin_token'
const store = {
  get: () => { try { return localStorage.getItem(TOKEN_KEY) } catch { return null } },
  set: (t: string) => { try { localStorage.setItem(TOKEN_KEY, t) } catch { /* private mode */ } },
  clear: () => { try { localStorage.removeItem(TOKEN_KEY) } catch { /* private mode */ } },
}

let onUnauthorized: () => void = () => {}
export const api = createApi(TOKEN_KEY, () => onUnauthorized())

interface AuthCtx {
  me: Me | null
  loading: boolean
  login: (email: string, password: string) => Promise<void>
  logout: () => void
}
const Ctx = createContext<AuthCtx>(null as unknown as AuthCtx)
export const useAuth = () => useContext(Ctx)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null)
  const [loading, setLoading] = useState(!!store.get())
  const logout = useCallback(() => { store.clear(); setMe(null) }, [])
  onUnauthorized = logout

  useEffect(() => {
    if (!store.get()) return
    api.get<Me>('/api/auth/me')
      .then((u) => (u.role === 'platform_admin' ? setMe(u) : logout()))
      .catch(logout)
      .finally(() => setLoading(false))
  }, [logout])

  const value = useMemo<AuthCtx>(() => ({
    me, loading, logout,
    login: async (email, password) => {
      const res = await api.post<{ access_token: string; user: Me }>('/api/auth/login', { email, password })
      if (res.user.role !== 'platform_admin') throw new Error('Доступ лише для адміністраторів платформи')
      store.set(res.access_token)
      setMe(res.user)
    },
  }), [me, loading, logout])

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}
