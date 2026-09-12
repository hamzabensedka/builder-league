# Builder League — TrustCore + DecisionCore + SimCore + AdaptiveCore + TowerCore + MemoryCore + AmbientCore (C1 · C2 · C3 · C4 · C5 · C7 · C8)

One modular monolith for the DOO Builders League. Seven challenges live here:

- **C1 TrustCore** — a trust layer for AI agents: W3C-VC-shaped **verifiable
  credentials** (Ed25519), a deterministic **policy engine** (no LLM on the
  enforcement path), and an **append-only decision receipt** per gated action.
- **C2 DecisionCore** — a **decision layer** that takes a proposed action +
  context and returns **execute · ask · defer · escalate · refuse**, with
  confidence, risk, evidence used, missing information, and reversibility all
  computed from five **named, weighted signals**. It composes TrustCore
  (authority evidence) and SimCore (reversibility) and receipts every decision
  to the shared append-only log. **No LLM anywhere** — enforced by an
  import-linter contract. See
  [`docs/architecture-c2.md`](docs/architecture-c2.md) ·
  [`docs/thesis-c2.md`](docs/thesis-c2.md) ·
  [`demo/script-c2.md`](demo/script-c2.md).
- **C8 SimCore** — a **simulation gate** in front of a real write: fork the
  live state, run the *same* pipeline on the fork, and show the human a
  **computed before/after diff** (not a confirm dialog) with the **rollback
  path** pre-computed. Post-execution invariant checks catch wrong predictions
  and offer a real compensating rollback. See
  [`docs/architecture-c8.md`](docs/architecture-c8.md) ·
  [`docs/thesis-c8.md`](docs/thesis-c8.md) ·
  [`demo/script-c8.md`](demo/script-c8.md).
- **C3 AdaptiveCore** — an **adaptive agent**: a plan → execute → observe →
  re-evaluate loop with persisted state. Every step declares typed
  **assumptions**; world changes arrive as **events with real side effects**;
  a contradiction (and only a contradiction) fires a deterministic re-plan,
  receipted with an **"I changed my mind because…"** trace and a structural
  plan diff. **Damping** (hysteresis, revision budget, A→B→A oscillation
  detection) contains runaway adaptation; a **non-adaptive baseline** runs the
  same world blind and fails against real enforced state. No LLM anywhere on
  the   detection/re-planning path. See
  [`docs/architecture-c3.md`](docs/architecture-c3.md) ·
  [`docs/thesis-c3.md`](docs/thesis-c3.md) ·
  [`demo/script-c3.md`](demo/script-c3.md).
- **C5 TowerCore** — the **agent control tower**: an SRE layer over the fleet.
  One append-only **event stream** is the spine; fleet state, per-agent cost,
  drift flags, and the audit export are all folds over it. An
  **InterventionGate** enforces pause/kill on the execution path (kill is
  terminal), risky actions park in an **approval queue**, and deterministic
  **drift rules** (denial/escalation bursts, cost runaway, oscillation)
  auto-pause a rogue agent. Telemetry pushes over SSE; interventions are
  receipted REST calls. The **rogue-agent failure test** injects a corrupted
  objective into DeployBot and walks injection → refusals → drift flag →
  auto-pause → operator replay → kill, all in one exportable audit trail. No
  LLM anywhere on the control path. See
  [`docs/architecture-c5.md`](docs/architecture-c5.md) ·
  [`docs/thesis-c5.md`](docs/thesis-c5.md) ·
  [`demo/script-c5.md`](demo/script-c5.md).
- **C4 MemoryCore** — a memory layer that **knows it might be wrong**. Every
  fact is tagged with **source** (user_stated > observed > inferred >
  imported), **confidence** (source trust × extraction quality, boosted by
  corroboration), **freshness** (half-life decay + optional TTL), and
  **scope** (user / agent / task — retrieval is gated, task facts never
  leak). Retrieval returns a **reliance receipt** — what it's relying on, a
  calibrated confidence, and named gaps — and below the acting threshold the
  verdict is **"I might be wrong about this"**. Forgetting is explicit and
  receipted: stale facts are swept, same-slot contradictions trust *neither*
  side at equal strength, and **signed revocations** (Ed25519, fail-closed)
  cascade to derived facts. All of it lands in the shared append-only
  receipt log; no LLM, no embeddings. See
  [`docs/architecture-c4.md`](docs/architecture-c4.md) ·
  [`docs/thesis-c4.md`](docs/thesis-c4.md) ·
  [`demo/script-c4.md`](demo/script-c4.md).
- **C7 AmbientCore** — **beyond the chatbot**: an ambient canvas for the ops
  operator on shift. Nothing renders by default — no KPI wall, no feed, no
  prompt box. A deterministic **intent fold** over the TowerCore event stream
  infers what you need to decide next and surfaces at most **one decision
  card**: evidence chain attached, the risky action **pre-simulated** through
  SimCore with a rollback preview, initiated by the interface itself. Wrong
  guess? Reject it: a receipted MemoryCore correction **demotes** that intent
  kind on the retry, and a second rejection degrades gracefully to raw
  evidence. The dogfood contrast is live: the **"⇄ What this replaces"**
  toggle shows the SAME fleet as the C5 dashboard vs the ambient canvas.
  Narration is propose-only LLM with scripted fallback; inference and
  enforcement are model-free. See
  [`docs/architecture-c7.md`](docs/architecture-c7.md) ·
  [`docs/thesis-c7.md`](docs/thesis-c7.md) ·
  [`demo/script-c7.md`](demo/script-c7.md).

**Live demo:** https://builder-league-trust.onrender.com — the inspector UI is
served at `/`; API under `/api/trust/*` (free tier: first request after idle
takes ~30–60s to wake; `/health` answers `{"status":"ok"}`).
Run the demo against it:
`PYTHONPATH=. .venv/Scripts/python demo/run_demo.py --base https://builder-league-trust.onrender.com`
**Architecture:** [`docs/architecture.md`](docs/architecture.md)
**Two-year thesis:** [`docs/thesis.md`](docs/thesis.md)

## Run from a clean clone

Requires Python ≥ 3.11 and Node ≥ 20. No external services needed (SQLite-free
in-memory by default; Langfuse/Redis are opt-in via env flags and not required).

```bash
# 1. backend deps
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"        # Windows
# source .venv/bin/activate && pip install -e ".[dev]"   # macOS/Linux

# 2. run the API (serves /api/trust/*)
PYTHONPATH=. .venv/Scripts/python -m uvicorn api.main:create_app --factory --port 8000

# 3. in another terminal: run the 90-second demo scenario against it
PYTHONPATH=. .venv/Scripts/python demo/run_demo.py --base http://localhost:8000

# 4. inspector UI (optional, dev server proxies /api to :8000)
cd ui && npm install && npm run dev          # http://localhost:5173
```

## The 90-second demo (what a judge sees)

`demo/run_demo.py` drives three independent agents (BuyerBot, VendorBot,
SpooferBot — separate keypairs, separate HTTP clients) through:

1. **Accept** — BuyerBot's $800 purchase is allowed: valid `AuthorityGrant`
   (≤ $1000, signed by Acme) + two signed `TaskCompletion` vouches.
2. **Credential issued** — VendorBot signs a new `TaskCompletion`; BuyerBot's
   history grows 2 → 3 live.
3. **Forgery refused** — SpooferBot presents an `AuthorityGrant` claiming Acme
   as issuer but signed with its own key → `invalid_signature`, HTTP 400.
4. **No-authority refusal** — SpooferBot tries the purchase anyway → REFUSE.
5. **Scope escape refused** — SpooferBot earns a *real* ≤ $50 grant, attempts
   $800 → REFUSE.
6. **Revocation refused** — Acme revokes BuyerBot's authority (issuer
   re-signed); BuyerBot retries → REFUSE, receipt reads `revoked`.

Every beat appends a machine-readable receipt (`GET /api/trust/receipts`),
each with `llm_called: false` — enforcement is crypto + policy only.

## Design decisions

- **No aggregate reputation score** (challenge disqualifier). Every surfaced
  count is a filter over individually verifiable signed claims; the UI renders
  only claim-level rows with verify checkmarks.
- **Hexagonal architecture**: `core/trustcore/domain` (pure: crypto,
  credentials, policy — zero I/O) → `application` (use-case services, ports as
  Protocols) → `adapters` (in-memory now, SQLite/Postgres later; FastAPI in
  `api/`). Enforced by `import-linter` contracts (`lint-imports`).
- **Fail-closed**: any malformed key/signature/input → refuse or 4xx, never
  an exception leaking to a decision. Verified by tests.
- **Key custody**: the server never holds private keys. Issuers sign
  credentials client-side; mutating endpoints verify a request signature.
  Revocations are issuer *re-signed* so a revoked credential stays verifiable.
- **TDD throughout**: 38 tests, each written before its implementation.

## Security notes

- Ed25519 via PyNaCl only; canonical JSON (sorted keys, UTF-8, no whitespace)
  before every sign/verify so identical payloads sign identically.
- Pydantic validation at every API boundary; parameterized/domain-only data
  access (no string-built SQL anywhere; no `eval`/`exec`).
- Private keys live in `.env`/local key files (git-ignored). This is
  **demo-grade custody** — production would use an external signer/HSM.
  Flagged in `docs/plans/2026-09-11-c1-trust-plan.md` §7.

## Out of scope (honest limits)

- No DID method resolution, no blockchain anchoring (VC-*shaped*, not full SSI).
- No cross-organization federation; single deployment, local key registry.
- No multi-tenant auth on the inspector UI (a demo surface, not enforcement).
- Langfuse/Redis are opt-in behind env flags, off by default for clean clones.

## AI usage

Built with an AI pair-programmer (Cursor). All architecture, security rules,
and the plan were reviewed and approved by the human submitter before code;
AI wrote implementation against failing tests (TDD) under gates
(`GATES.md` ledger, verified by `gate-check.mjs`).

## Tests

```bash
.venv/Scripts/python -m pytest        # full suite (C1 + C2 + C3 + C8)
.venv/Scripts/python -m ruff check .  # lint
.venv/Scripts/lint-imports            # architecture contracts (16 kept)
```

## C3 quick drive (The Adaptive Agent)

Open the UI → **C3 · Adaptive Agent** tab:

1. **Start adaptive + baseline** (scenario A) — seeds RestockBot with signed
   $1,000 purchase authority, runs the same world twice side by side.
2. **Advance steps**, then **⚡ inject the price spike** mid-run: the
   contradiction fires on the executed verify step (cascade), the revision
   card shows expected-vs-observed + plan diff + gate verdict + SimCore
   preview, and the run completes via SouthSupply ($780).
3. **Run the baseline blind** — same spike, no detection; it collides with
   the enforced budget invariant.
4. **Failure test** — scenario C (flapping price): the agent flip-flops
   suppliers twice, then A→B→A oscillation detection escalates to a human,
   receipted; further flaps change nothing.

API: `POST /api/adaptive/demo`, `GET /api/adaptive/scenarios`,
`POST /api/adaptive/runs`, `POST /api/adaptive/runs/{id}/events`,
`POST /api/adaptive/runs/{id}/advance`, `GET /api/adaptive/runs/{id}`.

### Honest limits ("this breaks when…")

- **Two-run demos share one budget**: running both columns to completion
  without a compensating refund leaves the second run with less headroom
  (the world is real, not per-run sandboxed). The UI walks one column at a
  time for this reason.
- **In-memory stores**: runs, revisions, and events reset on redeploy —
  swap adapters for SQLite to persist across restarts; the ports already
  isolate that change.

## C5 quick drive (The Agent Control Tower)

Open the UI → **C5 · Control Tower** tab:

1. **Enroll the fleet** — three agents register with real signed authority and
   start streaming events (live via SSE, polling fallback).
2. **Step RestockBot** — check stock → size order → a real purchase, simulated
   before write on the SimCore ledger and gated by TrustCore authority.
3. **Step DeployBot** — release v12 has no change ticket → DecisionCore
   escalates → the deploy **parks in the approval queue**. Approve or deny it.
4. **Replay** any agent — the last N steps as a readable trace, seq-aligned to
   the audit export.
5. **Failure test** — **Inject rogue objective**: DeployBot's objective is
   corrupted mid-run. Deny its over-authority demands; the escalation-burst
   detector flags drift and **auto-pauses** the agent. Replay the reasoning,
   then **Kill** (terminal). **Export audit** for the full incident trail.

API: `POST /api/tower/demo`, `GET /api/tower/fleet`, `GET /api/tower/stream`
(SSE), `GET /api/tower/approvals`, `POST /api/tower/approvals/{id}/approve|deny`,
`POST /api/tower/agents/{id}/advance|pause|resume|kill`,
`GET /api/tower/agents/{id}/replay?n=20`, `POST /api/tower/scenario/rogue`,
`GET /api/tower/audit`.

### Honest limits ("this breaks when…")

- **In-memory event store**: the stream resets on redeploy — swap the adapter
  for a durable log to persist across restarts; the ports already isolate that.
- **Metered costs**: token/cost numbers are deterministic per-action estimates
  labeled `metered_estimate`, not real provider billing.
- **Single operator, no auth**: the cockpit is a demo surface, not an
  enforcement boundary — enforcement lives in the gate and the cores.
- **SSE on free-tier hosting**: first connection after idle waits on cold start;
  the UI falls back to polling `/api/tower/fleet` if the stream drops.

## C4 quick drive (Memory That Knows It Might Be Wrong)

Open the UI → **C4 · Memory** tab:

1. **Run the demo** — Maya learns three differently-tagged facts: "prefers
   window seat" (user-stated, 95%), "lives in Lisbon" (inferred once, 40%),
   "flies TAP" (CRM import, 30-day TTL).
2. **2 · Plan a trip** — the *"I might be wrong"* moment: seat recall is
   Confident; city recall is **unsure** (40% < 55% threshold), gaps named.
3. **3 · User corrects** — "moved to Porto" supersedes the weak inference;
   Lisbon is tombstoned with reason `superseded`, recall is now Confident.
4. **4 · Time passes** — 45 simulated days; the sweeper kills the TTL-expired
   import explicitly and the airline recall goes blank.
5. **5 · Sign "forget my location"** — a real Ed25519-signed revocation
   tombstones the city fact (cascading to derived facts); the inspector shows
   the tombstone, recall no longer surfaces it.

API: `POST /api/memory/demo` (+ `/demo/unsure|correct|age|revoke` beats),
`POST /api/memory/learn|recall|forget|sweep`, `GET /api/memory/inspect`,
`GET /api/memory/events`.

### Honest limits ("this breaks when…")

- **Keyword/slot retrieval, no embeddings**: a query with zero lexical overlap
  ("where do I live" vs slot `user.city`) won't match. Deliberate: the
  confidence/forgetting model is the graded substance, and lexical matching
  keeps relevance fully inspectable. Semantic matching would slot in behind
  the same `recall` port.
- **In-memory stores**: facts and tombstones reset on redeploy — swap the
  adapters for SQLite to persist; the ports isolate that change.
- **Demo key custody**: the demo's user keypair is held server-side only so
  the revocation beat can be one click; it is never returned by any endpoint.
  Production revocation would be signed client-side like TrustCore issuers.

## C2 quick drive (The Decision Engine)

Open the UI → **C2 · Decision Engine** tab:

1. **Seed the demo** — three agents with real signed authority + history.
2. **Refund domain** — "Clean $120 refund" → **EXECUTE** (confidence/risk bars
   + the five weighted signals rendered). Then "$2400 refund, missing
   invoice_id" → **ASK**, naming the missing field.
3. **Deploy domain** — "$8000 deploy, fully evidenced" → **ESCALATE**
   (irreversible + over threshold). Then the **failure test**: "$8000 deploy,
   missing change_ticket" — full authority + strong history, but the engine
   **never executes**; it asks/escalates and names `change_ticket`.

API: `POST /api/decision/demo`, `GET /api/decision/domains`,
`POST /api/decision/decide`, `GET /api/decision/decisions`,
`GET /api/decision/{id}`.

### Honest limits ("this breaks when…")

- **Threshold gaming**: an actor who learns a domain's cost threshold can
  split one large action into several under-threshold ones. Mitigation
  (rate/window aggregation in the history signal) is noted, not built.
- **Self-reported evidence**: context fields like `tests_passing: true` are
  supplied by the actor and weighted, but not verified against a real CI
  system in this build — the port exists; the adapter is synthetic.
- **TOCTOU staleness**: the history signal reads the receipt log at decision
  time; a burst of concurrent proposals can interleave. C8's failure test
  demonstrates this class on the shared budget.

## C8 quick drive (Simulate Before You Act)

Open the UI → **C8 · Simulate first** tab:

1. **Seed the demo** — funds BuyerBot with signed $1,000 authority + history.
2. **Simulate $900 purchase** — the approval screen is the before/after diff.
3. **Approve & execute** — real `/api/trust/decide` + ledger write.
4. **Failure test** — simulate again, **inject a concurrent $200 hold** before
   approving, then approve → post-check catches `900+200 > 1000` → escalated,
   **rollback** offered and executed as a compensating refund.

API: `POST /api/sim/demo`, `POST /api/sim/simulate`, `GET /api/sim/{id}`,
`POST /api/sim/{id}/execute|reject|rollback`, `POST /api/sim/hold`,
`GET /api/sim/ledger/state`.

## C7 quick drive (Beyond the Chatbot)

Open the UI → **C7 · Canvas** tab:

1. **Start the shift** — the canvas binds to the live fleet. Nothing renders:
   no dashboard, no prompt box. The ambient line reads *"Fleet steady."*
2. **Step RestockBot** — a low-stock signal folds in but stays below
   threshold: see it in *"Inferred, but deliberately not shown."*
3. **Step DeployBot ×3** — v12 has no change ticket → DecisionCore escalates
   → the action parks → **the interface initiates the decision card itself**:
   evidence chain, pre-simulated before/after diff, rollback preview.
   **Approve & execute** — the real tower approval resolves.
4. **Failure test** — step DeployBot to the next review card, **reject** it
   ("Not the right call"): a receipted correction lands in MemoryCore. Resume
   + step again: the same card kind returns **visibly demoted** (confidence
   halved, correction cited). Reject twice and the canvas stops guessing —
   manual mode hands over the raw events.
5. **⇄ What this replaces** — one click to the C5 Tower tab: the SAME fleet
   as a monitoring dashboard. That contrast is the thesis.

API: `POST /api/ambient/demo`, `GET /api/ambient/canvas`,
`GET /api/ambient/intents`, `GET /api/ambient/cards`,
`POST /api/ambient/cards/{id}/approve|edit|reject`.

### Honest limits ("this breaks when…")

- **The fold is rule-based, not learned**: intent kinds and weights are named
  constants. Deliberate — the graded substance is that inference is real
  (folded from event shapes, demoted by corrections), inspectable, and
  model-free. A learned ranker would slot in behind the same `fold → rank`
  seam.
- **One fleet, one operator**: no multi-tenant auth on the canvas (a demo
  surface); enforcement lives in the cores, not the UI.
- **In-memory card store**: card history resets on redeploy — swap the
  adapter for a durable store; the port isolates that change.
- **Narrator is OpenRouter free-tier**; with no `OPENROUTER_API_KEY` (or on
  any error) the rationale falls back to scripted lines and the card labels
  which brain answered. Clean clones run fully offline.

## C6 quick drive (The Autonomous Company Simulator)

Open the UI → **C6 · Company** tab:

1. **Seed Northwind Components** — four roles (Sales, Ops, Finance, and an
   LLM **ChiefOfStaff**) enroll with signed, scoped authority; opening books
   land: $50k cash, 200 units, 2 invoices, 1 bill.
2. **Run a day** — the company operates: leads arrive, SalesBot quotes and
   wins (invoice issued), OpsBot restocks, FinanceBot collects and pays.
   Revenue, cash, runway, backlog, and churn all move. Borderline actions park
   in the **human inbox** — answer one inline (the human-in-the-loop moment).
3. **⚡ Cash crunch** — a churn + early-bill shock drops runway; the company
   **self-corrects with zero human input**: Finance freezes spend, Ops defers
   the restock, Sales pushes collections, the ChiefOfStaff ratifies.
4. **☠ Rogue sales** (failure test) — SalesBot over-discounts past its signed
   scope → TrustCore refuses → refusal streak → `role_paused`; Ops/Finance
   hold the line. Replay the reasoning on the timeline.
5. **Replay scrubber** — drag to any earlier day; the whole board re-folds
   from the event log.

API: `POST /api/company/demo`, `POST /api/company/advance`,
`GET /api/company/state`, `GET /api/company/kpis`, `GET /api/company/inbox`,
`POST /api/company/inbox/{id}/resolve`, `GET /api/company/replay?day=N`,
`GET /api/company/events`, `POST /api/company/scenario/cash-crunch`,
`POST /api/company/scenario/rogue-sales`.

### Honest limits ("this breaks when…")

- **In-memory spine**: the company event log resets on redeploy — swap the
  adapter for a durable log to persist; the ports isolate that change.
- **Sales/Ops/Finance are deterministic policies**, not LLMs — stated plainly;
  the LLM is the ChiefOfStaff (the cross-functional judgment role), and it is
  **propose-only**: its output is parsed by deterministic domain code before
  any state change, so it can never act outside the envelope.
- **OpenRouter free tier is rate-limited**; with no `OPENROUTER_API_KEY` (or on
  any error) the ChiefOfStaff falls back to a scripted policy and the UI labels
  which brain answered. Clean clones run fully offline.
- **Single operator, no auth** on the inbox (demo surface, not enforcement) —
  enforcement lives in TrustCore/DecisionCore, not the UI.

