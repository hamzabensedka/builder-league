# Challenge 3 — The Adaptive Agent: Implementation Plan

Status: DRAFT — awaiting review. No code will be written until this plan is approved.

Inherits §0 engineering standards from [2026-09-11-c1-trust-plan.md](2026-09-11-c1-trust-plan.md) unchanged: hexagonal layers, fail-closed security, **no LLM on the change-detection/re-planning path**, append-only receipts, ruff + import-linter enforced. Reuses the proven patterns from [2026-09-11-c2-decision-plan.md](2026-09-11-c2-decision-plan.md) and [2026-09-11-c8-simulate-plan.md](2026-09-11-c8-simulate-plan.md): composition over duplication, in-memory adapter pattern, one-click demo, failure test as a first-class test file.

## 1. What this module is

**AdaptiveCore**: an agent runtime that executes a **multi-step plan against a live world** and continuously re-verifies the assumptions the plan was built on. The loop is **plan → execute → observe → re-evaluate**, with all state persisted in stores (runs, plan versions, revisions, and the event stream are real stored records, not recomputed per request).

The mechanics are designed around the rubric, not the minimum:

- **Change detection is real, never a timer.** Every plan step carries *explicit, typed assumptions* (`price_at_most`, `budget_headroom_at_least`, `authority_valid`, …). Each observation cycle re-evaluates those assumptions — deterministic pure functions — against the current world state. A **contradiction** (an assumption that held at planning time and now fails) is the only thing that can trigger a re-plan. There is no re-prompt loop, no polling cadence that re-plans regardless of change.
- **Inputs are event-driven.** The world changes through an append-only **event stream** (`price_changed`, `hold_placed`, `authority_revoked`, …). Events are pushed into the run (API-injected, arriving asynchronously mid-execution); the agent consumes them via a persisted stream cursor. Where the world *is* a shared module, events have **real effects**: a `hold_placed` event writes a genuine hold to SimCore's budget ledger; an `authority_revoked` event goes through TrustCore's real signed-revocation path.
- **Every revision ships an "I changed my mind because…" trace**: the contradicted assumptions with expected-vs-observed values, the triggering events, a structured diff between the old plan and the new plan, and a deterministic rationale string. Each revision is receipted into TrustCore's append-only log.
- **Composition, not duplication.** AdaptiveCore gates each re-planned step through **DecisionCore** (execute/ask/defer/escalate/refuse per revised action — a re-plan cannot silently upgrade its own authority), previews revised purchases through **SimCore**'s fork-and-diff pipeline before committing, and receipts every revision into **TrustCore**'s append-only log. All through public application/domain surfaces only, import-linter enforced.
- **The non-adaptive baseline is a first-class run mode.** Every scenario can run with adaptation off: the same world, same events, same steps — but contradictions are ignored and the plan executes blindly to its (failed) end-state. The UI shows adaptive and baseline runs side by side.
- **Stability is engineered, not hoped for.** A damping layer (hysteresis margins, per-run revision budget, oscillation detection, human-escalation tripwire) keeps a flapping signal from causing endless re-planning — and when damping trips, the run *escalates to a human*, receipted, instead of oscillating.

**The mission domain**: procurement ops. The agent's goal is *"restock 100 units from an approved supplier within budget and authority."* A plan is a real sequence — verify price, verify authority, place the purchase (a genuine SimCore ledger spend gated by TrustCore credentials), schedule delivery, confirm. This domain is chosen because its world state is *already real* in the monolith: budget = SimCore's ledger, authority = TrustCore's credentials, so two of the three assumption kinds verify against genuinely shared, enforced state rather than a synthetic sandbox.

## 2. Data model

All new state lives in `core/adaptivecore/` using the C1/C8/C2 in-memory adapter pattern (clean-clone runnable). Cross-module state (ledger, credentials, receipts) is read/written only through TrustCore/SimCore/DecisionCore public services.

```
Assumption (explicit, per step — the unit of change detection)
  id: string
  kind: enum("price_at_most", "supplier_available", "budget_headroom_at_least",
             "authority_valid", "delivery_within_days")
  params: dict                    — e.g. {"supplier": "NorthParts", "max_price": 8.0}
  statement: string               — human-readable, e.g. "NorthParts price ≤ $8.00"
  critical: bool                  — a violated critical assumption forces re-plan

PlanStep
  id: string
  index: int
  action: enum("verify_price", "verify_authority", "place_order",
               "schedule_delivery", "confirm_restock")
  params: dict                    — e.g. {"supplier": "NorthParts", "qty": 100}
  assumptions: list[Assumption]
  status: enum("pending", "running", "done", "skipped", "failed", "deferred", "blocked")

Plan (versioned — every re-plan appends a new version, never mutates in place)
  id: string
  goal: string
  version: int                    — 1 at creation, +1 per revision
  steps: list[PlanStep]
  supersedes: string | null       — prior plan id
  created_reason: string          — "initial" | revision id that produced it

WorldEvent (append-only stream — the event-driven input channel)
  id: string
  ts: timestamp
  seq: int                        — stream position; runs consume via cursor
  kind: enum("price_changed", "supplier_unavailable", "hold_placed",
             "hold_released", "authority_revoked", "delivery_delayed")
  payload: dict                   — e.g. {"supplier": "NorthParts", "new_price": 14.0}
  applied_effects: list[str]      — real side effects, e.g. "ledger hold h-… $200",
                                    "credential c-… revoked" — shared modules are real

WorldState (observable reality the assumptions check against)
  suppliers: dict[name -> {price: float, available: bool, delivery_days: int}]
  budget: live SimCore ledger (read through SimService — real shared state)
  authority: live TrustCore credentials (read through TrustService — real shared state)

Run (persisted agent run — the plan/observe/revise loop's state)
  id: string
  scenario: string                — "price_spike" | "budget_squeeze" | "flapping_price"
  mode: enum("adaptive", "baseline")
  goal: string
  plan_id: string                 — current plan version
  status: enum("running", "awaiting_human", "completed", "failed", "escalated")
  event_cursor: int               — how far into the stream this run has observed
  step_log: list[StepOutcome]     — per executed step: decision gate, outcome, receipt ids
  revision_ids: list[string]
  damping: DampingState

DampingState (the stability mechanism, persisted per run)
  revision_count: int
  max_revisions: int              — scenario policy, e.g. 3
  cooldown_until_seq: int         — hysteresis: no re-plan before this stream position
  recent_plan_shapes: list[str]   — canonical plan signatures, for oscillation detection
  last_observed: dict[assumption_id -> observed value]  — min-delta gating

Contradiction (detector output — pure)
  assumption: Assumption
  step_id: string
  expected: string                — e.g. "price ≤ 8.00"
  observed: string                — e.g. "price = 14.00 (event #7, 12:03:41)"
  severity: float                 — normalized overshoot, feeds the min-delta gate
  triggering_event_ids: list[string]

Revision (the "I changed my mind because…" trace — one per re-plan)
  id: string
  ts: timestamp
  run_id: string
  from_plan_id / to_plan_id: string  (versions)
  contradictions: list[Contradiction]
  triggering_events: list[WorldEvent]
  plan_diff: PlanDiff             — structured: steps added/removed/replaced/reparametrized
  rationale: string               — deterministic template over the contradictions
  gates: list[StepGate]           — DecisionCore outcome per revised step (before activation)
  sim_preview: dict | null        — SimCore fork-diff for a revised place_order step
  damping_snapshot: DampingState
  receipt_id: string              — TrustCore append-only receipt

PlanDiff (computed, not narrated)
  added: list[PlanStep]
  removed: list[PlanStep]
  changed: list[{step_id, field, before, after}]
  summary: string                 — e.g. "replaced place_order(NorthParts,100) with
                                     place_order(SouthSupply,100); schedule_delivery re-dated"
```

The detector, re-planner, diff, and damping rules are all pure domain functions. The only impure edges are the stores (ports) and the composed services (TrustCore/SimCore/DecisionCore), injected at the composition root.

## 3. Architecture snapshot

This doubles as the required deliverable ("plan → execute → observe → re-evaluate loop").

```
 World (events pushed in)        ┌──────────────────────── AdaptiveCore ────────────────────────┐
    │  POST /events               │                                                              │
    ▼  (async, mid-run)           │  ┌────────────┐   append-only stream, real side effects      │
 ┌───────────┐  price_changed    │  │ EVENT      │── hold_placed ──▶ SimCore ledger (real write)│
 │ UI judge  │  hold_placed ───────▶│ STREAM     │── authority_revoked ─▶ TrustCore (real      │
 │ / script  │  authority_revoked │  │ + cursor   │                          signed revoke)     │
 └───────────┘                   │  └─────┬──────┘                                              │
                                 │        ▼  observe: new events since cursor                  │
                                 │  ┌────────────┐   re-verify ACTIVE assumptions (pure,       │
                                 │  │ DETECTOR   │   deterministic — NO LLM, no timer)         │
                                 │  │            │──▶ Contradiction[] (expected vs observed)   │
                                 │  └─────┬──────┘                                              │
                                 │        ▼  contradiction AND damping allows                  │
                                 │  ┌────────────┐   revised plan from rules (pure)            │
                                 │  │ REPLANNER  │──▶ Plan vN+1 + PlanDiff + rationale         │
                                 │  └─────┬──────┘                                              │
                                 │        ▼  gate each revised step BEFORE activation          │
                                 │  ┌────────────┐   execute/ask/defer/escalate/refuse         │
                                 │  │ DECISION-  │◀──────────── DecisionCore (C2, unchanged)   │
                                 │  │ GATE       │                                              │
                                 │  └─────┬──────┘                                              │
                                 │        ▼  preview revised purchase BEFORE committing        │
                                 │  ┌────────────┐   fork + diff + invariant                   │
                                 │  │ SIM PREVIEW│◀──────────── SimCore (C8, unchanged)        │
                                 │  └─────┬──────┘                                              │
                                 │        ▼  execute next step, append StepOutcome             │
                                 │  ┌────────────┐   every revision + escalation receipted     │
                                 │  │ RECEIPTS   │────────────▶ TrustCore log (C1, unchanged)  │
                                 │  └────────────┘                                              │
                                 │  ┌────────────┐   hysteresis · revision budget ·            │
                                 │  │ DAMPING    │   oscillation detect → human escalation     │
                                 │  └────────────┘                                              │
                                 └──────────────────────────────────────────────────────────────┘
                                            ▲
              one FastAPI app: /api/adaptive/* alongside /api/trust/*, /api/decision/*, /api/sim/*
```

Key properties:

- **No timer, no LLM anywhere in the module.** Re-planning fires only when the detector produces a contradiction *and* damping permits. Same import-linter no-LLM contract as DecisionCore; `llm_called=false` asserted on every receipt.
- **The world is partly real.** Budget and authority assumptions verify against the actual SimCore ledger and TrustCore credential store; events that change them execute real writes through those services. A stale plan fails against *enforced* state, which is what makes the silent-failure demos honest.
- **Re-plans cannot self-authorize.** Revised steps pass through DecisionCore before activation; a revision whose key step gates to `refuse`/`escalate` flips the run to `awaiting_human`/`escalated` rather than executing.
- **Append-only everything.** Plan versions, revisions, events, and receipts are never updated or deleted; a run's full history is replayable from the stores.

## 4. The 90-second demo, beat by beat

Live on the deployed URL, one-click seeded via `POST /api/adaptive/demo` (same pattern as the other three), then driven from the new **C3 · Adaptive Agent** tab. The tab shows two columns: **adaptive run** (left) and **non-adaptive baseline** (right), same scenario, same event stream.

- **0:00–0:10** — Pick **Scenario A: supplier price spike**, click **Run scenario**. Narration: "The agent will restock 100 units. Its plan assumes NorthParts costs ≤ $8 and the budget has $1,000 headroom. The world is about to break that."
- **0:10–0:25** — Steps tick: `verify_price` ✓ ($7.50), `verify_authority` ✓ (signed grant, real TrustCore verification). Click **Inject: price spike** — a `price_changed` event arrives mid-run: NorthParts → $14.00.
- **0:25–0:45** — **The contradiction fires.** Red banner: "Assumption violated: NorthParts price ≤ $8.00 — observed $14.00 (event #3)". The **"I changed my mind because…"** card appears: contradicted assumption with expected-vs-observed, the triggering event, and the plan diff — `place_order(NorthParts, 100×$8)` → `place_order(SouthSupply, 100×$7.80)`, delivery re-dated. Below it: the DecisionCore gate verdicts for the revised steps (`place_order → execute`, confidence/risk bars) and the SimCore preview diff (budget $0 → $780, invariant green). The run completes within budget.
- **0:45–0:60** — **The baseline column.** Same scenario, adaptation off: steps tick green… then `place_order` executes at $14 — **$1,400 spend against a $1,000 budget**, SimCore's post-check invariant flips it to ESCALATED. "The original plan failed. Blind execution means you find out from the ledger, not the plan." The side-by-side diff — recovered vs escalated — is the demo.
- **0:60–0:75** — **Scenario B: budget squeeze.** A `hold_placed` event (a real $600 hold written to the SimCore ledger by a separate actor) contradicts `budget_headroom_at_least($900)`. Adaptive run re-plans to a partial order (40 units) gated through DecisionCore; baseline runs headlong into the invariant violation.
- **0:75–0:90** — **The failure test** (§5): **Scenario C: flapping price.** NorthParts oscillates $7.9 ↔ $8.1 across the threshold. The detector sees contradictions, but damping engages — hysteresis margin rejects the first flap, the revision budget caps re-plans at 3, and when the oscillation detector sees plan shape A→B→A, the run **escalates to a human** with a receipt: "world unstable: price flapping around $8.00 threshold; 3 revisions consumed." Zoom out on the receipt log: every revision, gate, and escalation receipted. Close on the thesis.

## 5. The failure scenario

**Scenario: oscillation — a flapping signal makes the agent re-plan endlessly, and damping contains it.**

NorthParts' price hovers exactly at the $8.00 assumption threshold and flaps: $7.90 (event) → plan selects NorthParts → $8.10 (event) → contradiction → re-plan to SouthSupply → $7.90 (event) → contradiction on the revised plan's implicit economy assumption → re-plan back to NorthParts → … A naive adaptive agent oscillates forever, burning revisions and never completing — adaptation itself becomes the failure mode.

AdaptiveCore's containment is three deterministic rules, each receipted:

1. **Hysteresis / min-delta gate.** A contradiction only triggers a re-plan if its severity exceeds a margin *and* exceeds the observed value that caused the previous revision on that assumption (price must move beyond the last trigger by >2%). The $7.90↔$8.10 flap (1.25% and 2.5% alternating around an already-triggered value) is absorbed: logged as `contradiction_damped`, no re-plan.
2. **Revision budget.** Each run gets `max_revisions` (3). The third re-plan consumes the budget; the fourth contradiction flips the run to `escalated` — **handed to a human** with the full contradiction history, instead of a fourth re-plan.
3. **Oscillation detection.** The canonical shape of each new plan version (sorted action+param signature) is recorded; if the newest shape matches a shape already seen two revisions ago (A→B→A), the run escalates immediately — the world is unstable around the decision boundary, and the honest answer is a human, not another flip.

The test (`test_adaptive_failure.py`) drives the flap with real events, asserts: damped contradictions produce no plan versions, the revision budget is enforced, the A→B→A pattern triggers escalation, the final state is stable (no further plan churn after escalation even as more flaps arrive), and every damping decision is in the receipt log. Honest "this breaks when…" note for the submission: damping margins are scenario policy, and a genuinely changing world *just under* the hysteresis margin is intentionally absorbed — the run trades responsiveness for stability, and the tradeoff is visible in the damped-contradiction log rather than hidden.

## 6. File/folder structure

Extends the existing tree; C1/C2/C8 modules untouched (additive routes only, shared app factory).

```
builder-league/
├── core/
│   ├── trustcore/                      # C1 — untouched
│   ├── decisioncore/                   # C2 — untouched
│   ├── simcore/                        # C8 — untouched
│   └── adaptivecore/                   # NEW — Module 3
│       ├── domain/
│       │   ├── plans.py                # Plan, PlanStep, Assumption, plan shapes (pure)
│       │   ├── events.py               # WorldEvent stream, cursor math (pure)
│       │   ├── detection.py            # assumption re-verification → Contradiction[] (pure)
│       │   ├── replan.py               # revision rules: contradictions → new Plan (pure)
│       │   ├── plandiff.py             # Plan vN vs vN+1 → PlanDiff (pure)
│       │   └── damping.py              # hysteresis, revision budget, oscillation (pure)
│       ├── application/
│       │   ├── ports.py                # RunStore, PlanStore, EventStream, WorldStore,
│       │   │                           # StepGate (DecisionCore), StepPreview (SimCore),
│       │   │                           # BudgetPort (SimCore), AuthorityPort (TrustCore),
│       │   │                           # AuditTrail (TrustCore)
│       │   ├── services.py             # AdaptiveService: start_run, inject_event,
│       │   │                           # advance, observe/revise cycle, baseline mode
│       │   └── demo.py                 # one-click seed: agents, authority, budget, scenarios
│       └── adapters/
│           └── memory.py               # in-memory RunStore/PlanStore/EventStream/WorldStore
├── api/
│   └── main.py                         # + /api/adaptive/* router (additive only)
├── ui/
│   └── src/
│       ├── App.jsx                     # + fourth tab "C3 · Adaptive Agent"
│       └── adaptive/                   # AdaptiveRun.jsx: scenario picker, step timeline,
│                                       # event feed + injectors, contradiction banner,
│                                       # ChangedMindCard (trace + PlanDiff), gate verdicts,
│                                       # DampingMeter, BaselineColumn (side-by-side)
├── tests/
│   ├── test_assumptions.py             # every assumption kind: holds/violated readings
│   ├── test_detection.py               # contradiction only on real change; no timer path
│   ├── test_replan.py                  # revision rules per scenario; deterministic
│   ├── test_plandiff.py                # add/remove/change diffs are correct
│   ├── test_damping.py                 # hysteresis, budget, A→B→A oscillation
│   ├── test_adaptive_service.py        # full loop: plan→execute→observe→revise, persisted
│   ├── test_adaptive_api.py            # HTTP round trip; event injection; validation
│   ├── test_adaptive_baseline.py       # baseline mode fails silently where adaptive recovers
│   ├── test_adaptive_failure.py        # §5 oscillation containment end-to-end
│   └── test_adaptive_demo.py           # one-click demo seed
├── demo/
│   └── script-c3.md                    # the 90s runbook, beat-timed
├── docs/
│   ├── plans/2026-09-11-c3-adaptive-plan.md   # this file
│   ├── architecture-c3.md              # the §3 diagram, expanded
│   └── thesis-c3.md                    # ≤300-word 2-year thesis on adaptive planning
└── GATES.md                            # extended with A-section ledger (unlazy)
```

Import-linter contracts extended: the same three contracts duplicated for `core.adaptivecore` (domain purity, application↛adapters, layered), plus an **independence contract**: `core.adaptivecore` may import `core.trustcore`, `core.decisioncore`, and `core.simcore` only via their `application`/`domain` public surfaces — never their `adapters`, never `api`, never the UI. A **no-LLM contract**: `core.adaptivecore` may not import any LLM/tracing module at all.

## 7. What I will NOT build (out of scope)

- **No LLM-generated plans or rationales** — plans are deterministic rule products over scenario data; rationale strings are templates over the contradictions. The "I changed my mind because…" trace is computed, never narrated by a model.
- **No generic planner** — one mission domain (procurement restock) with three real scenarios. Generality is claimed via the assumption/detector/replanner pattern, not via half-built extra domains.
- **No persistent database** — same in-memory adapter pattern as C1/C2/C8 (demo resets on redeploy; documented in README). "Persisted state" means run/plan/revision/event state lives in stores across requests, never recomputed — ports make SQLite/Postgres a drop-in later.
- **No real supplier/shipping integrations** — the supplier world is realistic synthetic data in the WorldStore; budget and authority are real shared module state.
- **No websockets/SSE** — events are pushed via API and the UI polls run state (as C1/C2/C8 tabs do); the *agent's* input channel is the event stream (the bonus signal is about the agent's inputs, not the browser's transport).
- **No auto-execution without gates** — no path where a re-plan activates steps that skipped DecisionCore gating; `awaiting_human` states are terminal until a judge clicks through.
- **No multi-tenant auth on the UI** — same demo-surface rationale as C1/C2/C8.

## 8. Risk list: 3 ways this could trip a disqualifier

1. **Risk: "re-prompt every N seconds with no real change detection."**
   Avoidance: there is no timer and no re-prompt. `test_detection.py` asserts the detector returns zero contradictions when events arrive that don't touch active assumptions (change-blind), and that re-planning is *only* reachable through a contradiction — the service has no other code path that creates a plan version (grep-asserted in the security sweep gate). The UI shows the detector's expected-vs-observed reading per assumption, so a judge can watch it *not* fire on irrelevant events.
2. **Risk: the adaptation looks staged — the baseline doesn't really fail.**
   Avoidance: the baseline is the same scenario against the same real shared state with adaptation off, not a scripted animation: `test_adaptive_baseline.py` asserts the baseline's blind `place_order` genuinely breaches SimCore's enforced budget invariant (status flips to escalated by the C8 post-check, not by AdaptiveCore), while the adaptive run completes within budget. Both runs are driven by the same event stream; the only difference is the mode flag.
3. **Risk: hidden logic — the "why" of a re-plan can't be inspected.**
   Avoidance: every revision carries the full machine-readable trace — contradictions with expected/observed values, triggering event ids, structured plan diff, per-step DecisionCore gate outcomes, damping snapshot, and a TrustCore receipt id — all persisted and served via `GET /api/adaptive/runs/{id}`. The UI renders this verbatim; `test_adaptive_service.py` asserts the revision record is complete and that receipt ids resolve to real entries in the append-only log.

---

*Review this plan. On approval I will extend GATES.md with the C3 (A-prefix) ledger, implement TDD red-green (adaptivecore domain → detection → replan → damping → service → API → UI run view → baseline + failure tests), keep ruff + import-linter green with the extended contracts, add the one-click demo button, push to master for Render auto-deploy, verify live, and report against the ledger.*
