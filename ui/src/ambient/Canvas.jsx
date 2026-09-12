import { useCallback, useEffect, useState } from 'react'

const api = {
  demo: () => fetch('/api/ambient/demo', { method: 'POST' }).then((r) => r.json()),
  canvas: () => fetch('/api/ambient/canvas').then((r) => (r.ok ? r.json() : null)),
  intents: () => fetch('/api/ambient/intents').then((r) => (r.ok ? r.json() : { intents: [] })),
  cards: () => fetch('/api/ambient/cards').then((r) => r.json()),
  approve: (id) =>
    fetch(`/api/ambient/cards/${id}/approve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ operator: 'operator' }),
    }).then((r) => r.json()),
  reject: (id, note) =>
    fetch(`/api/ambient/cards/${id}/reject`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ operator: 'operator', note }),
    }).then((r) => r.json()),
  stepAgent: (id) =>
    fetch(`/api/tower/agents/${id}/advance`, { method: 'POST' }).then((r) => r.status),
  rogue: () =>
    fetch('/api/tower/scenario/rogue', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ agent_id: 'deploybot' }),
    }).then((r) => r.json()),
  resume: (id) =>
    fetch(`/api/tower/agents/${id}/resume`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ operator: 'operator' }),
    }).then((r) => r.json()),
}

const money = (n) => (n == null ? '—' : `$${Number(n).toLocaleString()}`)

function Badge({ kind, children }) {
  return <span className={`badge badge-${kind}`}>{children}</span>
}

function Dot({ color }) {
  return (
    <span className="inline-block w-1.5 h-1.5 rounded-full" style={{ background: color }} />
  )
}

const STATUS_TONE = {
  running: 'var(--green-ink)',
  awaiting_approval: 'var(--amber-ink, #b45309)',
  paused: 'var(--red-ink)',
  blocked: 'var(--amber-ink, #b45309)',
  killed: 'var(--red-ink)',
}

const KIND_LABEL = {
  deploy_needs_review: 'Deploy needs review',
  drift_contain: 'Agent drift — contain',
  restock_needed: 'Restock needed',
  budget_risk: 'Budget risk',
}

/* Reject reasons as one-tap choices — no free-text input anywhere in this tab. */
const REJECT_REASONS = [
  'Not the right call',
  'I already handled this',
  'Wrong priority right now',
]

export default function Canvas({ onCompare }) {
  const [seeded, setSeeded] = useState(false)
  const [running, setRunning] = useState(false)
  const [snap, setSnap] = useState(null)
  const [intents, setIntents] = useState([])
  const [history, setHistory] = useState([])
  const [rejectNote, setRejectNote] = useState(REJECT_REASONS[0])

  const refresh = useCallback(async () => {
    if (!seeded) return
    const [c, i, h] = await Promise.all([api.canvas(), api.intents(), api.cards()])
    if (c) setSnap(c)
    setIntents(i.intents || [])
    setHistory(h.cards || [])
  }, [seeded])

  useEffect(() => {
    refresh()
    const t = setInterval(refresh, 3000)
    return () => clearInterval(t)
  }, [refresh])

  const seed = async () => {
    setRunning(true)
    try {
      await api.demo()
      setSeeded(true)
      await refresh()
    } finally {
      setRunning(false)
    }
  }

  const act = async (fn) => {
    setRunning(true)
    try {
      await fn()
      await refresh()
    } finally {
      setRunning(false)
    }
  }

  const card = snap?.card
  const mode = snap?.mode ?? 'calm'
  const fleet = snap?.fleet_summary ?? {}
  const alert = mode === 'card' || mode === 'manual'

  return (
    <div className="space-y-4">
      {/* controls — verbs, not queries */}
      <div className="card p-5 fade-up">
        <div className="flex flex-wrap items-center gap-3">
          <button
            onClick={seed}
            disabled={running}
            className="pressable bg-[#1a1a18] text-white text-sm font-medium px-4 py-2 rounded-md hover:bg-[#333330] disabled:opacity-60"
          >
            {seeded ? 'Re-bind canvas' : 'Start the shift'}
          </button>
          <button
            onClick={() => act(() => api.stepAgent('deploybot'))}
            disabled={running || !seeded}
            className="pressable text-sm font-medium px-4 py-2 rounded-md border hover:bg-[var(--canvas)] disabled:opacity-50"
            style={{ borderColor: 'var(--line)' }}
          >
            ▶ Step DeployBot
          </button>
          <button
            onClick={() => act(() => api.stepAgent('restockbot'))}
            disabled={running || !seeded}
            className="pressable text-sm font-medium px-4 py-2 rounded-md border hover:bg-[var(--canvas)] disabled:opacity-50"
            style={{ borderColor: 'var(--line)' }}
          >
            ▶ Step RestockBot
          </button>
          <button
            onClick={() => act(api.rogue)}
            disabled={running || !seeded}
            className="pressable text-sm font-medium px-4 py-2 rounded-md border hover:bg-[var(--red-bg)] disabled:opacity-50"
            style={{ borderColor: 'var(--line)' }}
          >
            ☠ Rogue objective
          </button>
          {onCompare && (
            <button
              onClick={onCompare}
              className="pressable ml-auto text-sm font-medium px-4 py-2 rounded-md border hover:bg-[var(--canvas)]"
              style={{ borderColor: 'var(--line)' }}
            >
              ⇄ What this replaces
            </button>
          )}
        </div>
      </div>

      {/* the ambient field — the interface. Empty by default, on purpose. */}
      <div
        className="card fade-up transition-colors"
        style={{
          padding: '2.5rem 1.5rem',
          textAlign: 'center',
          background: alert ? 'var(--amber-bg, #fef3c7)' : 'var(--card-bg, var(--canvas))',
          borderColor: 'var(--line)',
        }}
      >
        <div className="flex items-center justify-center gap-2 mb-3">
          <Dot color={alert ? 'var(--amber-ink, #b45309)' : 'var(--green-ink)'} />
          <span className="mono text-[11px] uppercase tracking-[0.12em] text-[var(--ink-soft)]">
            {alert ? 'Attention requested' : 'Ambient'}
          </span>
        </div>
        <p className="serif text-2xl md:text-3xl font-medium leading-snug max-w-xl mx-auto">
          {snap?.ambient ?? 'The canvas is watching the fleet. Nothing needs you yet.'}
        </p>
        <div className="mt-4 flex items-center justify-center gap-4 text-[12px] text-[var(--ink-soft)]">
          {Object.entries(fleet).map(([id, status]) => (
            <span key={id} className="flex items-center gap-1.5">
              <Dot color={STATUS_TONE[status] ?? 'var(--ink-soft)'} />
              {id}
            </span>
          ))}
        </div>
      </div>

      {/* the ONE decision card — the whole point: at most one thing on screen */}
      {card && (
        <div className="card p-6 fade-up" style={{ borderColor: 'var(--ink)' }}>
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2.5">
              <Badge kind={card.hypothesis.demoted ? 'defer' : 'escalate'}>
                {KIND_LABEL[card.hypothesis.kind] ?? card.hypothesis.kind}
              </Badge>
              {card.hypothesis.demoted && (
                <Badge kind="defer">demoted — you corrected this before</Badge>
              )}
            </div>
            <span className="mono text-[11px] text-[var(--ink-soft)]">
              confidence {Math.round(card.hypothesis.confidence * 100)}%
              {card.hypothesis.demoted &&
                ` (was ${Math.round(card.hypothesis.base_confidence * 100)}%)`}
              {' · '}narrator: {card.brain}
            </span>
          </div>

          <h3 className="serif text-xl font-medium mb-1">{card.rationale}</h3>
          <p className="text-[13px] text-[var(--ink-soft)] mb-4">
            {card.action.description} {card.action.amount ? `· ${money(card.action.amount)}` : ''}
          </p>

          {/* evidence chain — why this surfaced */}
          <div className="rounded-lg bg-[var(--canvas)] p-3.5 mb-4">
            <p className="mono text-[10px] uppercase tracking-[0.12em] text-[var(--ink-soft)] mb-2">
              Why this surfaced
            </p>
            <ul className="space-y-1">
              {card.hypothesis.evidence.map((e, i) => (
                <li key={i} className="text-[12px] text-[var(--ink)] flex gap-2">
                  <span className="mono text-[10px] text-[var(--ink-soft)]">{i + 1}.</span>
                  {e}
                </li>
              ))}
            </ul>
            {card.hypothesis.missing.length > 0 && (
              <p className="text-[11px] text-[var(--ink-soft)] mt-2">
                Unknowns: {card.hypothesis.missing.join('; ')}
              </p>
            )}
          </div>

          {/* pre-computed before/after — the approval IS the diff */}
          {card.sim && card.sim.predicted_effects && (
            <div className="rounded-lg border p-3.5 mb-4" style={{ borderColor: 'var(--line)' }}>
              <p className="mono text-[10px] uppercase tracking-[0.12em] text-[var(--ink-soft)] mb-2">
                Pre-simulated outcome (SimCore fork, live state untouched)
              </p>
              <div className="grid grid-cols-3 gap-2 text-[13px]">
                <div className="rounded-lg bg-[var(--canvas)] px-3 py-2">
                  <span className="text-[var(--ink-soft)]">Decision</span>{' '}
                  <span className="font-medium">{card.sim.predicted_effects.decision}</span>
                </div>
                <div className="rounded-lg bg-[var(--canvas)] px-3 py-2">
                  <span className="text-[var(--ink-soft)]">Balance after</span>{' '}
                  <span className="font-medium">
                    {money(card.sim.predicted_effects.balance_after)}
                  </span>
                </div>
                <div className="rounded-lg bg-[var(--canvas)] px-3 py-2">
                  <span className="text-[var(--ink-soft)]">Limit use</span>{' '}
                  <span className="font-medium">
                    {card.sim.predicted_effects.scope_usage_pct}%
                  </span>
                </div>
              </div>
              {card.sim.rollback_preview?.entries?.length > 0 && (
                <p className="text-[11px] text-[var(--ink-soft)] mt-2">
                  Rollback pre-computed:{' '}
                  {card.sim.rollback_preview.entries.map((e) => e.kind).join(' + ')} — appended,
                  never undone.
                </p>
              )}
            </div>
          )}

          {/* the three verbs. No keyboard. */}
          <div className="flex flex-wrap items-center gap-2.5">
            <button
              onClick={() => act(() => api.approve(card.id))}
              disabled={running}
              className="pressable bg-[#1a1a18] text-white text-sm font-medium px-5 py-2.5 rounded-md hover:bg-[#333330] disabled:opacity-60"
            >
              Approve &amp; execute
            </button>
            {REJECT_REASONS.map((reason) => (
              <button
                key={reason}
                onMouseEnter={() => setRejectNote(reason)}
                onClick={() => act(() => api.reject(card.id, rejectNote === reason ? reason : reason))}
                disabled={running}
                className="pressable text-sm font-medium px-4 py-2.5 rounded-md border hover:bg-[var(--red-bg)] disabled:opacity-50"
                style={{ borderColor: 'var(--line)' }}
              >
                ✕ {reason}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* manual fallback — the interface admits it kept guessing wrong */}
      {mode === 'manual' && !card && (
        <div className="card p-6 fade-up">
          <Badge kind="defer">Manual mode</Badge>
          <h3 className="serif text-xl font-medium mt-2 mb-2">
            I guessed wrong twice — here is the raw picture.
          </h3>
          <p className="text-[13px] text-[var(--ink-soft)] mb-3">
            Exhausted: {snap.exhausted_kinds.join(', ')}. No more cards of that kind. The last
            events, unfiltered:
          </p>
          <div className="space-y-1.5 max-h-56 overflow-y-auto">
            {(snap.raw_events || []).map((e, i) => (
              <div key={i} className="text-[12px] flex items-baseline gap-2.5">
                <span className="mono text-[10px] text-[var(--ink-soft)] shrink-0">
                  {e.agent_id} · seq {e.seq}
                </span>
                <span className="text-[var(--ink)]">{e.kind}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 items-start">
        {/* what the interface chose NOT to show — the restraint is the product */}
        <div className="card p-5 fade-up">
          <p className="mono text-[11px] uppercase tracking-[0.12em] text-[var(--ink-soft)] mb-4">
            Inferred, but deliberately not shown ({intents.filter((i) => !card || i.kind !== card.hypothesis.kind).length})
          </p>
          {intents.filter((i) => !card || i.kind !== card.hypothesis.kind).length === 0 && (
            <p className="text-sm text-[var(--ink-soft)]">
              Nothing else even rose to consideration. This list is the proof the interface
              decides what not to interrupt you with.
            </p>
          )}
          <div className="space-y-2">
            {intents
              .filter((i) => !card || i.kind !== card.hypothesis.kind)
              .map((h) => (
                <div
                  key={h.id}
                  className="flex items-center justify-between px-3.5 py-2.5 rounded-lg border"
                  style={{ borderColor: 'var(--line)' }}
                >
                  <div>
                    <div className="text-sm">{KIND_LABEL[h.kind] ?? h.kind}</div>
                    <div className="text-[11px] text-[var(--ink-soft)]">{h.target}</div>
                  </div>
                  <span className="mono text-[11px] text-[var(--ink-soft)]">
                    {Math.round(h.confidence * 100)}%{h.demoted ? ' ↓' : ''} — below threshold
                  </span>
                </div>
              ))}
          </div>
        </div>

        {/* card history — the receipted arc of surfaced/approved/rejected */}
        <div className="card p-5 fade-up">
          <p className="mono text-[11px] uppercase tracking-[0.12em] text-[var(--ink-soft)] mb-4">
            Card history — every guess, receipted
          </p>
          {history.length === 0 && (
            <p className="text-sm text-[var(--ink-soft)]">No cards yet. Step the fleet.</p>
          )}
          <div className="space-y-2.5">
            {[...history].reverse().map((h) => (
              <div key={h.id + h.state} className="text-[13px] flex items-center justify-between">
                <span className="text-[var(--ink)]">
                  {KIND_LABEL[h.hypothesis.kind] ?? h.hypothesis.kind}
                  <span className="text-[var(--ink-soft)]"> · {h.hypothesis.target}</span>
                </span>
                <Badge
                  kind={
                    h.state === 'approved' || h.state === 'edited'
                      ? 'allow'
                      : h.state === 'rejected'
                        ? 'refuse'
                        : h.state === 'manual'
                          ? 'defer'
                          : 'escalate'
                  }
                >
                  {h.state}
                </Badge>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
