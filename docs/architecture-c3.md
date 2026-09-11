# C3 — AdaptiveCore architecture

The adaptive agent is a **plan → execute → observe → re-evaluate** loop with
persisted state, deterministic change detection, and damping that keeps
adaptation from becoming the bug. No LLM anywhere: detection is pure
assumption re-verification, re-planning is a rule product, both are
import-linter enforced.

## The loop

```
            ┌──────────────────────────────────────────────┐
            │                event stream                   │
            │  price_changed · hold_placed · authority_…    │
            └───────────────┬──────────────────────────────┘
                            │ (real side effects via C1/C8)
   plan vN ──▶ execute ONE step ──▶ observe ──▶ assumptions still hold?
        ▲            │                    │            │
        │            │ (gate via C2,      │            ├─ yes ─▶ next step
        │            │  effects via C1/C8)│            │
        │            │                    │            └─ contradiction
        │            │                    │               │
        │            │                    │               ▼
        │            │                    │         damping gate
        │            │                    │     (hysteresis · budget · A→B→A)
        │            │                    │               │
        └────────────┴──── plan vN+1 ◀────┴── re-planner (pure rules)
                     "I changed my mind because…" + PlanDiff + receipt
```

- **One step per `advance`.** The loop is deliberately step-at-a-time so world
  events land *between* steps — change detection mid-execution is the point.
- **Everything persists.** Runs, plan versions, revisions, and the event
  stream live in append-only stores; a run can be re-read across calls with
  zero recomputation.

## Change detection is real

Every step carries **explicit typed assumptions** (`price_at_most`,
`budget_headroom_at_least`, `authority_valid`, `supplier_available`,
`delivery_within_days`, `better_alternative`). The detector
(`domain/detection.py`) re-verifies each against a **WorldSnapshot** assembled
from live shared state: the supplier world, SimCore's real ledger (budget
committed), TrustCore's real credentials (authority). A contradiction is the
ONLY path to a re-plan — there is no timer and no re-prompt loop anywhere in
the service. Two properties are tested directly:

- **Change-blind**: an event touching no active assumption yields zero
  contradictions (`test_irrelevant_event_no_revision`).
- **Cascade**: a world change that breaks an assumption *after* its step ran
  still fires, because pending steps were planned on that reading.

`better_alternative` is the stability signal: non-critical, fires when the
world *improved* enough to beat the chosen supplier. Without it the agent
can't see "the thing I rejected is now best" — the raw material of
oscillation.

## Re-planning is a rule product

`domain/replan.py` picks the cheapest feasible supplier within the mission's
price cap and delivery window, re-sizes the order to fit observed budget
headroom, and carries execution history forward. Same inputs → same plan
(tested). If nothing is feasible it returns `None` and the run escalates
rather than inventing a plan. Every revised `place_order` is gated through
DecisionCore and previewed through SimCore's fork **before** the new plan
activates — a re-plan can never self-authorize.

## The trace

Every revision records: contradictions (expected vs observed, with
triggering event ids), the full triggering events, a structural `PlanDiff`
(added/removed/changed fields), a deterministic rationale sentence, gate
verdicts, the SimCore preview, the damping snapshot, and a TrustCore receipt
id that resolves in the append-only audit log.

## Damping — the containment

Three deterministic rules (`domain/damping.py`), each receipted:

1. **Hysteresis (min-delta)**: a contradiction on a kind that already
   triggered only re-triggers when the observed value moved beyond the last
   trigger by > max(2%, 1¢). Sub-margin flaps are absorbed.
2. **Revision budget**: at most 3 re-plans per run; the 4th contradiction
   escalates to a human.
3. **Oscillation (A→B→A)**: plans carry a *choice signature* (supplier +
   sizing bucket, price-insensitive). If a candidate re-plan repeats the
   choice from two revisions ago, the world is unstable around the decision
   boundary — escalate immediately.

## Baseline mode

The non-adaptive baseline runs the same scenario and the same events with
detection disabled: it executes the stale plan blindly and collides with
enforced reality — SimCore's budget invariant (`spent + holds ≤ limit`) or
TrustCore's revoked authority. Its failure is caught by *other modules'*
enforcement, which is the honest demonstration: the baseline doesn't fail
because AdaptiveCore says so, it fails against state the rest of the system
enforces.

## Composition

| Need | Surface |
| --- | --- |
| Authority check / revocation | TrustCore `trust_profile` / `decide` / `revoke_credential` |
| Audit trail | TrustCore `record_event` → append-only `ReceiptLog` |
| Step gating | DecisionCore `decide` (purchase domain policy) |
| Budget effects | SimCore `place_hold` / ledger spend·refund / invariant check |
| Pre-commit preview | SimCore `simulate` (fork + diff) |

All through application surfaces only — import-linter contract
"AdaptiveCore reaches TrustCore/DecisionCore/SimCore only via
application+domain public surfaces" is kept.
