import { useCallback, useEffect, useState } from 'react'

const api = {
  agents: () => fetch('/api/trust/agents').then((r) => r.json()),
  profile: (key) =>
    fetch(`/api/trust/profile?subject_key=${encodeURIComponent(key)}`).then((r) => r.json()),
  receipts: () => fetch('/api/trust/receipts?limit=20').then((r) => r.json()),
}

function shortKey(key) {
  return key ? `${key.slice(0, 10)}…${key.slice(-4)}` : ''
}

function DecisionBadge({ decision }) {
  const styles = {
    allow: 'bg-emerald-950 text-emerald-300 border-emerald-800',
    refuse: 'bg-red-950 text-red-300 border-red-800',
    escalate: 'bg-amber-950 text-amber-300 border-amber-800',
  }
  return (
    <span
      className={`inline-block px-2 py-0.5 text-xs font-mono uppercase tracking-wider border rounded ${styles[decision] || ''}`}
    >
      {decision}
    </span>
  )
}

function CredentialRow({ cred }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="border border-neutral-800 rounded mb-2">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-3 py-2 text-left hover:bg-neutral-900"
      >
        <span className="font-mono text-sm">{cred.type}</span>
        <span className="flex items-center gap-3">
          <span className="text-xs text-neutral-500 font-mono">{shortKey(cred.issuer_key)}</span>
          {cred.valid ? (
            <span className="text-emerald-400 text-xs font-mono">✓ verified</span>
          ) : (
            <span className="text-red-400 text-xs font-mono">✗ {cred.failures.join(', ')}</span>
          )}
        </span>
      </button>
      {open && (
        <pre className="px-3 py-2 text-xs text-neutral-400 overflow-x-auto border-t border-neutral-800">
          {JSON.stringify({ claim: cred.claim, scope: cred.scope, expires_at: cred.expires_at }, null, 2)}
        </pre>
      )}
    </div>
  )
}

export default function App() {
  const [agents, setAgents] = useState([])
  const [selected, setSelected] = useState(null)
  const [profile, setProfile] = useState(null)
  const [receipts, setReceipts] = useState([])

  const refresh = useCallback(async () => {
    const [a, r] = await Promise.all([api.agents(), api.receipts()])
    setAgents(a.agents)
    setReceipts(r.receipts)
    if (selected) {
      setProfile(await api.profile(selected.public_key))
    }
  }, [selected])

  useEffect(() => {
    refresh()
    const t = setInterval(refresh, 3000)
    return () => clearInterval(t)
  }, [refresh])

  const pick = async (agent) => {
    setSelected(agent)
    setProfile(await api.profile(agent.public_key))
  }

  return (
    <div className="min-h-screen p-6 max-w-6xl mx-auto">
      <header className="mb-8">
        <h1 className="text-2xl font-mono font-bold tracking-tight">TrustCore Inspector</h1>
        <p className="text-sm text-neutral-500 mt-1">
          Every number below traces to a specific signed claim. There is no aggregate score.
        </p>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* fleet */}
        <section>
          <h2 className="text-xs font-mono uppercase tracking-widest text-neutral-500 mb-3">Agents</h2>
          {agents.map((a) => (
            <button
              key={a.id}
              onClick={() => pick(a)}
              className={`w-full text-left px-3 py-2 mb-2 border rounded font-mono text-sm transition-colors ${
                selected?.id === a.id
                  ? 'border-neutral-500 bg-neutral-900'
                  : 'border-neutral-800 hover:border-neutral-700'
              }`}
            >
              <div className="flex justify-between">
                <span>{a.name}</span>
                <span className="text-neutral-500 text-xs">{a.owner}</span>
              </div>
              <div className="text-xs text-neutral-600 mt-1">{shortKey(a.public_key)}</div>
            </button>
          ))}
          {agents.length === 0 && (
            <p className="text-sm text-neutral-600">No agents registered. Run the demo.</p>
          )}
        </section>

        {/* profile */}
        <section>
          <h2 className="text-xs font-mono uppercase tracking-widest text-neutral-500 mb-3">
            {selected ? `Trust profile — ${selected.name}` : 'Trust profile'}
          </h2>
          {profile ? (
            <>
              <div className="flex gap-4 mb-4 text-sm font-mono">
                <span className="text-emerald-400">
                  {profile.counts.valid_authority_grants} authority
                </span>
                <span className="text-sky-400">{profile.counts.valid_completions} completions</span>
                <span className="text-red-400">{profile.counts.invalid_or_revoked} invalid</span>
              </div>
              {profile.credentials.map((c) => (
                <CredentialRow key={c.id} cred={c} />
              ))}
            </>
          ) : (
            <p className="text-sm text-neutral-600">Select an agent to inspect its claims.</p>
          )}
        </section>

        {/* receipts */}
        <section>
          <h2 className="text-xs font-mono uppercase tracking-widest text-neutral-500 mb-3">
            Decision receipts
          </h2>
          <div className="space-y-2">
            {receipts.map((r) => (
              <div key={r.id} className="border border-neutral-800 rounded px-3 py-2">
                <div className="flex items-center justify-between">
                  <DecisionBadge decision={r.decision} />
                  <span className="text-xs text-neutral-600 font-mono">
                    {r.ts.slice(11, 19)} · llm={String(r.llm_called)}
                  </span>
                </div>
                <p className="text-xs text-neutral-400 mt-1 font-mono">
                  {r.action} — {r.reasoning}
                </p>
              </div>
            ))}
            {receipts.length === 0 && (
              <p className="text-sm text-neutral-600">No decisions yet.</p>
            )}
          </div>
        </section>
      </div>
    </div>
  )
}
