# C8 Architecture — intent → simulate → present → execute/rollback

SimCore gates a **real** action (a purchase against a shared budget ledger)
behind a simulation whose approval screen is a computed diff. It reuses
TrustCore (C1) unchanged: the same credentials, policy engine, and receipt
log. One deployment, sibling routers on the same FastAPI app.

## The pipeline

```
 intent ─▶ SIMULATE ─▶ PRESENT ─▶ human: approve / tweak / reject ─▶ EXECUTE ─▶ POST-CHECK ─▶ (violation) ─▶ ESCALATE ─▶ ROLLBACK
           (fork)       (diff)                                      (live)         (invariants)
```

1. **Intent** — a human (or agent) proposes a write: `{requester, action: "purchase", amount}`.
2. **Simulate** — deep-copy the live stores (agents, credentials, ledger,
   receipts) into a fork; run the *same* `run_purchase` pipeline against the
   fork (real `TrustService.decide` + ledger spend). Live state untouched.
3. **Present** — `deepdiff(before, after)` over the two snapshots is the
   approval payload, plus a **rollback preview**: the exact compensating
   entries that would reverse this (refund + optional authority revocation).
4. **Human decides in one step** — approve / tweak / reject. No confirm
   dialog; the diff is the screen.
5. **Execute** — on approve, the *same* pipeline runs against live stores
   (real `/api/trust/decide`, real ledger append, real receipt).
6. **Post-check** — a pure invariant (`spent + active_holds ≤ limit`) is
   re-evaluated on live state. Violation → **escalated**, rollback offered.
7. **Rollback** — a compensating `refund` entry referencing the spend (+
   signed revocation of the enabling authority). Append-only: no undo.

## Layers (import-linter enforced)

```
api/main.py  (adapter: /api/sim/* router, Pydantic, HTTP codes)
   │ depends on ▼
core/simcore/application  (SimService, run_purchase pipeline, demo; ports)
   │ depends on ▼
core/simcore/domain  (ledger, fork, diff — pure, zero I/O, no framework)
core/simcore/adapters  (in-memory ledger + simulation stores)
```

SimCore imports TrustCore only through its public surface
(`TrustService` methods + domain types). Six import-linter contracts
(3 from C1 + 3 new) keep the hexagon intact.

## Why one pipeline, two targets

Simulation honesty comes from construction: `run_purchase(trust, ledger, …)`
takes whichever `TrustService`/ledger pair it's given. Fork and live can
never drift in logic within a run. The only residual gap is *time* (a stale
fork) — which is exactly what the post-execution invariant check catches.

## No LLM anywhere on this path

Simulate, diff, execute, post-check, rollback: pure Python + the existing
deterministic Cedar-style policy. Every step appends a receipt with
`llm_called: false` into the same append-only log as C1 decisions — one
forensic trail across both challenges.
