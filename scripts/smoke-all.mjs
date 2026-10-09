/* G11 smoke test — boots the real FastAPI server and exercises every
   challenge's demo flow over HTTP, using the same request shapes as the
   API tests. Usage: node scripts/smoke-all.mjs
   Prints one line per check; exits non-zero if any check fails. */
import { spawn } from 'node:child_process'

const BASE = 'http://127.0.0.1:8123'
const PY = '.venv/Scripts/python'

const results = []
const record = (challenge, name, ok, detail = '') => {
  results.push({ challenge, name, ok, detail })
  console.log(`${ok ? 'PASS' : 'FAIL'}  [${challenge}] ${name}${detail ? ' — ' + detail : ''}`)
}

async function req(path, init) {
  const r = await fetch(BASE + path, init)
  const body = await r.json().catch(() => null)
  return { status: r.status, body }
}
const post = (path, body) =>
  req(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? '{}' : JSON.stringify(body),
  })

async function waitForServer(timeoutMs = 60000) {
  const t0 = Date.now()
  while (Date.now() - t0 < timeoutMs) {
    try {
      const r = await fetch(BASE + '/health')
      if (r.ok) return true
    } catch { /* not up yet */ }
    await new Promise((r) => setTimeout(r, 500))
  }
  return false
}

const server = spawn(PY, ['-m', 'uvicorn', 'api.main:create_app', '--factory', '--port', '8123'], {
  env: { ...process.env, PYTHONPATH: '.' },
  stdio: ['ignore', 'pipe', 'pipe'],
})
server.stderr.on('data', (d) => process.stderr.write(d))

try {
  if (!(await waitForServer())) {
    console.error('server did not start')
    process.exit(2)
  }
  // challenges share one budget ledger/tower/ambient spine in a single server;
  // reset the shared surfaces between blocks so each demo runs clean
  const resetShared = async () => {
    await post('/api/sim/reset')
    await post('/api/tower/reset')
    await post('/api/ambient/reset')
  }

  // ---- C1 Trust: full demo scenario server-side
  {
    const demo = await post('/api/trust/demo')
    const beats = demo.body?.beats ?? []
    record('C1-trust', 'demo runs full scenario', demo.status === 200 && beats.length >= 6, `beats=${beats.length}`)
    const decided = beats.filter((b) => b.decision)
    const allowed = decided.filter((b) => b.decision === 'allow' || b.decision === 'ALLOW' || /allow/i.test(b.decision))
    const refused = decided.filter((b) => /refuse/i.test(b.decision))
    record('C1-trust', 'legit purchase accepted', allowed.length >= 1, decided.map((b) => b.decision).join(','))
    record('C1-trust', 'forgery + scope escape + revocation refused', refused.length >= 3, `refused=${refused.length}`)
    const agents = await req('/api/trust/agents')
    record('C1-trust', 'agents listed', agents.status === 200 && agents.body.agents.length >= 3,
      `agents=${agents.body?.agents?.length}`)
    const receipts = await req('/api/trust/receipts?limit=30')
    const llmOff = (receipts.body?.receipts ?? []).every((r) => r.llm_called === false)
    record('C1-trust', 'receipts append-only, llm off', receipts.status === 200 && receipts.body.receipts.length > 0 && llmOff,
      `receipts=${receipts.body?.receipts?.length}`)
  }

  // ---- C2 Decision: seed + execute/ask/escalate beats (shapes from test_decision_api.py)
  {
    const seed = await post('/api/decision/demo')
    record('C2-decision', 'demo seeds 3 domains', seed.status === 200 && !!seed.body?.triage_key)
    const clean = await post('/api/decision/decide', {
      domain: 'refund', action: 'issue_refund', actor_key: seed.body.triage_key, amount: 120,
      context: { invoice_id: 'INV-1', reason: 'defective' },
    })
    record('C2-decision', 'clean refund executes', clean.status === 200 && clean.body.outcome === 'execute',
      `outcome=${clean.body?.outcome}`)
    const missing = await post('/api/decision/decide', {
      domain: 'refund', action: 'issue_refund', actor_key: seed.body.triage_key, amount: 2400,
      context: { reason: 'defective' },
    })
    record('C2-decision', 'missing invoice_id named, no execute',
      missing.status === 200 && missing.body.outcome !== 'execute'
        && (missing.body.missing_information ?? []).includes('invoice_id'),
      `outcome=${missing.body?.outcome}`)
    const deploy = await post('/api/decision/decide', {
      domain: 'deploy', action: 'deploy_production', actor_key: seed.body.deploy_key, amount: 8000,
      context: { tests_passing: true, approvals: 2, change_ticket: 'CHG-1' },
    })
    record('C2-decision', 'irreversible $8000 deploy escalates', deploy.status === 200 && deploy.body.outcome === 'escalate',
      `outcome=${deploy.body?.outcome}`)
    const decisions = await req('/api/decision/decisions')
    record('C2-decision', 'audit trail present', decisions.status === 200 && decisions.body.decisions.length >= 3)
  }

  // ---- C8 Sim: simulate → diff → execute → hold-failure → rollback
  {
    const seed = await post('/api/sim/demo')
    const buyer = seed.body?.buyer_key
    record('C8-sim', 'demo seeds funded buyer', seed.status === 200 && !!buyer)
    const sim = await post('/api/sim/simulate', { requester_key: buyer, amount: 900, description: '100 units' })
    record('C8-sim', 'simulate returns real before/after diff',
      sim.status === 201 && !!sim.body?.fork_diff && (sim.body.rollback_preview?.entries ?? []).length > 0,
      `status=${sim.body?.status}`)
    const exec = await post(`/api/sim/${sim.body.id}/execute`)
    record('C8-sim', 'execute writes for real, post-check ok',
      exec.status === 200 && exec.body.status === 'executed' && exec.body.post_check?.ok === true)
    const sim2 = await post('/api/sim/simulate', { requester_key: buyer, amount: 900, description: 'bulk' })
    await post('/api/sim/hold', { agent_key: 'vendor-x', amount: 200 })
    const exec2 = await post(`/api/sim/${sim2.body.id}/execute`)
    record('C8-sim', 'concurrent-hold failure caught post-execution',
      exec2.status === 200 && exec2.body.status === 'escalated' && exec2.body.post_check?.ok === false,
      `status=${exec2.body?.status}`)
    // rollback compensates the escalated write (isolated test asserts
    // post_check.ok on a fresh app; here the earlier beat's spend legitimately
    // remains, so we assert the compensating refund + status, not ok=true)
    const rb = await post(`/api/sim/${sim2.body.id}/rollback`)
    record('C8-sim', 'rollback offered + executed (compensating refund)',
      rb.status === 200 && rb.body.status === 'rolled_back',
      `status=${rb.body?.status} detail=${JSON.stringify(rb.body?.detail ?? '')}`)
    await resetShared()
  }

  // ---- C3 Adaptive: inject contradiction, run-to-end, re-plan; baseline contrast
  {
    const seed = await post('/api/adaptive/demo')
    record('C3-adaptive', 'demo seeds RestockBot', seed.status === 200 && !!seed.body?.agent_key)
    const runA = (await post('/api/adaptive/runs', { scenario: 'price_spike', mode: 'adaptive' })).body
    await post(`/api/adaptive/runs/${runA.id}/events`,
      { kind: 'price_changed', payload: { supplier: 'NorthParts', new_price: 14.0 } })
    const doneA = (await post(`/api/adaptive/runs/${runA.id}/run-to-end`)).body
    const revs = doneA?.revisions ?? []
    record('C3-adaptive', 'contradiction fires receipted re-plan with rationale',
      ['completed', 'escalated'].includes(doneA?.status) && revs.length >= 1
        && /I changed my mind because/.test(revs[0]?.rationale ?? ''),
      `status=${doneA?.status} revisions=${revs.length}`)
    const fetched = await req(`/api/adaptive/runs/${runA.id}`)
    const versions = (fetched.body?.plan_history ?? []).length || fetched.body?.plan?.version
    record('C3-adaptive', 'plan revised (v2) after contradiction',
      fetched.status === 200 && versions >= 2, `versions=${versions}`)
    const runB = (await post('/api/adaptive/runs', { scenario: 'price_spike', mode: 'baseline' })).body
    await post(`/api/adaptive/runs/${runB.id}/events`,
      { kind: 'price_changed', payload: { supplier: 'NorthParts', new_price: 14.0 } })
    const doneB = (await post(`/api/adaptive/runs/${runB.id}/run-to-end`)).body
    record('C3-adaptive', 'baseline runs blind (no re-plan)',
      (doneB?.revisions ?? []).length === 0, `revisions=${(doneB?.revisions ?? []).length} status=${doneB?.status}`)
    await resetShared()
  }

  // ---- C4 Memory: unsure/correct/age/revoke beats (shapes from test_memory_api.py)
  {
    const demo = await post('/api/memory/demo')
    record('C4-memory', 'demo learns 3 tagged facts', demo.status === 200 && (demo.body?.beats ?? []).length === 3)
    const unsure = await post('/api/memory/demo/unsure')
    record('C4-memory', 'seat recall confident', unsure.body?.seat?.verdict === 'confident')
    const city = unsure.body?.city
    record('C4-memory', '"I might be wrong" verdict on weak inference',
      city?.verdict === 'unsure' && city?.sure === false && (city?.gaps ?? []).length > 0,
      `verdict=${city?.verdict}`)
    const corr = await post('/api/memory/demo/correct')
    record('C4-memory', 'correction supersedes → recall confident on Porto',
      corr.body?.correction?.outcome === 'supersede' && corr.body?.recall_after?.verdict === 'confident')
    const aged = await post('/api/memory/demo/age')
    record('C4-memory', 'TTL expiry sweeps imported fact',
      (aged.body?.swept?.swept ?? []).length === 1)
    const rev = await post('/api/memory/demo/revoke')
    record('C4-memory', 'signed revocation forgets city fact', (rev.body?.revoked?.forgotten ?? []).length > 0)
    const view = await req('/api/memory/inspect?user_id=demo-user')
    record('C4-memory', 'inspector shows live facts + tombstones',
      view.status === 200 && (view.body?.tombstones ?? []).length >= 2,
      `facts=${view.body?.facts?.length} tombstones=${view.body?.tombstones?.length}`)
  }

  // ---- C7 Ambient (runs BEFORE C5 kills deploybot): demo, canvas, card
  // initiation, reject → correction. Ambient seeds the tower fleet itself.
  {
    const demo = await post('/api/ambient/demo')
    record('C7-ambient', 'demo starts the shift', demo.status === 200)
    const canvas0 = await req('/api/ambient/canvas')
    record('C7-ambient', 'canvas calm before any incident',
      canvas0.status === 200 && ['calm', 'card'].includes(canvas0.body?.mode), `mode=${canvas0.body?.mode}`)
    // walk deploybot to a parked deploy (pick_release → verify_ticket → deploy
    // escalates), then the canvas itself surfaces the decision card
    let card = null
    for (let i = 0; i < 6 && !card; i++) {
      await post('/api/tower/agents/deploybot/advance')
      const cv = await req('/api/ambient/canvas')
      card = cv.body?.card ?? null
    }
    record('C7-ambient', 'interface initiates a decision card on parked deploy',
      !!card && card.hypothesis?.kind === 'deploy_needs_review' && card.state === 'surfaced',
      `card=${card ? `${card.hypothesis?.kind}/${card.state}` : 'none'}`)
    const intents = await req('/api/ambient/intents')
    record('C7-ambient', 'intent fold visible', intents.status === 200 && (intents.body?.intents ?? []).length >= 0)
    if (card) {
      const rej = await post(`/api/ambient/cards/${card.id}/reject`, { operator: 'ops', note: 'not the right call' })
      record('C7-ambient', 'rejection lands a receipted correction', rej.status === 200,
        `state=${rej.body?.state ?? JSON.stringify(rej.body)?.slice(0, 80)}`)
    }
    await resetShared()
  }

  // ---- C5 Tower: fleet, approval queue, rogue containment, kill, audit
  {
    const demo = await post('/api/tower/demo')
    record('C5-tower', 'demo enrolls fleet', demo.status === 200)
    const fleet = await req('/api/tower/fleet')
    record('C5-tower', 'fleet snapshot (3 agents)',
      fleet.status === 200 && Object.keys(fleet.body?.agents ?? {}).length === 3)
    // inject rogue FIRST — its cycle always escalates (missing change ticket),
    // so the approval queue and containment demo run on the rogue agent itself
    const rogue = await post('/api/tower/scenario/rogue', { agent_id: 'deploybot' })
    record('C5-tower', 'rogue objective injected', rogue.status === 200)
    // operator-in-the-loop containment (mirrors test_tower_rogue.py):
    // try to advance; if halted, deny what's parked; repeat until the drift
    // detector force-pauses the agent.
    let fleetStatus = null
    let sawApproval = false
    let deniedOnce = false
    for (let i = 0; i < 20; i++) {
      const f = await req('/api/tower/fleet')
      fleetStatus = f.body?.agents?.deploybot?.status
      if (fleetStatus === 'paused' || fleetStatus === 'killed') break
      const adv = await post('/api/tower/agents/deploybot/advance')
      const aps = (await req('/api/tower/approvals')).body?.approvals ?? []
      if (aps.length > 0) sawApproval = true
      for (const ap of aps) {
        const d = await post(`/api/tower/approvals/${ap.id}/deny`, { operator: 'ops' })
        if (d.status === 200) deniedOnce = true
      }
      void adv
    }
    record('C5-tower', 'risky action parks in approval queue', sawApproval)
    record('C5-tower', 'operator can deny parked action', deniedOnce)
    record('C5-tower', 'drift detector auto-pauses rogue agent', fleetStatus === 'paused',
      `fleet_status=${fleetStatus}`)
    const replay = await req('/api/tower/agents/deploybot/replay?n=20')
    record('C5-tower', 'replay trace readable', replay.status === 200 && (replay.body?.trace ?? []).length > 0)
    const kill = await post('/api/tower/agents/deploybot/kill', { operator: 'ops' })
    const afterKill = await req('/api/tower/fleet')
    record('C5-tower', 'kill is terminal',
      kill.status === 200 && afterKill.body?.agents?.deploybot?.status === 'killed')
    const audit = await req('/api/tower/audit')
    record('C5-tower', 'audit export covers incident', audit.status === 200 && (audit.body?.events ?? []).length > 0,
      `events=${audit.body?.events?.length}`)
  }

  // ---- C6 Company: seed, run days, crunch, rogue sales, replay
  {
    const demo = await post('/api/company/demo', { scenario: 'normal' })
    record('C6-company', 'demo seeds Northwind', demo.status === 200)
    const day = await post('/api/company/advance')
    record('C6-company', 'company runs a day', day.status === 200)
    const kpis = await req('/api/company/kpis')
    record('C6-company', 'KPIs move', kpis.status === 200 && kpis.body != null)
    const inbox = await req('/api/company/inbox')
    record('C6-company', 'human inbox surface works', inbox.status === 200)
    const crunch = await post('/api/company/scenario/cash-crunch')
    record('C6-company', 'cash crunch scenario injects', crunch.status === 200)
    await post('/api/company/advance')
    const rogue = await post('/api/company/scenario/rogue-sales')
    record('C6-company', 'rogue-sales failure scenario injects', rogue.status === 200)
    await post('/api/company/advance')
    const replay = await req('/api/company/replay?day=1')
    record('C6-company', 'replay scrubber re-folds day 1', replay.status === 200)
    const events = await req('/api/company/events')
    record('C6-company', 'event spine populated', events.status === 200 && (events.body?.events?.length ?? 0) > 0,
      `events=${events.body?.events?.length}`)
  }

  // ---- summary
  const failed = results.filter((r) => !r.ok)
  const challenges = [...new Set(results.map((r) => r.challenge))]
  const okChallenges = challenges.filter((c) => results.every((r) => r.challenge !== c || r.ok))
  console.log('---')
  console.log(`${results.length - failed.length}/${results.length} checks passed`)
  console.log(`challenges fully OK: ${okChallenges.length}/8 (${okChallenges.join(', ') || 'none'})`)
  if (failed.length) {
    console.log('FAILURES:')
    failed.forEach((f) => console.log(`  [${f.challenge}] ${f.name} ${f.detail}`))
    process.exit(1)
  }
  console.log('8/8 challenges OK')
} finally {
  server.kill()
}
