import { useCallback, useEffect, useRef, useState } from 'react'

const api = {
  demo: () => fetch('/api/adaptive/demo', { method: 'POST' }).then((r) => r.json()),
  scenarios: () => fetch('/api/adaptive/scenarios').then((r) => r.json()),
  start: (scenario, mode) =>
    fetch('/api/adaptive/runs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scenario, mode }),
    }).then((r) => r.json()),
  inject: (runId, kind, payload) =>
    fetch(`/api/adaptive/runs/${runId}/events`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ kind, payload }),
    }).then((r) => r.json()),
  advance: (runId) =>
    fetch(`/api/adaptive/runs/${runId}/advance`, { method: 'POST' }).then((r) => r.json()),
  runToEnd: (runId) =>
    fetch(`/api/adaptive/runs/${runId}/run-to-end`, { method: 'POST' }).then((r) => r.json()),
  get: (runId) => fetch(`/api/adaptive/runs/${runId}`).then((r) => r.json()),
}

const STATUS_STYLE = {
  running: ['var(--blue-ink, #1d4ed8)', 'running'],
  completed: ['var(--green-ink)', 'goal achieved'],
  escalated: ['var(--red-ink)', 'escalated to human'],
  failed: ['var(--red-ink)', 'failed'],
  awaiting_human: ['var(--amber-ink, #b45309)', 'awaiting human'],
}

function Badge({ kind, children }) {
  return <span className={`badge badge-${kind}`}>{children}</span>
}

function shortId(id) {
  return id ? id.slice(0, 8) : ''
}

/* ------------------------------------------------------------------ */

function StepTimeline({ plan, stepLog }) {
  if (!plan) return null
  const byId = Object.fromEntries((stepLog || []).map((e) => [e.step_id, e]))
  return (
    <div className="space-y-1.5">
      {plan.steps.map((s) => {
        const log = byId[s.id]
        const dot =
          s.status === 'done'
            ? 'var(--green-ink)'
            : s.status === 'pending'
              ? 'var(--ink-soft)'
              : 'var(--red-ink)'
        return (
          <div key={s.id} className="flex items-start gap-2.5">
            <span
              className="mt-1.5 inline-block w-1.5 h-1.5 rounded-full shrink-0"
              style={{ background: dot }}
            />
            <div className="min-w-0">
              <div className="text-[13px] font-medium">
                {s.index + 1}. {s.action.replaceAll('_', ' ')}
                {s.params.supplier && (
                  <span className="text-[var(--ink-soft)] font-normal"> · {s.params.supplier}</span>
                )}
                {s.params.qty != null && (
                  <span className="text-[var(--ink-soft)] font-normal"> × {s.params.qty}</span>
                )}
                {s.params.total != null && (
                  <span className="mono text-[11px] text-[var(--ink-soft)]"> ${s.params.total}</span>
                )}
              </div>
              {log && (
                <div className="text-[11px] text-[var(--ink-soft)] leading-snug">
                  {log.gate_outcome !== 'not_gated' && (
                    <span className="mono">gate:{log.gate_outcome} · </span>
                  )}
                  {log.result}
                </div>
              )}
              {!log && s.status === 'pending' && s.assumptions.length > 0 && (
                <div className="text-[10px] mono text-[var(--ink-soft)] opacity-70">
                  assumes: {s.assumptions.map((a) => a.statement).join(' · ')}
                </div>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}

function RevisionCard({ rev }) {
  const verdictKind = {
    allowed: 'allow',
    damped: 'defer',
    escalate_budget: 'escalate',
    escalate_oscillation: 'escalate',
  }[rev.damping_verdict] || 'info'
  return (
    <div className="rounded-lg border p-3.5 fade-up" style={{ borderColor: 'var(--line)' }}>
      <div className="flex items-center justify-between mb-2">
        <span className="mono text-[10px] uppercase tracking-[0.12em] text-[var(--ink-soft)]">
          revision {rev.from_version} → {rev.to_version ?? '—'}
        </span>
        <Badge kind={verdictKind}>{rev.damping_verdict.replace('_', ' ')}</Badge>
      </div>
      <p className="serif text-[15px] leading-snug mb-2.5">
        “{rev.rationale}”
      </p>
      {rev.contradictions.map((c) => (
        <div key={c.assumption_id} className="text-[11px] mb-1.5 leading-snug">
          <span className="mono text-[var(--red-ink)]">✗ {c.statement}</span>
          <span className="text-[var(--ink-soft)]"> — expected {c.expected}, observed {c.observed}</span>
        </div>
      ))}
      {rev.plan_diff && (
        <pre className="mono text-[10px] bg-[var(--canvas)] rounded p-2 mt-2 overflow-x-auto whitespace-pre-wrap">
          {rev.plan_diff.summary}
        </pre>
      )}
      {rev.sim_preview?.predicted_effects && (
        <div className="text-[10px] mono text-[var(--ink-soft)] mt-2">
          sim preview: balance after ${rev.sim_preview.predicted_effects.balance_after} ·
          scope {rev.sim_preview.predicted_effects.scope_usage_pct}% (fork, never committed)
        </div>
      )}
      <div className="text-[10px] mono text-[var(--ink-soft)] mt-2 opacity-70">
        damping: {rev.damping_reason} · receipt {shortId(rev.receipt_id)}…
      </div>
    </div>
  )
}

function RunColumn({ title, run, accent, onAdvance, onInject, scenarios, busy }) {
  const status = run ? STATUS_STYLE[run.status] || STATUS_STYLE.running : null
  const spec = run && scenarios.find((s) => s.id === run.scenario)
  return (
    <div className="card p-5 fade-up">
      <div className="flex items-center justify-between mb-4">
        <p className="mono text-[11px] uppercase tracking-[0.12em]" style={{ color: accent }}>
          {title}
        </p>
        {run && (
          <span className="badge" style={{ color: status[0], borderColor: status[0] }}>
            {status[1]}
          </span>
        )}
      </div>
      {!run && <p className="text-sm text-[var(--ink-soft)]">No run yet.</p>}
      {run && (
        <>
          <div className="mb-4">
            <div className="mono text-[10px] text-[var(--ink-soft)] mb-2">
              plan v{run.plan?.version} · revisions {run.damping.revision_count}/
              {run.damping.max_revisions} · budget ${run.budget.committed.toFixed(2)} / $
              {run.budget.limit.toFixed(2)}
            </div>
            <StepTimeline plan={run.plan} stepLog={run.step_log} />
          </div>

          {run.mode === 'adaptive' && run.status === 'running' && (
            <div className="flex flex-wrap gap-2 mb-4">
              {(spec?.injectors || []).map((inj) => (
                <button
                  key={inj.label}
                  disabled={busy}
                  onClick={() => onInject(run.id, inj.kind, inj.payload)}
                  className="pressable text-[11px] font-medium px-3 py-1.5 rounded-md border hover:bg-[var(--canvas)] disabled:opacity-50"
                  style={{ borderColor: 'var(--line)' }}
                >
                  ⚡ {inj.label}
                </button>
              ))}
              <button
                disabled={busy}
                onClick={() => onAdvance(run.id, false)}
                className="pressable text-[11px] font-medium px-3 py-1.5 rounded-md bg-[#1a1a18] text-white hover:bg-[#333330] disabled:opacity-50"
              >
                Advance step →
              </button>
              <button
                disabled={busy}
                onClick={() => onAdvance(run.id, true)}
                className="pressable text-[11px] font-medium px-3 py-1.5 rounded-md border hover:bg-[var(--canvas)] disabled:opacity-50"
                style={{ borderColor: 'var(--line)' }}
              >
                Run to end
              </button>
            </div>
          )}
          {run.mode === 'baseline' && run.status === 'running' && (
            <div className="flex gap-2 mb-4">
              <button
                disabled={busy}
                onClick={() => onAdvance(run.id, true)}
                className="pressable text-[11px] font-medium px-3 py-1.5 rounded-md bg-[#1a1a18] text-white hover:bg-[#333330] disabled:opacity-50"
              >
                Run baseline (blind) →
              </button>
            </div>
          )}

          {run.revisions?.length > 0 && (
            <div className="space-y-2.5 mt-4">
              <p className="mono text-[10px] uppercase tracking-[0.12em] text-[var(--ink-soft)]">
                I changed my mind because…
              </p>
              {run.revisions.map((rev) => (
                <RevisionCard key={rev.id} rev={rev} />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}

/* ------------------------------------------------------------------ */

export default function AdaptiveRun() {
  const [seed, setSeed] = useState(null)
  const [scenarios, setScenarios] = useState([])
  const [scenario, setScenario] = useState('price_spike')
  const [adaptive, setAdaptive] = useState(null)
  const [baseline, setBaseline] = useState(null)
  const [busy, setBusy] = useState(false)
  const [beats, setBeats] = useState(null)
  const pollRef = useRef(null)

  useEffect(() => {
    api.scenarios().then((r) => setScenarios(r.scenarios))
  }, [])

  const stopPoll = () => {
    if (pollRef.current) clearInterval(pollRef.current)
    pollRef.current = null
  }
  useEffect(() => stopPoll, [])

  const seedDemo = async () => {
    setBusy(true)
    try {
      const result = await api.demo()
      setSeed(result)
      setBeats(result.beats)
    } finally {
      setBusy(false)
    }
  }

  const startPair = async () => {
    setBusy(true)
    stopPoll()
    try {
      if (!seed) await seedDemo()
      const [a, b] = await Promise.all([
        api.start(scenario, 'adaptive'),
        api.start(scenario, 'baseline'),
      ])
      setAdaptive(a)
      setBaseline(b)
    } finally {
      setBusy(false)
    }
  }

  const refreshRun = useCallback(async (runId, which) => {
    const r = await api.get(runId)
    if (which === 'adaptive') setAdaptive(r)
    else setBaseline(r)
    return r
  }, [])

  const inject = async (runId, kind, payload) => {
    setBusy(true)
    try {
      // the world event lands on BOTH runs' shared stream — the baseline just
      // never looks at it
      await api.inject(runId, kind, payload)
      await refreshRun(runId, 'adaptive')
    } finally {
      setBusy(false)
    }
  }

  const advance = async (runId, toEnd, which = 'adaptive') => {
    setBusy(true)
    try {
      const r = toEnd ? await api.runToEnd(runId) : await api.advance(runId)
      if (which === 'adaptive') setAdaptive(r)
      else setBaseline(r)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <div className="card p-5 mb-4 fade-up">
        <p className="text-[15px] text-[var(--ink-soft)] leading-relaxed max-w-3xl mb-4">
          RestockBot runs a multi-step procurement plan against{' '}
          <span className="text-[var(--ink)] font-medium">real shared state</span> — the budget
          ledger, signed authority, the decision gate. World changes arrive as events. Every plan
          step declares its assumptions; when an event contradicts one, the agent re-plans and
          shows you exactly why. The baseline column runs the same scenario with adaptation off.
        </p>
        <div className="flex flex-wrap items-center gap-3">
          <select
            value={scenario}
            onChange={(e) => setScenario(e.target.value)}
            className="text-sm border rounded-md px-3 py-2 bg-transparent"
            style={{ borderColor: 'var(--line)' }}
          >
            {scenarios.map((s) => (
              <option key={s.id} value={s.id}>
                {s.label}
              </option>
            ))}
          </select>
          <button
            onClick={startPair}
            disabled={busy}
            className="pressable bg-[#1a1a18] text-white text-sm font-medium px-5 py-2.5 rounded-md hover:bg-[#333330] disabled:opacity-60"
          >
            {busy ? 'Working…' : 'Start adaptive + baseline'}
          </button>
          {!seed && (
            <span className="text-[12px] text-[var(--ink-soft)]">
              seeds RestockBot with signed $1,000 purchase authority on first start
            </span>
          )}
        </div>
        {beats && (
          <ol className="mt-4 space-y-1">
            {beats.map((b, i) => (
              <li key={i} className="text-[12px] flex items-baseline gap-2.5">
                <span className="mono text-[10px] text-[var(--ink-soft)]">
                  {String(i + 1).padStart(2, '0')}
                </span>
                <span className="text-[var(--ink-soft)]">{b.label}</span>
              </li>
            ))}
          </ol>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 items-start">
        <RunColumn
          title="Adaptive — assumptions re-verified"
          run={adaptive}
          accent="var(--green-ink)"
          scenarios={scenarios}
          busy={busy}
          onInject={inject}
          onAdvance={(id, toEnd) => advance(id, toEnd, 'adaptive')}
        />
        <RunColumn
          title="Baseline — adaptation off"
          run={baseline}
          accent="var(--red-ink)"
          scenarios={scenarios}
          busy={busy}
          onInject={() => {}}
          onAdvance={(id, toEnd) => advance(id, toEnd, 'baseline')}
        />
      </div>

      {adaptive?.events?.length > 0 && (
        <div className="card p-5 mt-4 fade-up">
          <p className="mono text-[11px] uppercase tracking-[0.12em] text-[var(--ink-soft)] mb-3">
            World event stream (append-only)
          </p>
          <div className="space-y-1.5">
            {adaptive.events.map((e) => (
              <div key={e.id} className="text-[12px] flex items-baseline gap-3">
                <span className="mono text-[10px] text-[var(--ink-soft)]">#{e.seq}</span>
                <span className="font-medium">{e.kind.replaceAll('_', ' ')}</span>
                <span className="text-[var(--ink-soft)] mono text-[10px]">
                  {JSON.stringify(e.payload)}
                </span>
                {e.applied_effects.length > 0 && (
                  <span className="text-[var(--green-ink)] text-[10px]">
                    ✓ {e.applied_effects[0]}
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
