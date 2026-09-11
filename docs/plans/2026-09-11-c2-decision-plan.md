# Challenge 2 — The Decision Engine: Implementation Plan

Status: DRAFT — awaiting review. No code will be written until this plan is approved.

Inherits §0 engineering standards from [2026-09-11-c1-trust-plan.md](2026-09-11-c1-trust-plan.md) unchanged: hexagonal layers, fail-closed security, **no LLM on the decision path**, append-only receipts, ruff + import-linter enforced. Reuses the C8 pattern from [2026-09-11-c8-simulate-plan.md](2026-09-11-c8-simulate-plan.md): real state, one-click demo, deterministic safety nets, failure test as a first-class test file.

## 1. What this module is

**DecisionCore**: a deterministic decision layer that takes a *proposed action + context* in a registered domain and returns one of five outcomes — **execute · ask · defer · escalate · refuse** — with every number computed from real, named, weighted signals. It is not a prompt wrapper: no LLM exists anywhere in `core/decisioncore`, and the wiring is import-linter-enforced so it structurally cannot call one.

DecisionCore **composes the two modules that already exist** rather than re-implementing them:

- **TrustCore (C1)** supplies the *authority/identity evidence*: does the actor hold a valid Ed25519-signed `AuthorityGrant` whose scope covers this action? Verification is real signature + expiry + revocation + scope matching, fail-closed.
- **SimCore (C8)** supplies the *reversibility evidence*: does a compensating action exist for this action in the domain's compensation map (the C8 ledger pattern — rollback is an appended reversal, never an undo)?

Around these, the engine computes **confidence** and **risk** from five named signals, each with an explicit weight that is part of the domain policy (visible in the UI and stored in the receipt — a judge can read exactly why a number is what it is). A pure resolution function maps (confidence, risk, plus hard safety constraints) → one of the five outcomes. Every decision appends a **full audit receipt** to TrustCore's existing append-only log: inputs, per-signal scores and weights, evidence used, missing information, reversibility, resolution path, and outcome.

**Three example domains** are wired in with real synthetic data and domain-specific signals — not toy stubs (each domain gets its own actor, signed credentials, threshold, required context fields, and historical receipts):

1. **Refund approval** — TriageBot agent proposes refunding a customer; signals keyed on amount, invoice evidence, and a $500 auto-approve threshold.
2. **Code deploy** — DeployBot agent proposes deploying a service to production; signals keyed on tests-passing evidence, approvals count, and an irreversible-by-default compensation map (rollbacks are flagged costly/partial).
3. **Content moderation** — ModBot agent proposes removing flagged content; signals keyed on prior-violation history and report count, with a lower blast-radius threshold.

The engine's behavior emerges from the signals, per domain: a fully-authorized, cheap, reversible, well-evidenced refund **executes**; the same action with a missing invoice **asks** (and names the missing field); a forged or absent authority **refuses**; a high-cost irreversible deploy **escalates**; a credential-expired-but-renewable case **defers**.

## 2. Data model

All state lives in `core/decisioncore/` using the C1/C8 in-memory adapter pattern (clean-clone runnable). The only cross-module state read is TrustCore's credential/receipt stores and SimCore's compensation map — read-only, through public surfaces.

```
DomainPolicy (per-domain configuration, pure data)
  domain: string                       — "refund" | "deploy" | "moderation"
  required_evidence: list[str]         — context fields that MUST be present (e.g. ["invoice_id","amount"])
  optional_evidence: list[str]         — fields that raise confidence when present
  cost_threshold: float                — amount/blast-radius above which "wrong" is expensive
  weights: dict[signal_name -> float]  — per-signal confidence weights (sum documented)
  risk_weights: dict[signal_name -> float]
  compensation: dict[action -> Compensation]  — from SimCore's ledger pattern

Compensation (reversibility evidence, C8 pattern)
  exists: bool                         — is a compensating action defined?
  kind: string                         — e.g. "refund_reversal", "rollback_deploy", "restore_content"
  cost: enum("low","medium","high")    — cost of performing the reversal
  partial: bool                        — true when reversal cannot fully restore state (e.g. prod deploy)

ProposedAction (engine input)
  domain: string
  action: string                       — e.g. "issue_refund"
  actor_key: string                    — Ed25519 public key of the proposing agent
  amount: float | null                 — cost proxy (refund $, deploy blast radius $, moderation reach)
  context: dict[str, Any]              — the evidence payload (invoice_id, tests_passing, prior_violations, ...)

DecisionRecord (engine output — one per decide() call)
  id: string (uuid)
  ts: timestamp
  proposed: ProposedAction
  outcome: enum("execute","ask","defer","escalate","refuse")
  confidence: float (0..1)             — weighted sum of satisfied confidence signals
  risk: float (0..1)                   — weighted sum of risk signals
  signals: list[SignalScore]           — per-signal: name, value, weight, contribution, detail
  evidence_used: list[str]             — context fields present and consumed
  missing_information: list[str]       — required fields absent (or authority/history gaps)
  reversibility: Compensation          — the SimCore-sourced compensation verdict
  resolution_path: string              — which rule fired, e.g. "hard_block:no_authority"
  receipt_id: string                   — the TrustCore receipt this decision appended

SignalScore
  name: string                         — authority | reversibility | evidence | cost_of_wrong | history
  value: float (0..1)                  — normalized signal reading
  weight: float                        — from DomainPolicy
  contributes_to: enum("confidence","risk")
  detail: string                       — human-readable, e.g. "authority grant c41d… covers action"
```

**The five signals** (each named, weighted, and stored in the receipt):

1. **authority** (confidence + risk): TrustCore `decide()` verdict for actor+action. Valid signed grant covering the action → confidence up. Missing/forged/revoked → risk maxed *and* a hard block (refuse/escalate regardless of confidence).
2. **reversibility** (confidence + risk): SimCore compensation lookup. Compensating action exists and is cheap → confidence up. Irreversible or partial+high-cost → risk up.
3. **evidence** (confidence): fraction of `required_evidence` present in `context`, plus a bonus fraction for `optional_evidence`. Missing required fields are *named* in `missing_information`.
4. **cost_of_wrong** (risk): `amount` vs `cost_threshold`, normalized (≤threshold → low, 2×threshold → high). Domain-specific: refund dollars, deploy blast-radius, moderation reach.
5. **history** (confidence): outcome rate of past TrustCore receipts for this actor+action (allows / total, from the append-only log). No history → neutral-low, which itself can force `ask`.

**Resolution function** (pure, ordered rules — the first matching rule wins, and the winning rule is recorded in `resolution_path`):

```
1. authority invalid/forged AND action is privileged → REFUSE      (hard block, fail-closed)
2. authority missing/uncertain (e.g. zero valid grants, no record) → ESCALATE
3. confidence < domain floor (missing required evidence)          → ASK  (names missing info)
4. risk high AND NOT reversible                                    → ESCALATE
5. risk high AND reversible AND evidence incomplete                → DEFER (retry when evidence arrives)
6. risk low/medium AND confidence ≥ domain execute bar             → EXECUTE
7. otherwise                                                       → ASK (default: gather, don't guess)
```

`confidence` and `risk` are computed *before* resolution and shown for every outcome — even a refuse shows its numbers. Determinism is asserted in tests: same inputs → same scores → same outcome, `llm_called=false` on every receipt.

## 3. Architecture snapshot

This doubles as the required deliverable ("inputs → signals → decision → audit").

```
 Judge / UI                ┌──────────────────────── DecisionCore ────────────────────────┐
    │  proposed action     │                                                              │
    ▼  + context           │  ┌─────────────┐   authority evidence (signed grant valid?)  │
 POST /api/decision/ ─────────▶│  AUTHORITY  │◀────────────── TrustCore.decide() (C1,      │
 decide                       │  │  signal     │                unchanged, read-only)       │
                              │  └─────────────┘                                             │
                              │  ┌─────────────┐   compensating action? (C8 ledger pattern) │
                              │  │REVERSIBILITY│◀────────────── SimCore compensation map    │
                              │  │  signal     │                                             │
                              │  └─────────────┘                                             │
                              │  ┌─────────────┐   required vs present context fields       │
                              │  │  EVIDENCE   │──▶ missing_information[]                    │
                              │  └─────────────┘                                             │
                              │  ┌─────────────┐   amount vs domain cost threshold          │
                              │  │COST-OF-WRONG│                                             │
                              │  └─────────────┘                                             │
                              │  ┌─────────────┐   past receipts for actor+action           │
                              │  │  HISTORY    │◀────────────── TrustCore receipt log       │
                              │  └─────────────┘                                             │
                              │         ▼  weighted sums (pure)                              │
                              │  ┌─────────────────────┐                                     │
                              │  │ confidence / risk   │                                     │
                              │  └─────────┬───────────┘                                     │
                              │            ▼  ordered resolution rules (pure)                │
                              │  ┌─────────────────────┐                                     │
                              │  │ execute·ask·defer·  │──▶ DecisionRecord + resolution_path │
                              │  │ escalate·refuse     │                                     │
                              │  └─────────┬───────────┘                                     │
                              │            ▼  append-only audit                              │
                              │  ┌─────────────────────┐                                     │
                              │  │ TrustCore receipt   │  inputs+signals+reasoning+outcome   │
                              │  │ log (C1, reused)    │                                     │
                              │  └─────────────────────┘                                     │
                              └──────────────────────────────────────────────────────────────┘
                                            ▲
                 one FastAPI app: /api/decision/* alongside /api/trust/* and /api/sim/*
```

Key properties:

- **No LLM anywhere in the module.** Every score is arithmetic over verified facts; `llm_called=false` is asserted in tests for all five outcomes. This is the anti-"prompt wrapper" structural guarantee, backed by the import-linter contract.
- **Composition, not duplication.** DecisionCore imports TrustCore only through `TrustService` (application surface) and SimCore only through its domain compensation pattern — never adapters, never `api/`.
- **Every decision is receipted.** The audit trail is C1's existing append-only log; a decision receipt carries the full signal vector, so the trail is independently replayable.
- **Missing information is first-class.** `ask` and `defer` outcomes always ship a non-empty `missing_information` list — the engine says *what it needs*, not just "no".

## 4. The 90-second demo, beat by beat

Live on the deployed URL, one-click seeded via `POST /api/decision/demo` (same pattern as C1's `/api/trust/demo` and C8's `/api/sim/demo`), then driven from the new **C2 · Decision Engine** tab:

- **0:00–0:10** — Screen: decision console. Narration: "Three agents propose actions in three domains. The engine decides whether each is allowed to act — from signals, not vibes."
- **0:10–0:25** — Domain: **refund**. TriageBot proposes a $120 refund with `invoice_id` + `reason` present. Click **Decide**. Outcome: **EXECUTE**, confidence 0.91, risk 0.18. The signal panel shows all five bars; evidence_used lists the invoice; reversibility shows "compensating action: refund_reversal (low cost)". A receipt appears in the audit feed.
- **0:25–0:40** — Same domain, **$2,400 refund, missing `invoice_id`**. Click **Decide**. Outcome: **ASK**, confidence 0.44 — the missing-information box names `invoice_id`, risk is up (over the $500 threshold), and the resolution path reads `hard_floor:missing_required_evidence`. "It doesn't guess — it asks, and tells you what for."
- **0:40–0:55** — Domain: **deploy**. DeployBot proposes a production deploy with tests passing but blast radius above threshold and only partial rollback. Outcome: **ESCALATE** — irreversible + high-cost. The reversibility bar shows "partial, high cost"; resolution path: `risk_high_not_reversible`.
- **0:55–1:15** — **The failure test** (§5): an action with full authority + high confidence that is irreversible AND over the cost threshold AND missing a critical evidence field. Click **Decide** → the engine must NOT execute; it **asks/escalates and names the missing information**. Then **SpooferBot** proposes the same action with a forged grant → **REFUSE**, resolution path `hard_block:no_authority`.
- **1:15–1:30** — Zoom out on the audit feed: every decision a receipt with its full signal vector, `llm_called: false` on all. Close on the thesis: "In two years, every agent action passes through a decision layer that can say no — and say why."

## 5. The failure scenario

**Scenario: high confidence + full authority + irreversible + over-threshold + one critical evidence field missing → the engine must not execute.**

Concretely (deploy domain): DeployBot holds a *valid, unexpired, correctly-scoped* signed `AuthorityGrant` for `deploy_production` (authority signal: green). It has strong history (past receipts: 9/10 allows). The proposed deploy's blast radius is **$8,000** against a **$2,000** threshold (cost_of_wrong: maxed). The compensation map says production deploys are **partially reversible at high cost** (reversibility: red). And the context is **missing `change_ticket`** — a required evidence field linking the deploy to an approved change request.

A naive system executes: authority is valid, confidence from history + authority is high. DecisionCore does not:

1. **Authority**: valid → but this only clears the hard block; it does not force execute.
2. **Evidence**: `change_ticket` absent → named in `missing_information`; confidence drops below the domain floor.
3. **Cost of wrong**: $8,000 ≫ $2,000 → risk maxed.
4. **Reversibility**: partial + high-cost → risk stays maxed.
5. **Resolution**: rule 3 fires first — `confidence < floor (missing required evidence)` → **ASK**, with `missing_information: ["change_ticket"]`. If the evidence were present, rule 4 would fire instead — `risk high AND NOT reversible` → **ESCALATE**. Either way: **no execution path exists** for this input. The receipt records the full vector so the near-miss is auditable.

Honest "this breaks when…" notes (for the submission, and they earn points):

- **Threshold gaming**: an actor who learns the $2,000 threshold can split one $8,000 action into five $1,600 ones. Mitigation noted (rate/window aggregation in the history signal), not built — flagged in README.
- **Staleness**: the history signal reads the receipt log at decision time; a burst of concurrent proposals can interleave. The C8 TOCTOU failure test already demonstrates this class; DecisionCore inherits the limitation honestly.
- **Self-reported evidence**: `tests_passing: true` is a context field the actor supplies; the engine weights it but cannot verify it against a real CI system in this build (the port exists; the adapter is synthetic).

## 6. File/folder structure

Extends the existing tree; C1 and C8 modules are untouched (additive routes only, shared app factory).

```
builder-league/
├── core/
│   ├── trustcore/                      # C1 — untouched
│   ├── simcore/                        # C8 — untouched
│   └── decisioncore/                   # NEW — Module 2
│       ├── domain/
│       │   ├── policies.py             # DomainPolicy, Compensation, the 3 domain definitions (pure data)
│       │   ├── signals.py              # the 5 signal functions: pure, (facts → SignalScore)
│       │   └── resolve.py              # resolution rules: (confidence, risk, facts) → outcome (pure)
│       ├── application/
│       │   ├── ports.py                # DecisionStore, HistoryReader, AuthorityVerifier protocols
│       │   └── services.py             # DecisionService: decide() → DecisionRecord + receipt
│       └── adapters/
│           └── memory.py               # in-memory DecisionStore; history reader over TrustService
├── api/
│   └── main.py                         # + /api/decision/* router (additive only)
├── ui/
│   └── src/
│       ├── App.jsx                     # + third tab "C2 · Decision Engine"
│       └── decision/                   # DecisionConsole, SignalBars, OutcomeBadge, MissingInfo, AuditFeed
├── tests/
│   ├── test_signals.py                 # each signal: satisfied/unsatisfied/partial readings
│   ├── test_resolve.py                 # every resolution rule fires; determinism; llm_called=false
│   ├── test_decision_service.py        # decide() end-to-end per domain; receipt appended; missing-info named
│   ├── test_decision_api.py            # HTTP round trip; validation; unknown domain 422
│   └── test_decision_failure.py        # the §5 failure test + forged-authority refuse
├── demo/
│   └── script-c2.md                    # the 90s runbook, beat-timed
├── docs/
│   ├── plans/2026-09-11-c2-decision-plan.md   # this file
│   ├── architecture-c2.md              # the §3 diagram, expanded
│   └── thesis-c2.md                    # ≤300-word 2-year thesis on decision layers
└── GATES.md                            # extended with D-section ledger (unlazy)
```

Import-linter contracts extended: the same three contracts duplicated for `core.decisioncore` (domain purity, application↛adapters, layered), plus an **independence contract**: `core.decisioncore` may import `core.trustcore` and `core.simcore` only via their `application`/`domain` public surfaces — never their `adapters`, never `api`, never the UI. A **no-LLM contract**: `core.decisioncore` may not import any LLM/tracing module at all.

## 7. What I will NOT build (out of scope)

- **No LLM-as-judge anywhere** — not even for borderline cases. `ask`/`defer`/`escalate` exist precisely so the system never needs to guess; reasoning strings are deterministic templates over the signal vector. (C1 allows LLM only for receipt narration; C2 needs even less.)
- **No generic "any domain" framework** — three real domains, each with its own policy, signals, and synthetic data. Generality is claimed via the policy+signal pattern, not via half-built extra domains.
- **No persistent database** — same in-memory adapter pattern as C1/C8 (demo resets on redeploy; documented in README). Ports make SQLite/Postgres a drop-in later.
- **No real CI/payment/moderation integrations** — evidence fields are realistic synthetic data through the ports, flagged honestly in the failure notes.
- **No actor-side SDK** — agents are seeded demo identities calling the HTTP API, as in C1/C8.
- **No multi-tenant auth on the decision UI** — same demo-surface rationale as C1/C8.

## 8. Risk list: 3 ways this could trip a disqualifier

1. **Risk: "pure prompt wrapper with no system around it."**
   Avoidance: there is no prompt. `core/decisioncore` contains zero LLM calls, enforced by an import-linter contract (no LLM/tracing module importable) and asserted in tests (`llm_called=false` on every receipt across all five outcomes). Confidence and risk are weighted arithmetic over verified facts; the UI renders the per-signal math, so a judge can recompute any number by hand.
2. **Risk: the five outcomes look decorative — everything always executes.**
   Avoidance: the demo and `test_decision_service.py` exercise all five outcomes on real inputs — execute (clean refund), ask (missing invoice), defer (reversible-but-under-evidenced moderation action), escalate (irreversible over-threshold deploy), refuse (forged authority). The resolution function is a pure ordered-rule table with a dedicated test per rule, and `resolution_path` records which rule fired.
3. **Risk: the failure test looks staged — the safety behavior never really fires.**
   Avoidance: `test_decision_failure.py` builds the §5 scenario from real primitives (a genuine signed grant, real receipt history, the real compensation map) and asserts the engine *refuses to execute* for two distinct reasons (missing evidence → ask; present evidence but irreversible+over-threshold → escalate), with the missing field named and the full signal vector receipted. The forged-authority refuse goes through real signature verification, not a flag.

---

*Review this plan. On approval I will extend GATES.md with the C2 (D-prefix) ledger, implement TDD red-green (decisioncore domain → signals → resolve → service → API → UI console → failure test), keep ruff + import-linter green with the extended contracts, add the one-click demo button, push to master for Render auto-deploy, verify live, and report against the ledger.*
