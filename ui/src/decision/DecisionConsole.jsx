import { useCallback, useEffect, useState } from 'react'

/* C2 DecisionConsole — the decision is computed from signals, not a prompt. */

const api = {
  demo: () => fetch('/api/decision/demo', { method: 'POST' }).then((r) => r.json()),
  domains: () => fetch('/api/decision/domains').then((r) => r.json()),
  decide: (body) =>
    fetch('/api/decision/decide', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then((r) => r.json()),
  decisions: () => fetch('/api/decision/decisions?limit=20').then((r) => r.json()),
}

const shortKey = (key) => (key ? `${key.slice(0, 8)}…${key.slice(-4)}` : '')

const OUTCOME_KIND = {
  execute: 'allow',
  ask: 'info',
  defer: 'info',
  escalate: 'escalate',
  refuse: 'refuse',
}

function Badge({ kind, children }) {
  return <span className={`badge badge-${kind}`}>{children}</span>
}

function Bar({ value, tone }) {
  const color =
    tone === 'risk'
      ? value >= 0.6
        ? 'var(--red-ink)'
        : value >= 0.4
          ? 'var(--amber-ink)'
          : 'var(--green-ink)'
      : value >= 0.7
        ? 'var(--green-ink)'
        : value >= 0.5
          ? 'var(--amber-ink)'
          : 'var(--red-ink)'
  return (
    <div className="h-1.5 rounded-full bg-[var(--canvas)] overflow-hidden">
      <div
        className="h-full rounded-full transition-all duration-500"
        style={{ width: `${Math.round(value * 100)}%`, background: color }}
      />
    </div>
  )
}

/* one signal row: name, weight, contribution bar, detail */
function SignalRow({ s }) {
  return (
    <div className="py-2 border-b last:border-b-0" style={{ borderColor: 'var(--line)' }}>
      <div className="flex items-center justify-between mb-1">
        <span className="mono text-[11px] uppercase tracking-[0.1em] text-[var(--ink)]">
          {s.name.replace(/_/g, ' ')}
        </span>
        <span className="mono text-[10px] text-[var(--ink-soft)]">
          {s.value.toFixed(2)} × w{s.weight} → {s.contributes_to}
        </span>
      </div>
      <Bar value={s.value} tone={s.contributes_to === 'risk' ? 'risk' : 'confidence'} />
      <p className="text-[12px] text-[var(--ink-soft)] mt-1">{s.detail}</p>
    </div>
  )
}

/* preset scenarios per domain so a judge never types a prompt */
const PRESETS = {
  refund: (keys) => [
    {
      label: 'Clean $120 refund (invoice + reason)',
      body: { domain: 'refund', action: 'issue_refund', actor_key: keys.triage_key, amount: 120,
        context: { invoice_id: 'INV-1042', reason: 'defective item', customer_history: 'gold' } },
    },
    {
      label: '$2400 refund, missing invoice_id',
      body: { domain: 'refund', action: 'issue_refund', actor_key: keys.triage_key, amount: 2400,
        context: { reason: 'defective item' } },
    },
  ],
  deploy: (keys) => [
    {
      label: 'Failure test: $8000 deploy, missing change_ticket',
      body: { domain: 'deploy', action: 'deploy_production', actor_key: keys.deploy_key, amount: 8000,
        context: { tests_passing: true, approvals: 2 } },
    },
    {
      label: '$8000 deploy, fully evidenced (still irreversible)',
      body: { domain: 'deploy', action: 'deploy_production', actor_key: keys.deploy_key, amount: 8000,
        context: { tests_passing: true, approvals: 2, change_ticket: 'CHG-231' } },
    },
  ],
  moderation: (keys) => [
    {
      label: 'Remove flagged content (reach 40, evidenced)',
      body: { domain: 'moderation', action: 'remove_content', actor_key: keys.mod_key, amount: 40,
        context: { report_count: 12, policy_category: 'hate', prior_violations: 3 } },
    },
    {
      label: 'Remove content, high reach 250, thin evidence',
      body: { domain: 'moderation', action: 'remove_content', actor_key: keys.mod_key, amount: 250,
        context: { report_count: 1 } },
    },
  ],
}

export default function DecisionConsole() {
  const [seeded, setSeeded] = useState(null)
  const [domain, setDomain] = useState('refund')
  const [result, setResult] = useState(null)
  const [decisions, setDecisions] = useState([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const refresh = useCallback(async () => {
    setDecisions((await api.decisions()).decisions)
  }, [])

  useEffect(() => {
    refresh()
    const t = setInterval(refresh, 4000)
    return () => clearInterval(t)
  }, [refresh])

  const seed = async () => {
    setBusy(true)
    setError(null)
    try {
      const s = await api.demo()
      setSeeded(s)
      setResult(null)
    } finally {
      setBusy(false)
    }
  }

  const run = async (body) => {
    setBusy(true)
    setError(null)
    try {
      const r = await api.decide(body)
      if (r.detail) {
        setError(typeof r.detail === 'string' ? r.detail : JSON.stringify(r.detail))
        return
      }
      setResult(r)
      await refresh()
    } finally {
      setBusy(false)
    }
  }

  const presets = seeded ? PRESETS[domain](seeded) : []

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[1fr_1.4fr] gap-4 items-start">
      {/* left: domain picker + presets */}
      <div className="space-y-4">
        <div className="card p-5 fade-up">
          <p className="mono text-[11px] uppercase tracking-[0.12em] text-[var(--ink-soft)] mb-4">
            Decision console
          </p>
          <button
            onClick={seed}
            disabled={busy}
            className="pressable w-full bg-[#1a1a18] text-white text-sm font-medium px-4 py-2.5 rounded-md hover:bg-[#333330] disabled:opacity-60 mb-4"
          >
            {seeded ? 'Re-seed the three domains' : 'Seed the demo (3 agents, signed authority)'}
          </button>

          <div className="flex gap-2 mb-4">
            {['refund', 'deploy', 'moderation'].map((d) => (
              <button
                key={d}
                onClick={() => setDomain(d)}
                className={`pressable flex-1 text-[13px] font-medium px-3 py-2 rounded-md border ${
                  domain === d ? 'bg-[#1a1a18] text-white border-transparent' : 'hover:bg-[var(--canvas)]'
                }`}
                style={{ borderColor: domain === d ? 'transparent' : 'var(--line)' }}
              >
                {d}
              </button>
            ))}
          </div>

          <div className="space-y-2">
            {presets.map((p, i) => (
              <button
                key={i}
                onClick={() => run(p.body)}
                disabled={busy}
                className="pressable w-full text-left border text-[13px] px-3.5 py-2.5 rounded-lg hover:bg-[var(--canvas)] disabled:opacity-50"
                style={{ borderColor: 'var(--line)' }}
              >
                {p.label}
              </button>
            ))}
            {!seeded && (
              <p className="text-[13px] text-[var(--ink-soft)]">
                Seed first — the engine decides from real signed authority, evidence, and history.
              </p>
            )}
          </div>
          {seeded && (
            <p className="mono text-[10px] text-[var(--ink-soft)] mt-3">
              triage {shortKey(seeded.triage_key)} · deploy {shortKey(seeded.deploy_key)} · mod {shortKey(seeded.mod_key)}
            </p>
          )}
          {error && (
            <p className="text-[12px] mt-3" style={{ color: 'var(--red-ink)' }}>{error}</p>
          )}
        </div>

        {/* audit feed */}
        <div className="card p-5 fade-up">
          <p className="mono text-[11px] uppercase tracking-[0.12em] text-[var(--ink-soft)] mb-3">
            Audit trail (append-only receipts)
          </p>
          <div className="space-y-3">
            {decisions.map((d) => (
              <div key={d.id} className="fade-up">
                <div className="flex items-center justify-between mb-0.5">
                  <Badge kind={OUTCOME_KIND[d.outcome]}>{d.outcome}</Badge>
                  <span className="mono text-[10px] text-[var(--ink-soft)]">
                    conf {d.confidence.toFixed(2)} · risk {d.risk.toFixed(2)} · llm off
                  </span>
                </div>
                <p className="text-[12px] text-[var(--ink)]">
                  <span className="font-medium">{d.domain}.{d.proposed.action}</span>
                  <span className="text-[var(--ink-soft)]"> — {d.reasoning}</span>
                </p>
              </div>
            ))}
            {decisions.length === 0 && (
              <p className="text-[13px] text-[var(--ink-soft)]">No decisions yet.</p>
            )}
          </div>
        </div>
      </div>

      {/* right: the decision render */}
      <div className="card p-5 fade-up">
        {!result && (
          <div className="h-full flex items-center justify-center min-h-[280px]">
            <p className="text-sm text-[var(--ink-soft)] text-center max-w-xs">
              Pick a domain and a scenario. The engine computes confidence and risk from five
              weighted signals and returns one of five outcomes — never a prompt, never a guess.
            </p>
          </div>
        )}

        {result && (
          <>
            <div className="flex items-center justify-between mb-1">
              <h3 className="serif text-xl font-medium">
                {result.domain}.{result.proposed.action}
              </h3>
              <Badge kind={OUTCOME_KIND[result.outcome]}>{result.outcome}</Badge>
            </div>
            <p className="mono text-[11px] text-[var(--ink-soft)] mb-5">
              {shortKey(result.proposed.actor_key)}
              {result.proposed.amount != null && ` · $${result.proposed.amount}`} · {result.resolution_path}
            </p>

            {/* confidence / risk */}
            <div className="grid grid-cols-2 gap-4 mb-5">
              <div>
                <div className="flex justify-between mb-1.5">
                  <span className="text-[12px] text-[var(--ink-soft)]">Confidence</span>
                  <span className="mono text-[12px] font-medium">{result.confidence.toFixed(2)}</span>
                </div>
                <Bar value={result.confidence} tone="confidence" />
              </div>
              <div>
                <div className="flex justify-between mb-1.5">
                  <span className="text-[12px] text-[var(--ink-soft)]">Risk</span>
                  <span className="mono text-[12px] font-medium">{result.risk.toFixed(2)}</span>
                </div>
                <Bar value={result.risk} tone="risk" />
              </div>
            </div>

            {/* reversibility */}
            <div className="rounded-lg bg-[var(--canvas)] p-3 mb-5">
              <p className="mono text-[11px] uppercase tracking-[0.12em] text-[var(--ink-soft)] mb-1">
                Reversibility
              </p>
              <p className="text-[13px]">
                {result.reversibility.exists ? (
                  <>
                    compensating action <span className="font-medium">{result.reversibility.kind}</span>
                    <span className="text-[var(--ink-soft)]">
                      {' '}— {result.reversibility.cost} cost{result.reversibility.partial ? ', partial' : ', full'}
                      {' '}(score {result.reversibility.reversibility_score})
                    </span>
                  </>
                ) : (
                  <span style={{ color: 'var(--red-ink)' }}>irreversible — no compensating action</span>
                )}
              </p>
            </div>

            {/* missing information — named, first-class */}
            {result.missing_information.length > 0 && (
              <div className="rounded-lg p-3 mb-5" style={{ background: 'var(--amber-bg)' }}>
                <p className="mono text-[11px] uppercase tracking-[0.12em] mb-1" style={{ color: 'var(--amber-ink)' }}>
                  Missing information
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {result.missing_information.map((m) => (
                    <span key={m} className="mono text-[11px] px-2 py-0.5 rounded" style={{ background: 'var(--canvas)', color: 'var(--amber-ink)' }}>
                      {m}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* the five signals, weighted */}
            <p className="mono text-[11px] uppercase tracking-[0.12em] text-[var(--ink-soft)] mb-2">
              Signals (weighted, deterministic — recompute by hand)
            </p>
            <div className="mb-4">
              {result.signals.map((s, i) => (
                <SignalRow key={i} s={s} />
              ))}
            </div>

            <p className="text-[12px] text-[var(--ink-soft)] pt-3 border-t" style={{ borderColor: 'var(--line)' }}>
              {result.reasoning} · receipt <span className="mono">{shortKey(result.receipt_id)}</span> · llm off
            </p>
          </>
        )}
      </div>
    </div>
  )
}
