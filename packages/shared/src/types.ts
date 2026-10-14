export interface Me {
  id: number
  email: string
  full_name: string
  role: 'platform_admin' | 'owner' | 'accountant' | 'viewer'
  tenant_id: number | null
  tenant_name: string | null
  plan: string | null
  modules: string[]
  trial_ends_at?: string | null
}

export interface Flag {
  code: string
  severity: 'error' | 'warning' | 'info'
  field: string
  message: string
}

export type Extracted = Record<string, any>

export interface FieldSpec {
  key: string
  label: string
  type: 'text' | 'number' | 'date' | 'textarea'
}

export type DocStatus = 'queued' | 'processing' | 'review' | 'approved' | 'rejected' | 'failed'

export interface DocRow {
  id: number
  module: string
  filename: string
  doc_type: string
  status: DocStatus
  confidence: string
  supplier_name: string
  doc_number: string
  amount: number
  currency: string
  created_at: string
  flag_count: number
  error_count: number
  match_status: string | null
  error: string
}

export interface DocFull extends DocRow {
  extracted: Extracted | null
  flags: Flag[]
  match: { status: string; name?: string; tax_id?: string; iban?: string; score?: number } | null
  description: string
  media_type: string
  size: number
  approved_at: string | null
  metrics: Record<string, any> | null
  fields: FieldSpec[]
  view: 'form' | 'report'
}

export const MODULE_PATH: Record<string, string> = {
  docs_extract: '/documents',
  identity: '/identity',
  reports: '/reports',
}

export interface ModuleInfo {
  code: string
  name: string
  description: string
  ready: boolean
  enabled: boolean
}

export const STATUS_LABEL: Record<DocStatus, string> = {
  queued: 'В черзі',
  processing: 'Обробка',
  review: 'На перевірці',
  approved: 'Затверджено',
  rejected: 'Відхилено',
  failed: 'Помилка',
}

export const money = (n: number, cur = 'UAH') =>
  new Intl.NumberFormat('uk-UA', { style: 'currency', currency: cur || 'UAH' }).format(n || 0)

export const dateTime = (s?: string | null) =>
  s ? new Date(s + (s.endsWith('Z') ? '' : 'Z')).toLocaleString('uk-UA', { dateStyle: 'short', timeStyle: 'short' }) : '—'
