import { useCallback, useEffect, useState } from 'react'

/* C8 SimGate — the approval screen IS the diff. No confirm dialog. */

const api = {
  demo: () => fetch('/api/sim/demo', { method: 'POST' }).then((r) => r.json()),
  simulate: (body) =>
    fetch('/api/sim/simulate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then((r) => r.json()),
  get: (id) => fetch(`/api/sim/${id}`).then((r) => r.json()),
  execute: (id) => fetch(`/api/sim/${id}/execute`, { method: 'POST' }).then((r) => r.json()),
  reject: (id) => fetch(`/api/sim/${id}/reject`, { method: 'POST' }).then((r) => r.json()),
  rollback: (id) => fetch(`/api/sim/${id}/rollback`, { method: 'POST' }).then((r) => r.json()),
  hold: (body) =>
    fetch('/api/sim/hold', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then((r) => r.json()),
  ledger: () => fetch('/api/sim/ledger/state').then((r) => r.json()),
}

const shortKey = (key) => (key ? `${key.slice(0, 8)}…${key.slice(-4)}` : '')

function Badge({ kind, children }) {
  return <span className={`badge badge-${kind}`}>{children}</span>
}

/* Render one deepdiff section (dictionary_item_added, values_changed, …) */
function DiffSection({ title, entries, tone }) {
  if (!entries || entries.length === 0) return null
  const toneColor = {
    add: 'var(--green-ink)',
    change: 'var(--amber-ink)',
    remove: 'var(--red-ink)',
  }[tone]
  return (
    <div className="mb-4">
      <p className="mono text-[11px] uppercase tracking-[0.12em] mb-2" style={{ color: toneColor }}>
        {title}
      </p>
      <div className="space-y-1.5">
        {entries.map(([path, val], i) => (
          <div key={i} className="mono text-[11px] leading-relaxed bg-[var(--canvas)] rounded-lg p-2.5 overflow-x-auto">
            <div className="text-[var(--ink-soft)]">{path}</div>
            <pre className="whitespace-pre-wrap break-all mt-1" style={{ color: toneColor }}>
              {typeof val === 'string' ? val : JSON.stringify(val, null, 2)}
            </pre>
          </div>
        ))}
      </div>
    </div>
  )
}

function DiffView({ diff }) {
  if (!diff || Object.keys(diff).length === 0) {
    return <p className="text-sm text-[var(--ink-soft)]">No changes — identical state.</p>
  }
  const added = Object.entries(diff.dictionary_item_added || {})
  const changed = Object.entries(diff.values_changed || {})
  const removed = Object.entries(diff.dictionary_item_removed || {})
  const iterAdded = Object.entries(diff.iterable_item_added || {})
  return (
    <div>
      <DiffSection title="Added" entries={added} tone="add" />
      <DiffSection title="Added (list entries)" entries={iterAdded} tone="add" />
      <DiffSection title="Changed" entries={changed} tone="change" />
      <DiffSection title="Removed" entries={removed} tone="remove" />
    </div>
  )
}

export default function SimGate() {
  const [seeded, setSeeded] = useState(null)
  const [sim, setSim] = useState(null)
  const [ledger, setLedger] = useState(null)
  const [busy, setBusy] = useState(false)
  const [log, setLog] = useState([])

  const note = (msg) => setLog((l) => [...l, msg])

  const refreshLedger = useCallback(async () => {
    setLedger(await api.ledger())
  }, [])

  useEffect(() => {
    refreshLedger()
  }, [refreshLedger])

  const seed = async () => {
    setBusy(true)
    try {
      const s = await api.demo()
      setSeeded(s)
      note('Seeded BuyerBot with $1,000 signed purchase authority + history.')
      await refreshLedger()
    } finally {
      setBusy(false)
    }
  }

  const simulate = async () => {
    setBusy(true)
    try {
      const record = await api.simulate({
        requester_key: seeded.buyer_key,
        amount: 900.0,
        description: 'Purchase 100 units @ $9',
      })
      setSim(record)
      note(`Simulated $900 purchase → decision "${record.predicted_effects.decision}". Diff below IS the approval.`)
      await refreshLedger()
    } finally {
      setBusy(false)
    }
  }

  const injectHold = async () => {
    setBusy(true)
    try {
      await api.hold({ agent_key: seeded.vendor_key, amount: 200.0 })
      note('VendorBot placed a REAL concurrent $200 hold (between simulate and execute). The simulation is now stale.')
      await refreshLedger()
    } finally {
      setBusy(false)
    }
  }

  const act = async (fn, label) => {
    setBusy(true)
    try {
      const updated = await fn(sim.id)
      setSim(updated)
      note(label)
      await refreshLedger()
    } finally {
      setBusy(false)
    }
  }

  const status = sim?.status
  const pc = sim?.post_check

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[1fr_1.4fr] gap-4 items-start">
      {/* left: controls + ledger */}
      <div className="space-y-4">
        <div className="card p-5 fade-up">
          <p className="mono text-[11px] uppercase tracking-[0.12em] text-[var(--ink-soft)] mb-4">
            Simulate before you act
          </p>
          <div className="flex flex-wrap gap-2.5">
            <button onClick={seed} disabled={busy} className="pressable bg-[#1a1a18] text-white text-sm font-medium px-4 py-2 rounded-md hover:bg-[#333330] disabled:opacity-60">
              {seeded ? 'Re-seed world' : 'Seed the demo'}
            </button>
            <button onClick={simulate} disabled={busy || !seeded} className="pressable border text-sm font-medium px-4 py-2 rounded-md hover:bg-[var(--canvas)] disabled:opacity-50" style={{ borderColor: 'var(--line)' }}>
              Simulate $900 purchase
            </button>
            <button onClick={injectHold} disabled={busy || !seeded || !sim || status !== 'pending'} className="pressable border text-sm font-medium px-4 py-2 rounded-md hover:bg-[var(--amber-bg)] disabled:opacity-50" style={{ borderColor: 'var(--line)' }}>
              Inject concurrent $200 hold
            </button>
          </div>
          {seeded && (
            <p className="mono text-[11px] text-[var(--ink-soft)] mt-3">
              buyer {shortKey(seeded.buyer_key)} · limit ${seeded.limit}
            </p>
          )}
        </div>

        {ledger && (
          <div className="card p-5 fade-up">
            <p className="mono text-[11px] uppercase tracking-[0.12em] text-[var(--ink-soft)] mb-3">
              Live budget ledger
            </p>
            <div className="grid grid-cols-3 gap-3 mb-3">
              {[
                ['Spent', `$${ledger.spent_total}`],
                ['Holds', `$${ledger.active_holds}`],
                ['Committed', `$${ledger.projected_balance}`],
              ].map(([label, v]) => (
                <div key={label} className="rounded-lg bg-[var(--canvas)] px-3 py-2.5">
                  <div className="serif text-2xl font-medium leading-none">{v}</div>
                  <div className="text-[11px] text-[var(--ink-soft)] mt-1.5">{label}</div>
                </div>
              ))}
            </div>
            <div className="space-y-1">
              {ledger.entries.map((e) => (
                <div key={e.id} className="mono text-[11px] flex justify-between text-[var(--ink-soft)]">
                  <span>{e.kind}{e.compensates ? ' ↩' : ''}</span>
                  <span>${e.amount}</span>
                </div>
              ))}
              {ledger.entries.length === 0 && (
                <p className="text-[13px] text-[var(--ink-soft)]">No entries yet.</p>
              )}
            </div>
          </div>
        )}

        {log.length > 0 && (
          <div className="card p-5 fade-up">
            <p className="mono text-[11px] uppercase tracking-[0.12em] text-[var(--ink-soft)] mb-3">Timeline</p>
            <ol className="space-y-1.5">
              {log.map((m, i) => (
                <li key={i} className="text-[13px] flex items-baseline gap-2.5">
                  <span className="mono text-[10px] text-[var(--ink-soft)] shrink-0">{String(i + 1).padStart(2, '0')}</span>
                  <span className="text-[var(--ink)]">{m}</span>
                </li>
              ))}
            </ol>
          </div>
        )}
      </div>

      {/* right: the approval diff */}
      <div className="card p-5 fade-up">
        {!sim && (
          <div className="h-full flex items-center justify-center min-h-[220px]">
            <p className="text-sm text-[var(--ink-soft)] text-center max-w-xs">
              Seed the world, then simulate a purchase. The approval screen will be the
              computed before/after diff — not a confirm dialog.
            </p>
          </div>
        )}

        {sim && (
          <>
            <div className="flex items-center justify-between mb-1">
              <h3 className="serif text-xl font-medium">Review before execution</h3>
              <Badge kind={status === 'escalated' ? 'escalate' : status === 'rolled_back' ? 'refuse' : status === 'executed' ? 'allow' : 'info'}>
                {status}
              </Badge>
            </div>
            <p className="text-xs text-[var(--ink-soft)] mb-4">
              ${sim.intent.amount} {sim.intent.action} by {shortKey(sim.intent.requester_key)} ·
              predicted <span className="font-medium">{sim.predicted_effects.decision}</span> ·
              balance after ${sim.predicted_effects.balance_after} ({sim.predicted_effects.scope_usage_pct}% of limit)
            </p>

            {/* escalation banner */}
            {status === 'escalated' && pc && !pc.ok && (
              <div className="mb-4 rounded-lg p-3.5" style={{ background: 'var(--amber-bg)' }}>
                <p className="text-[13px] font-medium" style={{ color: 'var(--amber-ink)' }}>
                  Safety net fired — simulation under-predicted a side effect.
                </p>
                <p className="mono text-[11px] mt-1" style={{ color: 'var(--amber-ink)' }}>
                  spent ${pc.violations[0].spent} + holds ${pc.violations[0].holds} &gt; limit ${pc.violations[0].limit} (excess ${pc.violations[0].excess})
                </p>
              </div>
            )}

            {/* the diff IS the approval */}
            <div className="mb-5">
              <p className="mono text-[11px] uppercase tracking-[0.12em] text-[var(--ink-soft)] mb-2">
                Before vs after (computed diff of state)
              </p>
              <DiffView diff={sim.fork_diff} />
            </div>

            {/* rollback path, shown pre-approval */}
            <div className="mb-5">
              <p className="mono text-[11px] uppercase tracking-[0.12em] text-[var(--ink-soft)] mb-2">
                Rollback path (compensating action, not an undo)
              </p>
              <div className="space-y-1.5">
                {sim.rollback_preview.entries.map((e, i) => (
                  <div key={i} className="mono text-[11px] bg-[var(--canvas)] rounded-lg p-2.5">
                    <span className="font-medium" style={{ color: 'var(--blue-ink)' }}>{e.kind}</span>
                    {e.amount ? <span> ${e.amount}</span> : null}
                    <span className="text-[var(--ink-soft)]"> — {e.note}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* one-step approve / tweak / reject */}
            <div className="flex flex-wrap gap-2.5 pt-4 border-t" style={{ borderColor: 'var(--line)' }}>
              {status === 'pending' && (
                <>
                  <button onClick={() => act(api.execute, 'Approved & executed — real /api/trust/decide ran, ledger appended.')} disabled={busy} className="pressable bg-[#1a1a18] text-white text-sm font-medium px-4 py-2 rounded-md hover:bg-[#333330] disabled:opacity-60">
                    Approve &amp; execute
                  </button>
                  <button onClick={simulate} disabled={busy} className="pressable border text-sm font-medium px-4 py-2 rounded-md hover:bg-[var(--canvas)]" style={{ borderColor: 'var(--line)' }}>
                    Tweak &amp; re-simulate
                  </button>
                  <button onClick={() => act(api.reject, 'Rejected — nothing executed, no state changed.')} disabled={busy} className="pressable border text-sm font-medium px-4 py-2 rounded-md hover:bg-[var(--red-bg)]" style={{ borderColor: 'var(--line)' }}>
                    Reject
                  </button>
                </>
              )}
              {(status === 'executed' || status === 'escalated') && (
                <button onClick={() => act(api.rollback, 'Rolled back — compensating refund appended + authority revoked. Invariant restored.')} disabled={busy} className="pressable text-sm font-medium px-4 py-2 rounded-md text-white" style={{ background: 'var(--red-ink)' }}>
                  Roll back (compensating refund)
                </button>
              )}
              {status === 'rolled_back' && (
                <Badge kind="allow">invariant restored — full chain in receipt log</Badge>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  )
}
