import { useCallback, useEffect, useRef, useState } from 'react'
import AdaptiveRun from './adaptive/AdaptiveRun'
import Canvas from './ambient/Canvas'
import Company from './company/Company'
import HowTo from './components/HowTo'
import DecisionConsole from './decision/DecisionConsole'
import Memory from './memory/Memory'
import SimGate from './sim/SimGate'
import Tower from './tower/Tower'

const api = {
  agents: () => fetch('/api/trust/agents').then((r) => r.json()),
  profile: (key) =>
    fetch(`/api/trust/profile?subject_key=${encodeURIComponent(key)}`).then((r) => r.json()),
  receipts: () => fetch('/api/trust/receipts?limit=30').then((r) => r.json()),
  runDemo: () => fetch('/api/trust/demo', { method: 'POST' }).then((r) => r.json()),
}

/* Order + labels for the challenge tabs, C1 → C8. Each maps to the seed/demo
   endpoint that powers its "Run the demo" button. */
const TABS = [
  ['trust', 'C1 · Trust'],
  ['decision', 'C2 · Decision Engine'],
  ['adaptive', 'C3 · Adaptive Agent'],
  ['memory', 'C4 · Memory'],
  ['tower', 'C5 · Control Tower'],
  ['company', 'C6 · Company'],
  ['canvas', 'C7 · Canvas'],
  ['sim', 'C8 · Simulate first'],
]

const DEMO_ENDPOINT = {
  trust: '/api/trust/demo',
  decision: '/api/decision/demo',
  adaptive: '/api/adaptive/demo',
  memory: '/api/memory/demo',
  tower: '/api/tower/demo',
  company: '/api/company/demo',
  canvas: '/api/ambient/demo',
  sim: '/api/sim/demo',
}

const shortKey = (key) => (key ? `${key.slice(0, 8)}…${key.slice(-4)}` : '')

const TYPE_LABEL = {
  AuthorityGrant: 'Authority grant',
  TaskCompletion: 'Task completion',
  CapabilityAttestation: 'Capability attestation',
  Vouch: 'Vouch',
}

function Badge({ kind, children }) {
  return <span className={`badge badge-${kind}`}>{children}</span>
}

function Dot({ color }) {
  return (
    <span
      className="inline-block w-1.5 h-1.5 rounded-full"
      style={{ background: color }}
    />
  )
}

/* ------------------------------------------------------------------ */

function AgentList({ agents, selected, onPick }) {
  return (
    <div className="card p-5 fade-up">
      <p className="mono text-[11px] uppercase tracking-[0.12em] text-[var(--ink-soft)] mb-4">
        Fleet
      </p>
      {agents.length === 0 && (
        <p className="text-sm text-[var(--ink-soft)]">
          Nothing here yet — press <span className="font-medium text-[var(--ink)]">Run the demo</span> above
          to watch three agents earn, lose, and abuse trust.
        </p>
      )}
      <div className="space-y-1.5">
        {agents.map((a, i) => (
          <button
            key={a.id}
            onClick={() => onPick(a)}
            style={{ animationDelay: `${i * 60}ms` }}
            className={`pressable fade-up w-full text-left px-3.5 py-3 rounded-lg border transition-colors ${
              selected?.id === a.id
                ? 'border-[var(--ink)] bg-[var(--canvas)]'
                : 'border-transparent hover:bg-[var(--canvas)]'
            }`}
          >
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium">{a.name}</span>
              <span className="text-xs text-[var(--ink-soft)]">{a.owner}</span>
            </div>
            <div className="mono text-[11px] text-[var(--ink-soft)] mt-0.5">
              {shortKey(a.public_key)}
            </div>
          </button>
        ))}
      </div>
    </div>
  )
}

function Credential({ cred, index }) {
  const [open, setOpen] = useState(false)
  return (
    <div
      className="fade-up border-b last:border-b-0"
      style={{ animationDelay: `${index * 60}ms`, borderColor: 'var(--line)' }}
    >
      <button
        onClick={() => setOpen(!open)}
        className="pressable w-full flex items-center justify-between py-3 text-left"
      >
        <div className="flex items-center gap-3">
          <Dot color={cred.valid ? 'var(--green-ink)' : 'var(--red-ink)'} />
          <span className="text-sm font-medium">{TYPE_LABEL[cred.type] ?? cred.type}</span>
        </div>
        <span className="flex items-center gap-2.5">
          {cred.valid ? (
            <Badge kind="allow">Verified</Badge>
          ) : (
            <Badge kind="refuse">{cred.failures[0]?.replace('_', ' ')}</Badge>
          )}
          <span className="text-[var(--ink-soft)] text-sm">{open ? '−' : '+'}</span>
        </span>
      </button>
      {open && (
        <div className="pb-4 pl-6">
          <p className="mono text-[11px] text-[var(--ink-soft)] mb-2">
            issuer {shortKey(cred.issuer_key)} · expires {cred.expires_at.slice(0, 10)}
          </p>
          <pre className="mono text-[11px] leading-relaxed bg-[var(--canvas)] rounded-lg p-3 overflow-x-auto">
            {JSON.stringify({ claim: cred.claim, scope: cred.scope }, null, 2)}
          </pre>
        </div>
      )}
    </div>
  )
}

function Profile({ agent, profile }) {
  if (!agent) {
    return (
      <div className="card p-5 fade-up h-full flex items-center justify-center min-h-[220px]">
        <p className="text-sm text-[var(--ink-soft)]">
          Select an agent to inspect its signed claims.
        </p>
      </div>
    )
  }
  return (
    <div className="card p-5 fade-up">
      <div className="flex items-baseline justify-between mb-1">
        <h3 className="serif text-xl font-medium">{agent.name}</h3>
        <span className="mono text-[11px] text-[var(--ink-soft)]">{shortKey(agent.public_key)}</span>
      </div>
      <p className="text-xs text-[var(--ink-soft)] mb-5">
        Every count below traces to an individually verifiable signed claim. No aggregate score.
      </p>
      {profile && (
        <>
          <div className="grid grid-cols-3 gap-3 mb-5">
            {[
              ['Authority grants', profile.counts.valid_authority_grants, 'allow'],
              ['Completions', profile.counts.valid_completions, 'info'],
              ['Invalid / revoked', profile.counts.invalid_or_revoked, 'refuse'],
            ].map(([label, n, kind]) => (
              <div key={label} className="rounded-lg bg-[var(--canvas)] px-3 py-2.5">
                <div className="serif text-2xl font-medium leading-none">{n}</div>
                <div className="text-[11px] text-[var(--ink-soft)] mt-1.5">{label}</div>
              </div>
            ))}
          </div>
          <div>
            {profile.credentials.map((c, i) => (
              <Credential key={c.id} cred={c} index={i} />
            ))}
            {profile.credentials.length === 0 && (
              <p className="text-sm text-[var(--ink-soft)]">No credentials on record.</p>
            )}
          </div>
        </>
      )}
    </div>
  )
}

function ReceiptFeed({ receipts }) {
  const prevIds = useRef(new Set())
  useEffect(() => {
    prevIds.current = new Set(receipts.map((r) => r.id))
  })
  return (
    <div className="card p-5 fade-up">
      <p className="mono text-[11px] uppercase tracking-[0.12em] text-[var(--ink-soft)] mb-4">
        Decision receipts
      </p>
      {receipts.length === 0 && (
        <p className="text-sm text-[var(--ink-soft)]">No decisions yet.</p>
      )}
      <div className="space-y-3.5">
        {receipts.map((r, i) => {
          const isNew = !prevIds.current.has(r.id)
          return (
            <div
              key={r.id}
              className={isNew ? 'fade-up' : ''}
              style={isNew ? {} : { animationDelay: `${i * 40}ms` }}
            >
              <div className="flex items-center justify-between mb-1">
                <Badge kind={r.decision}>{r.decision}</Badge>
                <span className="mono text-[10px] text-[var(--ink-soft)]">
                  {r.ts.slice(11, 19)} UTC · llm off
                </span>
              </div>
              <p className="text-[13px] leading-snug text-[var(--ink)]">
                <span className="font-medium">{r.action}</span>
                <span className="text-[var(--ink-soft)]"> — {r.reasoning}</span>
              </p>
            </div>
          )
        })}
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ */

export default function App() {
  const [tab, setTab] = useState('trust')
  const [agents, setAgents] = useState([])
  const [selected, setSelected] = useState(null)
  const [profile, setProfile] = useState(null)
  const [receipts, setReceipts] = useState([])
  const [online, setOnline] = useState(true)
  const [running, setRunning] = useState(false)
  const [lastRun, setLastRun] = useState(null)

  const runDemo = async () => {
    setRunning(true)
    try {
      const endpoint = DEMO_ENDPOINT[tab] ?? DEMO_ENDPOINT.trust
      const init =
        tab === 'company'
          ? {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ scenario: 'normal' }),
            }
          : { method: 'POST' }
      const result = await fetch(endpoint, init).then((r) => r.json())
      setLastRun(result)
      await refresh()
      // C1: select BuyerBot so the profile panel fills in immediately
      if (tab === 'trust') {
        const a = await api.agents()
        const buyer = a.agents.find((x) => x.public_key === result.buyer_key)
        if (buyer) setSelected(buyer)
      }
    } finally {
      setRunning(false)
    }
  }

  const refresh = useCallback(async () => {
    try {
      const [a, r] = await Promise.all([api.agents(), api.receipts()])
      setAgents(a.agents)
      setReceipts(r.receipts)
      setOnline(true)
    } catch {
      setOnline(false)
    }
  }, [])

  useEffect(() => {
    refresh()
    const t = setInterval(refresh, 3000)
    return () => clearInterval(t)
  }, [refresh])

  useEffect(() => {
    if (!selected) return
    let cancelled = false
    const load = async () => {
      const p = await api.profile(selected.public_key)
      if (!cancelled) setProfile(p)
    }
    load()
    const t = setInterval(load, 3000)
    return () => {
      cancelled = true
      clearInterval(t)
    }
  }, [selected])

  return (
    <div className="min-h-screen">
      <div className="max-w-5xl mx-auto px-6 py-14 md:py-20">
        <header className="mb-12 fade-up">
          <div className="flex items-center gap-2 mb-4">
            <Dot color={online ? 'var(--green-ink)' : 'var(--red-ink)'} />
            <span className="mono text-[11px] uppercase tracking-[0.12em] text-[var(--ink-soft)]">
              {online ? 'Connected to TrustCore' : 'API unreachable'}
            </span>
          </div>
          <h1 className="serif text-4xl md:text-5xl font-medium leading-[1.05] mb-4">
            Who may this agent trust?
          </h1>
          <p className="text-[15px] text-[var(--ink-soft)] max-w-xl leading-relaxed mb-6">
            Every agent here carries signed, verifiable credentials — authority grants,
            completed-task vouches, attestations. Decisions are enforced by cryptography
            and policy, never by a model. Each one leaves a receipt.
          </p>
          <div className="flex items-center gap-4">
            <button
              onClick={runDemo}
              disabled={running}
              className="pressable bg-[#1a1a18] text-white text-sm font-medium px-5 py-2.5 rounded-md hover:bg-[#333330] disabled:opacity-60"
            >
              {running ? 'Running…' : 'Run the demo'}
            </button>
            <span className="text-[13px] text-[var(--ink-soft)]">
              Seeds and runs the <span className="font-medium text-[var(--ink)]">{TABS.find(([id]) => id === tab)?.[1]}</span> demo, server-side.
            </span>
          </div>
          {lastRun?.beats && (
            <ol className="mt-6 space-y-1.5 fade-up">
              {lastRun.beats.map((b, i) => (
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

          {/* challenge tabs, ordered C1 → C8 */}
          <div className="mt-8 flex flex-wrap gap-2">
            {TABS.map(([id, label]) => (
              <button
                key={id}
                onClick={() => setTab(id)}
                className={`pressable text-sm font-medium px-4 py-2 rounded-md border ${
                  tab === id ? 'bg-[#1a1a18] text-white border-transparent' : 'hover:bg-[var(--canvas)]'
                }`}
                style={{ borderColor: tab === id ? 'transparent' : 'var(--line)' }}
              >
                {label}
              </button>
            ))}
          </div>
        </header>

        {tab === 'trust' && (
          <div>
            <HowTo
              steps={[
                'Press "Run the demo" — three agents (BuyerBot, VendorBot, SpooferBot) earn, lose, and abuse trust in six receipted beats.',
                'Click an agent in the Fleet list to inspect its signed claims — every count traces to an individually verifiable credential.',
                'Watch the receipts feed: a legitimate purchase is accepted, a forged signature is refused, a scope escape is refused, and a revocation sticks.',
                'Every receipt reads "llm off" — enforcement is cryptography + policy only, never a model.',
              ]}
            />
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-[1fr_1.4fr_1fr] gap-4 items-start">
              <AgentList agents={agents} selected={selected} onPick={setSelected} />
              <Profile agent={selected} profile={profile} />
              <ReceiptFeed receipts={receipts} />
            </div>
          </div>
        )}
        {tab === 'decision' && <DecisionConsole />}
        {tab === 'sim' && <SimGate />}
        {tab === 'adaptive' && <AdaptiveRun />}
        {tab === 'tower' && <Tower />}
        {tab === 'memory' && <Memory />}
        {tab === 'company' && <Company />}
        {tab === 'canvas' && <Canvas onCompare={() => setTab('tower')} />}

        <footer className="mt-14 pt-6 border-t text-[12px] text-[var(--ink-soft)] flex justify-between" style={{ borderColor: 'var(--line)' }}>
          <span className="mono">TrustCore + DecisionCore + AdaptiveCore + MemoryCore + TowerCore + CompanyCore + AmbientCore + SimCore · Builders League, C1–C8</span>
          <span>Ed25519 · VC-shaped claims · append-only receipts · decision layer · simulate-first · plan/observe/revise · agent ops control plane · self-doubting memory</span>
        </footer>
      </div>
    </div>
  )
}
