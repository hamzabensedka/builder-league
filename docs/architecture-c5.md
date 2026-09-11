# C5 — The Agent Control Tower architecture

The tower is the **SRE layer for the agent fleet**: one control surface where a
human operates, audits, and intervenes on live agents in real time. Not a
chatbot, not a read-only dashboard — a control plane with teeth, built on the
same append-only spine the agents actually run on.

## The event log is the spine

```
  RestockBot ─┐
  RefundBot ──┼──▶  EventStream (append-only typed events)
  DeployBot ──┘            │
                           ├─▶ Registry   (fleet state, folded)
                           ├─▶ CostMeter  (per agent per task)
                           ├─▶ Anomaly    (drift rules, pure)
                           ├─▶ Replay     (last N steps)
                           └─▶ SSE fan-out ──▶ Operator UI
                                    ▲
        InterventionGate ◀── REST ──┘  (pause · resume · kill · approve · deny)
```

Every agent action, denial, cost entry, drift flag, and human intervention is
one `AgentEvent` in a single ordered log. The registry (what the operator
sees), the cost totals, and the audit export are all **folds over the same
log** — the UI can never show state the control plane didn't see. That is the
honest answer to "not a static dashboard": the dashboard and the enforcement
share one source of truth.

## The control plane has teeth

Interventions are not advisory flags a runaway loop can ignore. Every agent
step calls `gate.check(agent_id)` **before acting**; a paused or killed agent
raises `AgentHalted` on the execution path. Kill is a terminal state, and
killing auto-denies any parked approval — a dead agent's queued action can
never be released (fail-closed, like the rest of the codebase).

Risky actions **park** in an approval queue: when DecisionCore returns
`ask`/`escalate` (missing evidence, over-threshold blast radius), the agent
blocks in `awaiting_approval` until a human approves (release) or denies
(receipted skip).

## Drift detection is deterministic, and containment is automatic

No LLM, no vibes. Pure rules over the stream, each flag carrying its evidence:

| Rule | Signal | Rogue relevance |
| --- | --- | --- |
| `denial_burst` | ≥3 refusals in the last 10 meaningful events | colliding with enforcement |
| `escalation_burst` | ≥2 over-authority demands in the last 8 | keeps requesting what a human must clear |
| `cost_runaway` | cumulative cost > budget | spending out of control |
| `oscillation` | last 4 executed actions read A,B,A,B | flip-flopping at a decision boundary |

Rules match only **meaningful** events (decisions, outcomes, demands, flags) —
routine loop steps are excluded, so a restart-after-denial never masquerades as
churn. On any flag, the tower **auto-pauses** the agent and receipts both the
flag and the pause: containment without human latency, with the human still
making the final call.

## The fleet does real work through real cores

Three scripted agents, step-at-a-time (like C3) so interventions land *between*
steps. Nothing is mocked:

- **RestockBot** (procurement): stock → sized order → purchase gated by
  TrustCore authority + SimCore simulate-before-write on the real ledger.
- **RefundBot** (finance): refund queue → DecisionCore `decide`; clean refunds
  execute, risky ones park.
- **DeployBot** (releases): release → verify change ticket → deploy via
  DecisionCore + TrustCore. The rogue-scenario agent.

## The rogue-agent failure test, concretely

1. `POST /api/tower/scenario/rogue` injects a corrupted objective into
   DeployBot mid-run (it now deploys without a change ticket at absurd blast
   radius).
2. Each rogue demand hits DecisionCore → `ask`/`escalate` (missing ticket, huge
   cost) → parks in the approval queue. The operator denies; the agent retries.
3. `escalation_burst` fires → `drift_flagged` + auto-pause. The UI shows the
   red drift badge.
4. Operator opens **replay**, reads the corrupted objective in the trace, and
   hits **KILL** — terminal; the next step raises.
5. `GET /api/tower/audit` exports the whole incident: injection → demands →
   denials → flag → pause → kill.

Tested end-to-end in `tests/test_tower_rogue.py`, including "the rogue deploy
never executes" and "healthy agents never flag" (no false positives).

## Composition

| Need | Surface |
| --- | --- |
| Signed authority / refusals | TrustCore `decide` / `issue_credential` |
| Step gating | DecisionCore `decide` (refund / deploy / purchase domains) |
| Pre-commit effects | SimCore `simulate` / `execute` on the real ledger |
| Telemetry push | SSE `/api/tower/stream` (polling fallback) |
| Audit export | `EventStream.export()` → `/api/tower/audit` (JSONL) |

All cross-core calls go through application surfaces only — import-linter
contract "TowerCore reaches other cores only via application+domain public
surfaces" is kept. TowerCore is LLM-free (contract-enforced).
