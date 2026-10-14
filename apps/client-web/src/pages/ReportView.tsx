import { money } from '@tochno/shared'

type M = Record<string, any>

function Stat({ label, value, tone }: { label: string; value: string; tone?: 'ok' | 'err' }) {
  return (
    <div className="card stat">
      <div className="l">{label}</div>
      <div className="v" style={{ fontSize: 20, color: tone === 'ok' ? 'var(--ok)' : tone === 'err' ? 'var(--err)' : undefined }}>{value}</div>
    </div>
  )
}

function Bars({ rows, cur }: { rows: { name: string; amount: number }[]; cur: string }) {
  const max = Math.max(...rows.map((r) => r.amount), 1)
  return (
    <div>
      {rows.map((r) => (
        <div key={r.name} style={{ marginBottom: 10 }}>
          <div className="row" style={{ justifyContent: 'space-between' }}><span>{r.name}</span><strong>{money(r.amount, cur)}</strong></div>
          <div className="bar"><div style={{ width: `${(r.amount / max) * 100}%` }} /></div>
        </div>
      ))}
    </div>
  )
}

/** Лінія залишку по днях — легкий SVG без бібліотек. */
function Line({ series }: { series: { date: string; balance: number }[] }) {
  if (series.length < 2) return null
  const W = 560, H = 140, P = 8
  const vals = series.map((s) => s.balance)
  const lo = Math.min(...vals), hi = Math.max(...vals)
  const span = hi - lo || 1
  const pts = series.map((s, i) => `${P + (i / (series.length - 1)) * (W - 2 * P)},${H - P - ((s.balance - lo) / span) * (H - 2 * P)}`)
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="Динаміка залишку на рахунку">
      <polyline points={pts.join(' ')} fill="none" stroke="var(--accent)" strokeWidth="2.5" strokeLinejoin="round" />
      {pts.map((p, i) => <circle key={i} cx={p.split(',')[0]} cy={p.split(',')[1]} r="3" fill="var(--accent)" />)}
    </svg>
  )
}

export default function ReportView({ metrics, data }: { metrics: M; data: M }) {
  const cur = metrics.currency || 'UAH'
  const summary = metrics.summary && (
    <div className="alert info" style={{ marginTop: 0 }}>{metrics.summary}</div>
  )

  if (metrics.kind === 'bank_statement') {
    const tx: any[] = data.transactions ?? []
    return (
      <>
        {summary}
        <div className="grid cols-3" style={{ marginBottom: 16 }}>
          <Stat label="Надходження" value={money(metrics.total_in, cur)} tone="ok" />
          <Stat label="Витрати" value={money(metrics.total_out, cur)} tone="err" />
          <Stat label="Чистий рух" value={money(metrics.net, cur)} />
        </div>
        <div className="grid cols-2" style={{ marginBottom: 16 }}>
          <div className="card"><h2>Витрати за категоріями</h2>{metrics.by_category.length ? <Bars rows={metrics.by_category} cur={cur} /> : <span className="muted">Немає витрат</span>}</div>
          <div className="card"><h2>Динаміка залишку</h2><Line series={metrics.balance_series} />
            {metrics.top_counterparties.length > 0 && <><h2 style={{ marginTop: 14 }}>Найбільші отримувачі</h2><Bars rows={metrics.top_counterparties} cur={cur} /></>}</div>
        </div>
        <div className="card scroll-x" style={{ padding: 0 }}>
          <table className="t">
            <thead><tr><th>Дата</th><th>Призначення</th><th>Контрагент</th><th>Категорія</th><th className="num">Сума</th></tr></thead>
            <tbody>{tx.map((t, i) => (
              <tr key={i}><td>{t.date}</td><td>{t.description}</td><td>{t.counterparty || '—'}</td><td><span className="badge">{t.category}</span></td>
                <td className="num" style={{ color: t.amount < 0 ? 'var(--err)' : 'var(--ok)' }}>{money(t.amount, cur)}</td></tr>
            ))}</tbody>
          </table>
        </div>
      </>
    )
  }

  if (metrics.kind === 'balance_sheet') {
    const Table = ({ title, rows }: { title: string; rows: any[] }) => (
      <div className="card scroll-x" style={{ padding: 0 }}>
        <table className="t"><thead><tr><th>{title}</th><th className="num">Сума</th></tr></thead>
          <tbody>{(rows ?? []).map((r, i) => <tr key={i}><td>{r.name}{r.current === false && <span className="badge" style={{ marginLeft: 6 }}>довгостр.</span>}</td><td className="num">{money(r.amount, cur)}</td></tr>)}</tbody></table>
      </div>
    )
    const ratio = (v: number | null) => (v === null || v === undefined ? '—' : String(v))
    return (
      <>
        {summary}
        <div className="grid cols-4" style={{ marginBottom: 16 }}>
          <Stat label="Актив" value={money(metrics.assets, cur)} />
          <Stat label="Зобов’язання" value={money(metrics.liabilities, cur)} />
          <Stat label="Власний капітал" value={money(metrics.equity, cur)} tone={metrics.equity < 0 ? 'err' : undefined} />
          <Stat label="Робочий капітал" value={money(metrics.working_capital, cur)} />
        </div>
        <div className="grid cols-3" style={{ marginBottom: 16 }}>
          <Stat label="Поточна ліквідність" value={ratio(metrics.current_ratio)} />
          <Stat label="Частка власного капіталу" value={metrics.equity_ratio === null ? '—' : `${Math.round(metrics.equity_ratio * 100)}%`} />
          <Stat label="Частка зобов’язань" value={metrics.debt_ratio === null ? '—' : `${Math.round(metrics.debt_ratio * 100)}%`} />
        </div>
        <div className="grid cols-3">
          <Table title="Актив" rows={data.assets} /><Table title="Зобов’язання" rows={data.liabilities} /><Table title="Власний капітал" rows={data.equity} />
        </div>
      </>
    )
  }

  // income_statement
  const pct = (v: number | null) => (v === null || v === undefined ? '—' : `${v}%`)
  const steps = [
    { name: 'Дохід', amount: metrics.revenue },
    { name: 'Валовий прибуток', amount: Math.max(metrics.gross_profit, 0) },
    { name: 'Операційний прибуток', amount: Math.max(metrics.operating_profit, 0) },
    { name: 'Чистий результат', amount: Math.max(metrics.net_profit_calc, 0) },
  ]
  return (
    <>
      {summary}
      <div className="grid cols-4" style={{ marginBottom: 16 }}>
        <Stat label="Валова маржа" value={pct(metrics.gross_margin_pct)} />
        <Stat label="Операційна маржа" value={pct(metrics.operating_margin_pct)} />
        <Stat label="Чиста рентабельність" value={pct(metrics.net_margin_pct)} tone={metrics.net_profit_calc < 0 ? 'err' : undefined} />
        <Stat label="Чистий результат" value={money(metrics.net_profit_calc, cur)} tone={metrics.net_profit_calc < 0 ? 'err' : 'ok'} />
      </div>
      <div className="card"><h2>Від доходу до чистого результату</h2><Bars rows={steps} cur={cur} /></div>
    </>
  )
}
