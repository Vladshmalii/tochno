import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ModuleInfo } from '@tochno/shared'
import { api } from '../auth'

export default function Locked() {
  const { code } = useParams()
  const [m, setM] = useState<ModuleInfo | null>(null)
  useEffect(() => { api.get<ModuleInfo[]>('/api/modules').then((l) => setM(l.find((x) => x.code === code) ?? null)) }, [code])
  if (!m) return null
  return (
    <div className="card empty" style={{ maxWidth: 560, margin: '40px auto' }}>
      <h1>{m.name}</h1>
      <p>{m.description}</p>
      {m.enabled ? (
        <Link to="/">На головну</Link>
      ) : (
        <p>Модуль не входить до вашого тарифу. Зверніться до менеджера, щоб підключити його.</p>
      )}
    </div>
  )
}
