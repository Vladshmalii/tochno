export class ApiError extends Error {
  status: number
  detail: unknown
  constructor(status: number, message: string, detail?: unknown) {
    super(message)
    this.status = status
    this.detail = detail
  }
}

const BASE: string = (import.meta as any).env?.VITE_API_URL ?? 'http://localhost:8000'

export interface ApiClient {
  get<T>(path: string): Promise<T>
  post<T>(path: string, body?: unknown): Promise<T>
  patch<T>(path: string, body?: unknown): Promise<T>
  put<T>(path: string, body?: unknown): Promise<T>
  del(path: string): Promise<void>
  upload<T>(path: string, form: FormData): Promise<T>
  blob(path: string): Promise<Blob>
  download(path: string, filename: string): Promise<void>
  base: string
}

function messageFrom(detail: any, fallback: string): string {
  if (typeof detail === 'string') return detail
  if (detail?.message) return detail.message
  if (Array.isArray(detail) && detail[0]?.msg) return detail[0].msg
  return fallback
}

/** Фабрика клієнта: кожен застосунок (кабінет/адмінка) має власний ключ токена. */
export function createApi(tokenKey: string, onUnauthorized: () => void): ApiClient {
  const getToken = () => {
    try { return localStorage.getItem(tokenKey) } catch { return null }
  }

  async function raw(path: string, init: RequestInit = {}, json = true): Promise<Response> {
    const headers = new Headers(init.headers)
    const token = getToken()
    if (token) headers.set('Authorization', `Bearer ${token}`)
    if (json && init.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json')
    let res: Response
    try {
      res = await fetch(BASE + path, { ...init, headers })
    } catch {
      throw new ApiError(0, 'Немає зв’язку із сервером')
    }
    if (res.status === 401 && token) onUnauthorized()
    if (!res.ok) {
      let detail: unknown = null
      try { detail = (await res.json()).detail } catch { /* not json */ }
      throw new ApiError(res.status, messageFrom(detail, `Помилка ${res.status}`), detail)
    }
    return res
  }

  const parse = async <T,>(r: Response): Promise<T> => (r.status === 204 ? (undefined as T) : r.json())

  return {
    base: BASE,
    get: (p) => raw(p).then((r) => parse(r)),
    post: (p, b) => raw(p, { method: 'POST', body: b === undefined ? undefined : JSON.stringify(b) }).then((r) => parse(r)),
    patch: (p, b) => raw(p, { method: 'PATCH', body: JSON.stringify(b ?? {}) }).then((r) => parse(r)),
    put: (p, b) => raw(p, { method: 'PUT', body: JSON.stringify(b ?? {}) }).then((r) => parse(r)),
    del: (p) => raw(p, { method: 'DELETE' }).then(() => undefined),
    upload: (p, f) => raw(p, { method: 'POST', body: f }, false).then((r) => parse(r)),
    blob: (p) => raw(p).then((r) => r.blob()),
    async download(p, filename) {
      const blob = await raw(p).then((r) => r.blob())
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      a.click()
      URL.revokeObjectURL(url)
    },
  }
}
