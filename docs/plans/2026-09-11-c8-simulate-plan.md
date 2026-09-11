# Challenge 8 — Simulate Before You Act: Implementation Plan

Status: DRAFT — awaiting review. No code will be written until this plan is approved.

Urgency note: C8 was already submitted on the platform by mistake. This build must land fast so the live demo matches the submission; the entry notes will then be updated with the real repo/demo URLs.

Inherits §0 engineering standards from [2026-09-11-c1-trust-plan.md](2026-09-11-c1-trust-plan.md) unchanged: hexagonal layers, fail-closed security, no LLM on the enforcement path, append-only receipts, ruff + import-linter enforced.

## 1. What this module is

**SimCore**: a simulation gate that sits in front of a *real* mutating action. Before any execution, SimCore deep-copies the live TrustCore state (agents, credentials, budget ledger, receipt log), runs the exact same decision pipeline against the fork, and produces a **structured diff** of what would change. The human reviews that diff — not a confirm dialog — and approves, tweaks, or rejects in one step. On approval, the same action executes against the live service through the real `POST /api/trust/decide` path, so simulation and execution can never drift apart in logic.

The real high-stakes action being gated: **a purchase against a shared budget ledger** (send money). This is a genuine write: executing appends a spend entry to the append-only `BudgetLedger` and a decision receipt to the TrustCore receipt log. Because everything is append-only, **rollback is a compensating action** (a reversal/refund entry plus, where appropriate, revocation of the authority that enabled the purchase) — shown in the diff *before* approval, never promised as an "undo".

Both bonus signals are the design, not extras:

- **Diff-style before/after**: the approval screen renders the deepdiff of forked-state vs live-state — records added, balances changed, receipts appended — row by row.
- **Real API, not a mock**: simulation runs the real `TrustService.decide` + ledger write against a fork of the real stores; execution runs the identical code against the live stores over the same HTTP routes.

## 2. Data model

Extends C1's model. All new state lives in `core/simcore/` and uses the same in-memory adapter pattern as C1 (clean-clone runnable, zero external services); the receipt log stays append-only.

```
BudgetLedger (NEW — the real shared resource that makes purchases high-stakes)
  entries: append-only list of LedgerEntry

LedgerEntry
  id: string (uuid)
  ts: timestamp
  kind: enum("hold", "spend", "refund")     — hold reserves, spend executes, refund compensates
  agent_key: string (Ed25519 public key)
  amount: numeric
  currency: "USD"
  reference: string                          — simulation id / decision receipt id
  compensates: string | null                 — LedgerEntry.id this entry reverses (refund only)

Simulation
  id: string (uuid)
  created_at: timestamp
  intent: jsonb            — {requester_key, action:"purchase", amount, description}
  status: enum("pending","approved","rejected","executed","rolled_back","escalated")
  fork_diff: jsonb         — deepdiff of fork vs live state (the approval payload)
  rollback_preview: jsonb  — the compensating entries that WOULD reverse this, shown pre-approval
  predicted_effects: jsonb — projected balance, new receipt, scope usage after action
  decision_receipt_id: string | null         — set on execution
  post_check: jsonb | null — invariant re-verification result after execution
```

Invariants enforced post-execution (the safety net): `Σ(spend) - Σ(refund) + Σ(active holds) ≤ policy limit` per authority scope. The post-execution check is a pure function re-run against live state — no LLM anywhere on simulate/gate/execute/rollback paths.

## 3. Architecture snapshot

This doubles as the required deliverable ("intent → simulate → present → execute/rollback").

```
 Human (UI)                ┌──────────────────────────── SimCore ────────────────────────────┐
    │  intent              │                                                                │
    ▼                      │  ┌──────────┐   deep-copy live stores                          │
 POST /api/sim/  ────────▶ │  │  FORK    │◀── agents, credentials, BudgetLedger, receipts    │
 simulate                  │  └────┬─────┘                                                   │
                           │       ▼  run REAL pipeline on fork (TrustService.decide        │
                           │  ┌──────────┐    + ledger spend entry)                          │
                           │  │ EXECUTE- │                                                   │
                           │  │ ON-FORK  │                                                   │
                           │  └────┬─────┘                                                   │
                           │       ▼  deepdiff(fork, live)                                   │
                           │  ┌──────────┐   + rollback preview (compensating entries)       │
                           │  │ DIFFVIEW │──────────┐                                        │
                           │  └──────────┘          ▼                                        │
    ◀───────────────────── │                 GET /api/sim/{id}  →  before/after records      │
    │  approve / tweak /   │                                                                │
    ▼  reject (one step)   │                                                                │
 POST /api/sim/{id}/  ───▶ │  ┌──────────┐   LIVE: real /api/trust/decide + real ledger      │
 execute                   │  │ EXECUTE  │   write (same code path as the fork run)           │
                           │  └────┬─────┘                                                   │
                           │       ▼  re-check invariants on live state                      │
                           │  ┌──────────┐  violation → status=escalated, rollback offered   │
                           │  │ POSTCHK  │──────────▶ POST /api/sim/{id}/rollback            │
                           │  └──────────┘          (appends refund/reversal, optional       │
                           │                          authority revocation)                  │
                           └─────────────────────────────────────────────────────────────────┘
                                           ▲
                            TrustCore (C1, unchanged): credentials, policy engine, receipts
```

Key properties:

- **One pipeline, two targets.** Fork and live execution call the same `PurchasePipeline` function; only the injected stores differ. Drift between simulation and reality is structurally impossible within a single run; drift *across* runs (concurrency) is exactly what the failure test exercises.
- **Diff is computed, not narrated.** `deepdiff.DeepDiff` over serialized store snapshots produces the approval payload; the UI renders it verbatim.
- **Rollback is real.** Reversal = appending compensating ledger entries (+ optional signed credential revocation through the existing `/api/trust/revoke`), all receipt-logged. Append-only preserved — nothing is ever deleted.
- **No LLM on any path.** Simulation, diff, execution, post-check, and rollback are pure Python + existing TrustCore policy.

## 4. The 90-second demo, beat by beat

Live on the deployed URL, one-click seeded via `POST /api/sim/demo` (same pattern as C1's `/api/trust/demo`), then driven in the UI:

- **0:00–0:10** — Screen: SimCore gate view. Narration: "BuyerBot wants to spend $900 of its $1,000 purchase authority. Nothing executes until a human reviews the consequences."
- **0:10–0:25** — Click **Simulate purchase $900**. The approval screen appears: a **diff view**, left "before", right "after" — ledger balance $0 → $900, +1 `spend` entry, +1 decision receipt (ALLOW, authority matched), authority scope usage 0% → 90%. Below: **Rollback path** — "reversal entry: refund $900 referencing spend #…, optionally revoke AuthorityGrant …c41d". No confirm dialog; the diff *is* the screen.
- **0:25–0:40** — Click **Approve & execute**. Live `/api/trust/decide` runs, ledger entry appends, receipt appears in the C1 receipt feed. Post-check green. "Simulation and execution were the same code — the diff told the truth."
- **0:40–1:00** — **The failure test.** New intent: purchase $900 (90% of limit) — simulation passes. Before approving, click **Inject concurrent hold $200** (a second agent reserves budget in between). Approve anyway → execution succeeds but the **post-execution invariant check** catches `900 + 200 hold > 1000 limit` → status flips to **ESCALATED**, red banner, **Rollback offered** with the exact compensating entries pre-computed.
- **1:00–1:20** — Click **Rollback**. A `refund` entry referencing the spend appends (and the AuthorityGrant is revoked via the real C1 signed-revocation path). Diff view updates: balance back to $0 (+hold), receipt log shows the full forensic chain: simulate → execute → escalate → rollback. "Undo isn't a promise — it's a logged, verifiable reversal."
- **1:20–1:30** — Close on thesis slide: "In two years, no agent writes without a simulated, human-reviewed diff."

## 5. The failure scenario

**Scenario: simulation under-predicts a side effect (TOCTOU on a shared budget), caught downstream.**

1. BuyerBot simulates a $900 purchase against a $1,000 authority scope. Simulation correctly predicts ALLOW — at fork time, no holds exist.
2. **Between simulation and execution**, VendorBot's agent places a legitimate $200 hold on the same budget (a concurrent write the simulation could not see). This is the classic time-of-check/time-of-use gap — the simulation is *correct but stale*.
3. Human approves; execution proceeds (the decision itself is still policy-valid — BuyerBot's authority genuinely covers $900).
4. The **post-execution invariant check** — a pure function over live ledger state: `spent + active_holds ≤ limit` — fails: $900 + $200 > $1,000.
5. Consequences shown, not just logged: simulation status → `escalated`, the UI surfaces the violated invariant with the offending entries, and offers the pre-computed rollback. One click appends the compensating `refund` entry (and optionally revokes the authority), returning the system to a safe state with a complete audit trail.

Defense-in-depth note for judges: this demonstrates the brief's exact requirement — "simulation under-predicts a side effect, show the safety net" — with the safety net being a deterministic invariant check plus a real compensating action, not an apology message.

## 6. File/folder structure

Extends the existing tree; nothing in C1 is modified except additive routes and the shared app factory.

```
builder-league/
├── core/
│   ├── trustcore/                      # C1 — untouched
│   └── simcore/                        # NEW — Module 8
│       ├── domain/
│       │   ├── ledger.py               # BudgetLedger, LedgerEntry, invariant checks (pure)
│       │   ├── fork.py                 # deep-copy snapshot of stores (pure)
│       │   └── diff.py                 # deepdiff wrapper → approval payload (pure)
│       ├── application/
│       │   ├── ports.py                # SimulationStore, LedgerStore protocols
│       │   ├── pipeline.py             # PurchasePipeline: decide + ledger write (fork or live)
│       │   └── services.py             # SimService: simulate/execute/rollback/post-check/demo
│       └── adapters/
│           └── memory.py               # in-memory SimulationStore, LedgerStore
├── api/
│   └── main.py                         # + /api/sim/* router (additive only)
├── ui/
│   └── src/
│       ├── App.jsx                     # + SimGate tab
│       └── sim/                        # DiffView, RollbackPreview, EscalationBanner
├── tests/
│   ├── test_ledger.py                  # invariant math, refund compensation
│   ├── test_fork_diff.py               # fork isolation (live untouched), diff correctness
│   ├── test_pipeline.py                # fork run ≡ live run on identical state
│   ├── test_sim_api.py                 # simulate → execute → rollback round trip
│   └── test_failure_scenario.py        # concurrent hold → post-check → escalate → rollback
├── demo/
│   └── script-c8.md                    # the 90s runbook, beat-timed
├── docs/
│   ├── plans/2026-09-11-c8-simulate-plan.md   # this file
│   ├── architecture-c8.md              # the §3 diagram, expanded
│   └── thesis-c8.md                    # ≤300-word 2-year thesis on simulation-gated agents
└── GATES.md                            # extended with C-section ledger (unlazy)
```

Import-linter contracts extended: same three contracts duplicated for `core.simcore` (domain purity, application↛adapters, layered), plus a new independence contract: `core.simcore` may import `core.trustcore` only via its `application.ports`/`domain` public surface — never `api`, never the UI.

## 7. What I will NOT build (out of scope)

- **No generic "simulate any action" framework** — one real action (purchase against the budget ledger) gated end-to-end. Generality is claimed via the pipeline pattern, not via half-built extra actions.
- **No persistent database migration** — SimCore state uses the same in-memory adapter pattern as C1 (demo resets on redeploy; documented in README). The ports make SQLite/Postgres a drop-in later.
- **No LLM-generated diff narration** — the diff speaks for itself; receipts keep C1's deterministic reasoning strings.
- **No multi-tenant auth on the simulation UI** — same demo-surface rationale as C1.
- **No real money/payment rails** — the ledger is the money; it is real state with real invariants, which is what the brief gates.
- **No undo/delete paths anywhere** — rollback is compensating entries only; append-only is preserved as a hard rule.

## 8. Risk list: 3 ways this could trip a disqualifier

1. **Risk: "a confirm dialog dressed up as simulation."**
   Avoidance: the approval screen renders *only* the computed deepdiff (before/after records, balance changes, new entries) plus the rollback path. There is no standalone "are you sure?" — approval is meaningless without the diff, and `test_fork_diff.py` asserts the diff payload is non-empty, state-derived, and matches what execution actually produces (`test_pipeline.py`: fork diff ≡ live outcome on identical state).
2. **Risk: "no real action being gated."**
   Avoidance: execution writes through the real `POST /api/trust/decide` (C1's production path, with Ed25519-verified credentials and policy evaluation) plus a real ledger mutation that the post-check enforces invariants against. The demo's escalation proves the state is real: a concurrent hold genuinely changes the outcome.
3. **Risk: the failure test looks staged — the safety net never really fires.**
   Avoidance: the concurrent hold is injected *between* simulate and execute through the real API as a separate actor, not a flag; `test_failure_scenario.py` asserts the invariant violation is detected *post-execution* (not at simulate time), that status transitions to `escalated`, and that rollback restores the invariant — verified by re-running the invariant check, with the full chain present in the receipt log.

---

*Review this plan. On approval I will extend GATES.md with the C8 ledger, implement TDD red-green (simcore domain → pipeline → API → UI diff view → failure scenario), keep ruff + import-linter green, add the one-click demo, push to master for Render auto-deploy, verify live, and report against the ledger.*
