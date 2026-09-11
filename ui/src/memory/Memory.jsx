import { useCallback, useEffect, useState } from 'react'

/* C4 · Memory That Knows It Might Be Wrong — Maya's memory inspector.
   Three panels: what Maya remembers (with source/confidence/freshness/scope
   tags), ask-Maya recalls with reliance receipts (the "I might be wrong"
   state), and the forgetting feed (tombstones with reasons) + per-fact
   privacy revocation. Every beat drives the REAL /api/memory endpoints. */

const api = {
  demo: () => fetch('/api/memory/demo', { method: 'POST' }).then((r) => r.json()),
  beat: (name) => fetch(`/api/memory/demo/${name}`, { method: 'POST' }).then((r) => r.json()),
  inspect: () => fetch('/api/memory/inspect?user_id=demo-user').then((r) => r.json()),
  events: () => fetch('/api/memory/events').then((r) => r.json()),
  recall: (query) =>
    fetch('/api/memory/recall', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, user_id: 'demo-user', agent_id: 'maya' }),
    }).then((r) => r.json()),
}

const KIND_LABEL = {
  user_stated: 'You said',
  observed: 'Observed',
  inferred: 'Inferred',
  imported: 'Imported',
}

const KIND_BADGE = {
  user_stated: 'allow',
  observed: 'info',
  inferred: 'escalate',
  imported: 'escalate',
}

const VERDICT = {
  confident: { badge: 'allow', label: 'Confident' },
  unsure: { badge: 'escalate', label: 'I might be wrong about this' },
  unknown: { badge: 'refuse', label: "I don't know" },
}

function Badge({ kind, children }) {
  return <span className={`badge badge-${kind}`}>{children}</span>
}

function ConfBar({ value }) {
  const pct = Math.round(value * 100)
  const color =
    value >= 0.55 ? 'var(--green-ink)' : value >= 0.25 ? 'var(--amber-ink)' : 'var(--red-ink)'
  return (
    <div className="flex items-center gap-2">
      <div className="w-20 h-1.5 rounded-full bg-[var(--canvas)] overflow-hidden">
        <div className="h-full rounded-full" style={{ width: `${pct}%`, background: color }} />
      </div>
      <span className="mono text-[11px] text-[var(--ink-soft)]">{pct}%</span>
    </div>
  )
}

/* ------------------------------------------------------------------ */

function FactCard({ fact, index }) {
  return (
    <div
      className="fade-up border-b last:border-b-0 py-3"
      style={{ animationDelay: `${index * 60}ms`, borderColor: 'var(--line)' }}
    >
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-sm font-medium">{fact.value}</span>
        <Badge kind={KIND_BADGE[fact.source_kind]}>{KIND_LABEL[fact.source_kind]}</Badge>
      </div>
      <div className="flex items-center justify-between mb-1.5">
        <span className="mono text-[11px] text-[var(--ink-soft)]">{fact.slot}</span>
        <ConfBar value={fact.effective_confidence} />
      </div>
      <p className="mono text-[10px] text-[var(--ink-soft)]">
        source {fact.source} · scope {fact.scope.user_id}
        {fact.scope.task_id ? ` / ${fact.scope.task_id}` : ''}
        {fact.expires_at ? ` · expires ${fact.expires_at.slice(0, 10)}` : ' · no TTL'}
        {fact.corroborations > 0 ? ` · corroborated ×${fact.corroborations}` : ''}
      </p>
    </div>
  )
}

function RecallCard({ recall }) {
  if (!recall) return null
  const v = VERDICT[recall.verdict] ?? VERDICT.unknown
  return (
    <div className="fade-up rounded-lg bg-[var(--canvas)] p-4 mb-3">
      <div className="flex items-center justify-between mb-2">
        <span className="text-[13px] font-medium">"{recall.query}"</span>
        <Badge kind={v.badge}>{v.label}</Badge>
      </div>
      {recall.verdict === 'unsure' && (
        <p className="text-[13px] text-[var(--amber-ink)] mb-2 leading-snug">
          Maya acts on this only with a hedge — or asks you to confirm first.
        </p>
      )}
      {recall.relied_on.map((f) => (
        <div key={f.fact_id} className="flex items-center justify-between py-1">
          <span className="text-[13px]">
            <span className="text-[var(--ink-soft)]">{f.slot} =</span> {f.value}
          </span>
          <ConfBar value={f.effective_confidence} />
        </div>
      ))}
      {recall.gaps.map((g, i) => (
        <p key={i} className="mono text-[11px] text-[var(--ink-soft)] mt-1.5">
          gap: {g}
        </p>
      ))}
      <p className="mono text-[10px] text-[var(--ink-soft)] mt-2">
        calibrated {Math.round(recall.calibrated_confidence * 100)}% · acts above{' '}
        {Math.round(recall.threshold * 100)}%
      </p>
    </div>
  )
}

function TombstoneRow({ t, index }) {
  return (
    <div
      className="fade-up flex items-baseline justify-between py-2 border-b last:border-b-0"
      style={{ animationDelay: `${index * 40}ms`, borderColor: 'var(--line)' }}
    >
      <span className="text-[13px]">
        <span className="line-through text-[var(--ink-soft)]">{t.value}</span>
        <span className="mono text-[10px] text-[var(--ink-soft)] ml-2">{t.slot}</span>
      </span>
      <span className="flex items-center gap-2 shrink-0 ml-3">
        <span className="mono text-[10px] text-[var(--ink-soft)]">{t.detail}</span>
        <Badge kind={t.reason === 'revoked' ? 'refuse' : 'escalate'}>{t.reason}</Badge>
      </span>
    </div>
  )
}

/* ------------------------------------------------------------------ */

export default function Memory() {
  const [view, setView] = useState(null)
  const [events, setEvents] = useState([])
  const [beats, setBeats] = useState([])
  const [recalls, setRecalls] = useState([])
  const [busy, setBusy] = useState('')
  const [revoked, setRevoked] = useState(false)

  const refresh = useCallback(async () => {
    const [v, e] = await Promise.all([api.inspect(), api.events()])
    setView(v)
    setEvents(e.tombstones)
  }, [])

  useEffect(() => {
    refresh()
    const t = setInterval(refresh, 4000)
    return () => clearInterval(t)
  }, [refresh])

  const run = async (label, fn) => {
    setBusy(label)
    try {
      await fn()
      await refresh()
    } finally {
      setBusy('')
    }
  }

  const seed = () =>
    run('demo', async () => {
      const out = await api.demo()
      setBeats(out.beats.map((b) => b.label))
      setRecalls([])
      setRevoked(false)
    })

  const unsure = () =>
    run('unsure', async () => {
      const out = await api.beat('unsure')
      setRecalls([out.seat, out.city])
    })

  const correct = () =>
    run('correct', async () => {
      const out = await api.beat('correct')
      setRecalls((r) => [...r, out.recall_after])
      setBeats((b) => [...b, 'You corrected: "I moved to Porto" — the weak inference is tombstoned'])
    })

  const age = () =>
    run('age', async () => {
      await api.beat('age')
      setBeats((b) => [...b, '45 days pass — the CRM import crosses its TTL and is swept'])
    })

  const revoke = () =>
    run('revoke', async () => {
      const out = await api.beat('revoke')
      setRecalls((r) => [...r, out.recall_after])
      setRevoked(true)
      setBeats((b) => [...b, 'You signed "forget my location" — revoked, receipted, gone'])
    })

  const ask = (query) =>
    run(query, async () => {
      const out = await api.recall(query)
      setRecalls((r) => [...r, out])
    })

  const seeded = view && (view.facts.length > 0 || view.tombstones.length > 0)

  return (
    <div className="fade-up">
      <div className="card p-5 mb-4">
        <h2 className="serif text-2xl font-medium mb-2">What does Maya remember — and how sure is she?</h2>
        <p className="text-[14px] text-[var(--ink-soft)] leading-relaxed mb-5 max-w-2xl">
          Every fact is tagged with its source, confidence, freshness, and scope. Retrieval
          shows a reliance receipt. Stale, contradicted, and revoked memories are forgotten
          explicitly — with tombstones, not silence.
        </p>
        <div className="flex flex-wrap gap-2 mb-2">
          <button
            onClick={seed}
            disabled={!!busy}
            className="pressable bg-[#1a1a18] text-white text-sm font-medium px-4 py-2 rounded-md hover:bg-[#333330] disabled:opacity-60"
          >
            {busy === 'demo' ? 'Seeding…' : 'Run the demo'}
          </button>
          {[
            ['unsure', '2 · Plan a trip (the unsure moment)', !seeded],
            ['correct', '3 · User corrects: moved to Porto', !seeded],
            ['age', '4 · Time passes (staleness sweep)', !seeded],
            ['revoke', '5 · Sign "forget my location"', !seeded || revoked],
          ].map(([id, label, disabled]) => (
            <button
              key={id}
              onClick={() => ({ unsure, correct, age, revoke })[id]()}
              disabled={!!busy || disabled}
              className="pressable text-sm font-medium px-4 py-2 rounded-md border hover:bg-[var(--canvas)] disabled:opacity-40"
              style={{ borderColor: 'var(--line)' }}
            >
              {busy === id ? '…' : label}
            </button>
          ))}
        </div>
        {seeded && (
          <div className="flex flex-wrap gap-2 mt-1">
            <span className="mono text-[10px] uppercase tracking-[0.12em] text-[var(--ink-soft)] py-2">
              Ask Maya:
            </span>
            {['seat preference', 'city', 'airline', 'favorite color'].map((q) => (
              <button
                key={q}
                onClick={() => ask(q)}
                disabled={!!busy}
                className="pressable mono text-[12px] px-3 py-1.5 rounded-md border hover:bg-[var(--canvas)] disabled:opacity-40"
                style={{ borderColor: 'var(--line)' }}
              >
                {q}
              </button>
            ))}
          </div>
        )}
        {beats.length > 0 && (
          <ol className="mt-4 space-y-1.5">
            {beats.map((b, i) => (
              <li key={i} className="text-[13px] flex items-baseline gap-2.5 fade-up">
                <span className="mono text-[10px] text-[var(--ink-soft)] shrink-0">
                  {String(i + 1).padStart(2, '0')}
                </span>
                <span className="text-[var(--ink)]">{b}</span>
              </li>
            ))}
          </ol>
        )}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-[1fr_1.3fr_1fr] gap-4 items-start">
        <div className="card p-5">
          <p className="mono text-[11px] uppercase tracking-[0.12em] text-[var(--ink-soft)] mb-4">
            Memory inspector — what Maya remembers about you
          </p>
          {!view || (view.facts.length === 0 && view.tombstones.length === 0) ? (
            <p className="text-sm text-[var(--ink-soft)]">
              Nothing yet — press <span className="font-medium text-[var(--ink)]">Run the demo</span>.
            </p>
          ) : (
            <>
              {view.facts.map((f, i) => (
                <FactCard key={f.id} fact={f} index={i} />
              ))}
              {view.facts.length === 0 && (
                <p className="text-sm text-[var(--ink-soft)]">Everything live was forgotten.</p>
              )}
            </>
          )}
        </div>

        <div className="card p-5">
          <p className="mono text-[11px] uppercase tracking-[0.12em] text-[var(--ink-soft)] mb-4">
            Recall — what Maya relies on, and how sure she is
          </p>
          {recalls.length === 0 && (
            <p className="text-sm text-[var(--ink-soft)]">
              Run beat 2 to watch the "I might be wrong about this" moment, or ask directly.
            </p>
          )}
          {recalls.map((r, i) => (
            <RecallCard key={i} recall={r} />
          ))}
        </div>

        <div className="card p-5">
          <p className="mono text-[11px] uppercase tracking-[0.12em] text-[var(--ink-soft)] mb-4">
            Forgetting feed — tombstones with reasons
          </p>
          {events.length === 0 ? (
            <p className="text-sm text-[var(--ink-soft)]">Nothing forgotten yet.</p>
          ) : (
            events.slice(0, 12).map((t, i) => <TombstoneRow key={t.fact_id} t={t} index={i} />)
          )}
        </div>
      </div>
    </div>
  )
}
