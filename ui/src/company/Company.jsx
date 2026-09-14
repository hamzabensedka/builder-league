import { useCallback, useEffect, useState } from 'react'

const api = {
  demo: (scenario) =>
    fetch('/api/company/demo', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scenario }),
    }).then((r) => r.json()),
  advance: () => fetch('/api/company/advance', { method: 'POST' }).then((r) => r.json()),
  state: () => fetch('/api/company/state').then((r) => r.json()),
  kpis: () => fetch('/api/company/kpis').then((r) => r.json()),
  inbox: () => fetch('/api/company/inbox').then((r) => r.json()),
  events: () => fetch('/api/company/events').then((r) => r.json()),
  replay: (day) => fetch(`/api/company/replay?day=${day}`).then((r) => r.json()),
  resolve: (id, resolution) =>
    fetch(`/api/company/inbox/${id}/resolve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ resolution }),
    }).then((r) => r.json()),
  crunch: () => fetch('/api/company/scenario/cash-crunch', { method: 'POST' }).then((r) => r.json()),
  rogue: () => fetch('/api/company/scenario/rogue-sales', { method: 'POST' }).then((r) => r.json()),
}

const ROLES = [
  ['salesbot', 'SalesBot', 'pipeline · quotes · invoices'],
  ['opsbot', 'OpsBot', 'inventory · purchase orders'],
  ['financebot', 'FinanceBot', 'AR/AP · budget · freezes'],
  ['chiefofstaff', 'ChiefOfStaff', 'cross-functional directives'],
]

function Badge({ kind, children }) {
  return <span className={`badge badge-${kind}`}>{children}</span>
}

function Kpi({ label, value, tone }) {
  return (
    <div className="rounded-lg bg-[var(--canvas)] px-3 py-2.5">
      <div className={`serif text-2xl font-medium leading-none ${tone || ''}`}>{value}</div>
      <div className="text-[11px] text-[var(--ink-soft)] mt-1.5">{label}</div>
    </div>
  )
}

const money = (n) => `$${Number(n).toLocaleString()}`

const KIND_LABEL = {
  lead_arrived: 'lead arrived',
  quote_sent: 'quote sent',
  deal_won: 'deal won',
  deal_lost: 'deal lost',
  invoice_issued: 'invoice issued',
  invoice_collected: 'invoice collected',
  po_raised: 'PO raised',
  po_received: 'PO received',
  bill_received: 'bill received',
  bill_paid: 'bill paid',
  spend_frozen: 'spend frozen',
  spend_unfrozen: 'spend unfrozen',
  escalation_raised: 'escalation raised',
  escalation_resolved: 'escalation resolved',
  directive_proposed: 'directive proposed',
  directive_applied: 'directive applied',
  directive_rejected: 'directive rejected',
  role_paused: 'role paused',
  role_restored: 'role restored',
  day_ticked: 'day ticked',
}

export default function Company() {
  const [seeded, setSeeded] = useState(false)
  const [running, setRunning] = useState(false)
  const [kpis, setKpis] = useState(null)
  const [state, setState] = useState(null)
  const [inbox, setInbox] = useState([])
  const [events, setEvents] = useState([])
  const [beats, setBeats] = useState([])
  const [brain, setBrain] = useState(null)
  const [replayDay, setReplayDay] = useState(null)
  const [replayState, setReplayState] = useState(null)
  const [resolution, setResolution] = useState({})

  const refresh = useCallback(async () => {
    if (!seeded) return
    const [k, s, i, e] = await Promise.all([
      api.kpis(), api.state(), api.inbox(), api.events(),
    ])
    setKpis(k)
    setState(s)
    setInbox(i.inbox)
    setEvents(e.events)
  }, [seeded])

  useEffect(() => {
    refresh()
    const t = setInterval(refresh, 3000)
    return () => clearInterval(t)
  }, [refresh])

  const seed = async () => {
    setRunning(true)
    try {
      const out = await api.demo('normal')
      setSeeded(true)
      setBeats(out.beats || [])
      await refresh()
    } finally {
      setRunning(false)
    }
  }

  const advance = async () => {
    setRunning(true)
    try {
      const out = await api.advance()
      setBeats(out.beats || [])
      setBrain(out.chief_brain)
      await refresh()
    } finally {
      setRunning(false)
    }
  }

  const lever = async (fn) => {
    setRunning(true)
    try {
      const out = await fn()
      if (out?.beats) setBeats(out.beats)
      await refresh()
    } finally {
      setRunning(false)
    }
  }

  const doReplay = async (day) => {
    setReplayDay(day)
    setReplayState(await api.replay(day))
  }

  const resolve = async (id) => {
    await api.resolve(id, resolution[id] || 'approved')
    setResolution((r) => ({ ...r, [id]: '' }))
    await refresh()
  }

  const paused = new Set(state?.roles_paused || [])
  const maxDay = kpis?.day ?? 0

  return (
    <div className="space-y-4">
      {/* controls */}
      <div className="card p-5 fade-up">
        <div className="flex flex-wrap items-center gap-3">
          <button
            onClick={seed}
            disabled={running}
            className="pressable bg-[#1a1a18] text-white text-sm font-medium px-4 py-2 rounded-md hover:bg-[#333330] disabled:opacity-60"
          >
            {seeded ? 'Re-seed Northwind' : 'Seed Northwind Components'}
          </button>
          <button
            onClick={advance}
            disabled={running || !seeded}
            className="pressable text-sm font-medium px-4 py-2 rounded-md border hover:bg-[var(--canvas)] disabled:opacity-50"
            style={{ borderColor: 'var(--line)' }}
          >
            ▶ Run a day
          </button>
          <button
            onClick={() => lever(api.crunch)}
            disabled={!seeded}
            className="pressable text-sm font-medium px-4 py-2 rounded-md border hover:bg-[var(--amber-bg)] disabled:opacity-50"
            style={{ borderColor: 'var(--line)' }}
          >
            ⚡ Cash crunch
          </button>
          <button
            onClick={() => lever(api.rogue)}
            disabled={!seeded}
            className="pressable text-sm font-medium px-4 py-2 rounded-md border hover:bg-[var(--red-bg)] disabled:opacity-50"
            style={{ borderColor: 'var(--line)' }}
          >
            ☠ Rogue sales
          </button>
          {brain && (
            <span className="mono text-[11px] text-[var(--ink-soft)] ml-auto">
              chief brain: <span className="text-[var(--ink)]">{brain}</span>
            </span>
          )}
        </div>
        {beats.length > 0 && (
          <ol className="mt-4 space-y-1.5">
            {beats.map((b, i) => (
              <li key={i} className="text-[13px] flex items-baseline gap-2.5">
                <span className="mono text-[10px] text-[var(--ink-soft)] shrink-0">
                  {String(i + 1).padStart(2, '0')}
                </span>
                <span className="text-[var(--ink)]">{b.label}</span>
                {b.decision && <Badge kind={b.decision}>{b.decision}</Badge>}
              </li>
            ))}
          </ol>
        )}
      </div>

      {/* KPI ticker */}
      {kpis && (
        <div className="card p-5 fade-up">
          <p className="mono text-[11px] uppercase tracking-[0.12em] text-[var(--ink-soft)] mb-4">
            Day {kpis.day} · company KPIs {kpis.spend_frozen && '· spend frozen'}
          </p>
          <div className="grid grid-cols-3 md:grid-cols-6 gap-3">
            <Kpi label="Revenue" value={money(kpis.revenue)} />
            <Kpi label="Cash" value={money(kpis.cash)} />
            <Kpi
              label="Runway (days)"
              value={kpis.runway_days}
              tone={kpis.runway_days < 21 ? 'text-[var(--red-ink)]' : ''}
            />
            <Kpi label="Backlog (units)" value={kpis.backlog_units} />
            <Kpi label="Churn" value={`${Math.round(kpis.churn * 100)}%`} />
            <Kpi label="Margin" value={`${Math.round(kpis.margin * 100)}%`} />
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-[1fr_1.3fr] gap-4 items-start">
        {/* org view */}
        <div className="card p-5 fade-up">
          <p className="mono text-[11px] uppercase tracking-[0.12em] text-[var(--ink-soft)] mb-4">
            The four roles
          </p>
          <div className="space-y-2">
            {ROLES.map(([id, name, job]) => (
              <div
                key={id}
                className="flex items-center justify-between px-3.5 py-3 rounded-lg border"
                style={{ borderColor: 'var(--line)' }}
              >
                <div>
                  <div className="text-sm font-medium">{name}</div>
                  <div className="text-[11px] text-[var(--ink-soft)]">{job}</div>
                </div>
                {paused.has(id) ? (
                  <Badge kind="refuse">paused</Badge>
                ) : (
                  <Badge kind="allow">active</Badge>
                )}
              </div>
            ))}
          </div>

          {/* books */}
          {state && (
            <div className="mt-5 pt-4 border-t" style={{ borderColor: 'var(--line)' }}>
              <p className="mono text-[11px] uppercase tracking-[0.12em] text-[var(--ink-soft)] mb-3">
                The books
              </p>
              <div className="grid grid-cols-2 gap-2 text-[13px]">
                <div className="rounded-lg bg-[var(--canvas)] px-3 py-2">
                  <span className="text-[var(--ink-soft)]">Inventory</span>{' '}
                  <span className="font-medium">{state.inventory} units</span>
                </div>
                <div className="rounded-lg bg-[var(--canvas)] px-3 py-2">
                  <span className="text-[var(--ink-soft)]">Open pipeline</span>{' '}
                  <span className="font-medium">{Object.keys(state.pipeline).length}</span>
                </div>
                <div className="rounded-lg bg-[var(--canvas)] px-3 py-2">
                  <span className="text-[var(--ink-soft)]">AR open</span>{' '}
                  <span className="font-medium">{Object.keys(state.ar).length}</span>
                </div>
                <div className="rounded-lg bg-[var(--canvas)] px-3 py-2">
                  <span className="text-[var(--ink-soft)]">AP open</span>{' '}
                  <span className="font-medium">{Object.keys(state.ap).length}</span>
                </div>
              </div>
            </div>
          )}

          {/* replay scrubber */}
          {seeded && (
            <div className="mt-5 pt-4 border-t" style={{ borderColor: 'var(--line)' }}>
              <p className="mono text-[11px] uppercase tracking-[0.12em] text-[var(--ink-soft)] mb-2">
                Replay a day
              </p>
              <input
                type="range"
                min="0"
                max={maxDay}
                value={replayDay ?? maxDay}
                onChange={(e) => doReplay(Number(e.target.value))}
                className="w-full"
              />
              {replayState && replayDay !== null && (
                <p className="text-[12px] text-[var(--ink-soft)] mt-2">
                  Day {replayDay}: cash {money(replayState.cash)} · inventory{' '}
                  {replayState.inventory} · pipeline {Object.keys(replayState.pipeline).length}
                </p>
              )}
            </div>
          )}
        </div>

        <div className="space-y-4">
          {/* human inbox */}
          <div className="card p-5 fade-up">
            <p className="mono text-[11px] uppercase tracking-[0.12em] text-[var(--ink-soft)] mb-4">
              Human inbox {inbox.length > 0 && `(${inbox.length})`}
            </p>
            {inbox.length === 0 && (
              <p className="text-sm text-[var(--ink-soft)]">
                Nothing needs a human. The company is running itself.
              </p>
            )}
            <div className="space-y-3">
              {inbox.map((e) => (
                <div key={e.id} className="rounded-lg border p-3.5" style={{ borderColor: 'var(--line)' }}>
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-sm font-medium">{e.summary}</span>
                    <Badge kind="escalate">{e.actor}</Badge>
                  </div>
                  <p className="text-[12px] text-[var(--ink-soft)] mb-2.5">{e.detail}</p>
                  <div className="flex gap-2">
                    <input
                      value={resolution[e.id] || ''}
                      onChange={(ev) =>
                        setResolution((r) => ({ ...r, [e.id]: ev.target.value }))
                      }
                      placeholder="answer (e.g. approved)"
                      className="flex-1 text-[13px] px-3 py-1.5 rounded-md border bg-transparent"
                      style={{ borderColor: 'var(--line)' }}
                    />
                    <button
                      onClick={() => resolve(e.id)}
                      className="pressable bg-[#1a1a18] text-white text-[13px] font-medium px-3.5 py-1.5 rounded-md"
                    >
                      Resolve
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* event timeline */}
          <div className="card p-5 fade-up">
            <p className="mono text-[11px] uppercase tracking-[0.12em] text-[var(--ink-soft)] mb-4">
              The spine — every action on one shared record
            </p>
            <div className="space-y-1.5 max-h-80 overflow-y-auto">
              {[...events].reverse().slice(0, 60).map((e) => (
                <div key={e.id} className="text-[12px] flex items-baseline gap-2.5">
                  <span className="mono text-[10px] text-[var(--ink-soft)] shrink-0 w-14">
                    d{e.day} · {String(e.seq).padStart(3, '0')}
                  </span>
                  <span className="text-[var(--ink-soft)] shrink-0">{e.actor}</span>
                  <span className="text-[var(--ink)]">
                    {KIND_LABEL[e.kind] ?? e.kind}
                    {e.payload?.amount ? ` · ${money(e.payload.amount)}` : ''}
                  </span>
                </div>
              ))}
              {events.length === 0 && (
                <p className="text-sm text-[var(--ink-soft)]">
                  Seed the company, then run a day.
                </p>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
