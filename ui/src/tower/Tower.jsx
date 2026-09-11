import { useCallback, useEffect, useRef, useState } from 'react'

/* C5 · The Agent Control Tower — the operator cockpit.
   Fleet state, live event timeline (SSE), approval queue, kill switches,
   replay drawer, rogue-scenario lever, audit export. Reads the SAME event
   stream the control plane enforces on — there is no second source of truth. */

const api = {
  seed: () => fetch('/api/tower/demo', { method: 'POST' }).then((r) => r.json()),
  fleet: () => fetch('/api/tower/fleet').then((r) => r.json()),
  approvals: () => fetch('/api/tower/approvals').then((r) => r.json()),
  advance: (id) => fetch(`/api/tower/agents/${id}/advance`, { method: 'POST' }).then((r) => r.json()),
  intervene: (id, verb) =>
    fetch(`/api/tower/agents/${id}/${verb}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ operator: 'operator' }),
    }).then((r) => r.json()),
  resolve: (id, verb) =>
    fetch(`/api/tower/approvals/${id}/${verb}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ operator: 'operator' }),
    }).then((r) => r.json()),
  replay: (id, n = 20) => fetch(`/api/tower/agents/${id}/replay?n=${n}`).then((r) => r.json()),
  rogue: (id) =>
    fetch('/api/tower/scenario/rogue', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ agent_id: id }),
    }).then((r) => r.json()),
}

const STATUS = {
  running: { dot: 'var(--green-ink)', label: 'Running' },
  paused: { dot: 'var(--amber-ink)', label: 'Paused' },
  awaiting_approval: { dot: 'var(--amber-ink)', label: 'Awaiting approval' },
  blocked: { dot: 'var(--amber-ink)', label: 'Blocked' },
  killed: { dot: 'var(--red-ink)', label: 'Killed' },
}

const KIND_BADGE = {
  action_executed: 'allow',
  action_denied: 'refuse',
  drift_flagged: 'refuse',
  approval_requested: 'escalate',
  approval_resolved: 'info',
  intervention_applied: 'escalate',
  blocker_raised: 'escalate',
  step_started: 'info',
  decision_requested: 'info',
  cost_recorded: 'info',
}

function Dot({ color }) {
  return (
    <span className="inline-block w-1.5 h-1.5 rounded-full" style={{ background: color }} />
  )
}

function Badge({ kind, children }) {
  return <span className={`badge badge-${KIND_BADGE[kind] ?? 'info'}`}>{children}</span>
}

/* ------------------------------------------------------------------ */

function FleetRow({ agent, onAdvance, onIntervene, onReplay, busy }) {
  const s = STATUS[agent.status] ?? STATUS.running
  const drift = agent.drift?.length > 0
  return (
    <div
      className="card p-4 fade-up"
      style={drift ? { borderColor: 'var(--red-ink)', borderWidth: 1 } : {}}
    >
      <div className="flex items-center justify-between mb-1">
        <div className="flex items-center gap-2.5">
          <Dot color={s.dot} />
          <span className="text-sm font-medium capitalize">{agent.agent_id}</span>
          <span className="mono text-[10px] text-[var(--ink-soft)] uppercase tracking-wide">
            {s.label}
          </span>
        </div>
        {drift && <span className="badge badge-refuse">drift</span>}
      </div>

      <p className="text-[12px] text-[var(--ink-soft)] mb-2.5 pl-4">
        last: <span className="text-[var(--ink)]">{agent.last_action ?? '—'}</span>
        {agent.blockers?.length > 0 && (
          <span className="text-[var(--amber-ink)]"> · blocked: {agent.blockers[0]}</span>
        )}
      </p>

      <div className="flex items-center justify-between pl-4 mb-3">
        <span className="mono text-[11px] text-[var(--ink-soft)]">
          {agent.tokens} tok · ${agent.cost_usd?.toFixed(4)}{' '}
          <span title="Metered estimate, not provider billing">(est)</span>
        </span>
        <span className="mono text-[10px] text-[var(--ink-soft)]">
          {agent.event_count} events
        </span>
      </div>

      <div className="flex gap-1.5 pl-4 flex-wrap">
        <button
          onClick={() => onAdvance(agent.agent_id)}
          disabled={busy || agent.status === 'killed'}
          className="pressable text-[11px] font-medium px-2.5 py-1 rounded border hover:bg-[var(--canvas)] disabled:opacity-40"
          style={{ borderColor: 'var(--line)' }}
        >
          Step
        </button>
        {agent.status === 'paused' ? (
          <button
            onClick={() => onIntervene(agent.agent_id, 'resume')}
            className="pressable text-[11px] font-medium px-2.5 py-1 rounded border hover:bg-[var(--canvas)]"
            style={{ borderColor: 'var(--line)' }}
          >
            Resume
          </button>
        ) : (
          <button
            onClick={() => onIntervene(agent.agent_id, 'pause')}
            disabled={agent.status === 'killed'}
            className="pressable text-[11px] font-medium px-2.5 py-1 rounded border hover:bg-[var(--canvas)] disabled:opacity-40"
            style={{ borderColor: 'var(--line)' }}
          >
            Pause
          </button>
        )}
        <button
          onClick={() => onReplay(agent.agent_id)}
          className="pressable text-[11px] font-medium px-2.5 py-1 rounded border hover:bg-[var(--canvas)]"
          style={{ borderColor: 'var(--line)' }}
        >
          Replay
        </button>
        <button
          onClick={() => onIntervene(agent.agent_id, 'kill')}
          disabled={agent.status === 'killed'}
          className="pressable text-[11px] font-medium px-2.5 py-1 rounded bg-[var(--red-bg)] text-[var(--red-ink)] disabled:opacity-40"
        >
          Kill
        </button>
      </div>
    </div>
  )
}

function ApprovalCard({ ap, onResolve, busy }) {
  return (
    <div className="rounded-lg border p-3.5 fade-up" style={{ borderColor: 'var(--amber-ink)' }}>
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-[13px] font-medium capitalize">{ap.agent_id}</span>
        <span className="mono text-[11px] text-[var(--ink-soft)]">
          ${ap.amount?.toLocaleString()}
        </span>
      </div>
      <p className="text-[12px] text-[var(--ink)] mb-1">
        wants to <span className="font-medium">{ap.action}</span>
      </p>
      <p className="text-[11px] text-[var(--amber-ink)] mb-3">{ap.reason}</p>
      <div className="flex gap-1.5">
        <button
          onClick={() => onResolve(ap.id, 'approve')}
          disabled={busy}
          className="pressable flex-1 text-[11px] font-medium px-2 py-1.5 rounded bg-[var(--green-bg)] text-[var(--green-ink)] disabled:opacity-40"
        >
          Approve
        </button>
        <button
          onClick={() => onResolve(ap.id, 'deny')}
          disabled={busy}
          className="pressable flex-1 text-[11px] font-medium px-2 py-1.5 rounded bg-[var(--red-bg)] text-[var(--red-ink)] disabled:opacity-40"
        >
          Deny
        </button>
      </div>
    </div>
  )
}

function ReplayDrawer({ agentId, trace, onClose }) {
  if (!agentId) return null
  return (
    <div className="card p-5 fade-up">
      <div className="flex items-center justify-between mb-4">
        <p className="mono text-[11px] uppercase tracking-[0.12em] text-[var(--ink-soft)]">
          Replay · {agentId} · last {trace.length} steps
        </p>
        <button
          onClick={onClose}
          className="pressable text-[11px] px-2 py-0.5 rounded border hover:bg-[var(--canvas)]"
          style={{ borderColor: 'var(--line)' }}
        >
          Close
        </button>
      </div>
      <ol className="space-y-2">
        {trace.map((line) => (
          <li key={line.seq} className="flex items-baseline gap-3 text-[12px]">
            <span className="mono text-[10px] text-[var(--ink-soft)] shrink-0 w-7 text-right">
              {String(line.seq).padStart(2, '0')}
            </span>
            <span className={line.kind === 'action_denied' || line.kind === 'drift_flagged' ? 'text-[var(--red-ink)]' : 'text-[var(--ink)]'}>
              {line.text}
            </span>
          </li>
        ))}
        {trace.length === 0 && (
          <p className="text-sm text-[var(--ink-soft)]">No events yet — step the agent first.</p>
        )}
      </ol>
    </div>
  )
}

/* ------------------------------------------------------------------ */

export default function Tower() {
  const [agents, setAgents] = useState({})
  const [approvals, setApprovals] = useState([])
  const [events, setEvents] = useState([])
  const [replayFor, setReplayFor] = useState(null)
  const [trace, setTrace] = useState([])
  const [seeded, setSeeded] = useState(false)
  const [busy, setBusy] = useState(false)
  const [live, setLive] = useState(false)
  const seenSeq = useRef(new Set())

  const refresh = useCallback(async () => {
    try {
      const [f, a] = await Promise.all([api.fleet(), api.approvals()])
      setAgents(f.agents)
      setApprovals(a.approvals)
      if (Object.keys(f.agents).length > 0) setSeeded(true)
    } catch {
      /* offline — keep last frame */
    }
  }, [])

  // SSE live timeline with polling fallback — the stream is the same one the
  // control plane enforces on, so the UI can never drift from reality.
  useEffect(() => {
    refresh()
    const es = new EventSource('/api/tower/stream')
    es.onopen = () => setLive(true)
    es.onmessage = (msg) => {
      try {
        const ev = JSON.parse(msg.data)
        const key = `${ev.agent_id}:${ev.seq}`
        if (seenSeq.current.has(key)) return
        seenSeq.current.add(key)
        setEvents((prev) => [...prev.slice(-60), ev])
        refresh() // re-fold fleet state on every pushed event
      } catch {
        /* keepalive frame */
      }
    }
    es.onerror = () => {
      setLive(false)
      es.close()
      const t = setInterval(refresh, 2500) // fallback: poll
      return () => clearInterval(t)
    }
    return () => es.close()
  }, [refresh])

  const act = async (fn) => {
    setBusy(true)
    try {
      await fn()
      await refresh()
    } finally {
      setBusy(false)
    }
  }

  const onReplay = async (id) => {
    setReplayFor(id)
    const r = await api.replay(id)
    setTrace(r.trace)
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[1.2fr_1fr_1fr] gap-4 items-start">
      {/* fleet */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <p className="mono text-[11px] uppercase tracking-[0.12em] text-[var(--ink-soft)]">
            Fleet · {Object.keys(agents).length} agents
          </p>
          <div className="flex items-center gap-2">
            <Dot color={live ? 'var(--green-ink)' : 'var(--amber-ink)'} />
            <span className="mono text-[10px] text-[var(--ink-soft)]">
              {live ? 'live' : 'polling'}
            </span>
          </div>
        </div>
        {!seeded ? (
          <div className="card p-6 fade-up text-center">
            <p className="text-sm text-[var(--ink-soft)] mb-4">
              No fleet enrolled. Seed three agents with real signed authority and
              watch them work — then intervene.
            </p>
            <button
              onClick={() => act(api.seed)}
              disabled={busy}
              className="pressable bg-[#1a1a18] text-white text-sm font-medium px-5 py-2.5 rounded-md hover:bg-[#333330] disabled:opacity-60"
            >
              Enroll the fleet
            </button>
          </div>
        ) : (
          <div className="space-y-3">
            {Object.values(agents).map((a) => (
              <FleetRow
                key={a.agent_id}
                agent={a}
                busy={busy}
                onAdvance={(id) => act(() => api.advance(id))}
                onIntervene={(id, verb) => act(() => api.intervene(id, verb))}
                onReplay={onReplay}
              />
            ))}
            <div className="flex gap-2">
              <button
                onClick={() => act(() => api.rogue('deploybot'))}
                disabled={busy}
                className="pressable text-[11px] font-medium px-3 py-1.5 rounded bg-[var(--red-bg)] text-[var(--red-ink)] disabled:opacity-40"
              >
                Inject rogue objective
              </button>
              <a
                href="/api/tower/audit"
                target="_blank"
                rel="noreferrer"
                className="pressable text-[11px] font-medium px-3 py-1.5 rounded border hover:bg-[var(--canvas)]"
                style={{ borderColor: 'var(--line)' }}
              >
                Export audit
              </a>
            </div>
          </div>
        )}
      </div>

      {/* approval queue + replay */}
      <div className="space-y-4">
        <div className="card p-5 fade-up">
          <p className="mono text-[11px] uppercase tracking-[0.12em] text-[var(--ink-soft)] mb-4">
            Approval queue · {approvals.length}
          </p>
          {approvals.length === 0 ? (
            <p className="text-sm text-[var(--ink-soft)]">
              Nothing parked. Risky actions land here for a human decision.
            </p>
          ) : (
            <div className="space-y-3">
              {approvals.map((ap) => (
                <ApprovalCard key={ap.id} ap={ap} busy={busy}
                              onResolve={(id, verb) => act(() => api.resolve(id, verb))} />
              ))}
            </div>
          )}
        </div>
        <ReplayDrawer agentId={replayFor} trace={trace} onClose={() => setReplayFor(null)} />
      </div>

      {/* live event timeline */}
      <div className="card p-5 fade-up">
        <p className="mono text-[11px] uppercase tracking-[0.12em] text-[var(--ink-soft)] mb-4">
          Live event stream
        </p>
        {events.length === 0 && (
          <p className="text-sm text-[var(--ink-soft)]">
            Events appear here the moment an agent acts.
          </p>
        )}
        <div className="space-y-2.5 max-h-[520px] overflow-y-auto">
          {[...events].reverse().map((ev) => (
            <div key={`${ev.agent_id}:${ev.seq}`} className="fade-up">
              <div className="flex items-center justify-between mb-0.5">
                <Badge kind={ev.kind}>{ev.kind.replace(/_/g, ' ')}</Badge>
                <span className="mono text-[10px] text-[var(--ink-soft)]">
                  {ev.agent_id} · #{ev.seq}
                </span>
              </div>
              <p className="text-[12px] text-[var(--ink-soft)] leading-snug">
                {ev.payload?.action ?? ev.payload?.step ?? ev.payload?.intervention ??
                  ev.payload?.blocker ?? ev.payload?.summary ?? ''}
              </p>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
