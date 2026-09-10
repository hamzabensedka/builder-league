# Challenge 1 — The Agent That Earns Trust: Implementation Plan

Status: DRAFT — awaiting review. No code will be written until this plan is approved.

## 0. Engineering standards (binding for this and all later challenges)

**Architecture: modular monolith + hexagonal (ports & adapters) layering.** One repo, one deployment, per-challenge routes — but the *domain logic (logique métier) is framework-free and lives in pure modules*; FastAPI, SQLAlchemy, Langfuse, Redis, and the React UI are adapters at the edges. Layers and allowed dependency directions:

```
adapters/ (FastAPI routes, UI, Langfuse, Redis, SQLAlchemy repos)
        │   depend on ▼  — never the reverse
application/ (use-case services: IssueCredential, DecideTask, RevokeAuthority)
        │   depend on ▼
domain/ (pure: Credential, PolicyDecision, VerificationResult — no I/O, no framework imports)
```

Concrete rules enforced in code review and by lint (ruff + import-linter contract):

1. **Domain purity**: nothing in `domain/` imports fastapi/sqlalchemy/redis/requests; it performs zero I/O. Verification and policy evaluation are pure functions — fully unit-testable without a database.
2. **Dependency inversion**: adapters implement repository/signer/tracer protocols (Python `Protocol` classes) defined in `application/`; services receive them via constructor injection. Swapping SQLite→Postgres or adding Langfuse touches adapters only.
3. **Security practices** (non-negotiable):
   - Ed25519 via PyNaCl only — no hand-rolled crypto; canonical JSON (RFC 8785-style: sorted keys, UTF-8, no whitespace) before every sign/verify.
   - All API inputs validated with Pydantic models at the adapter boundary; domain objects are constructed only from validated DTOs.
   - Parameterized queries only (SQLAlchemy, never string-built SQL); no `eval`/`exec` anywhere; Cedar policy files are data, never executable code paths.
   - Private keys never leave `.env`/local key files, are git-ignored, and never appear in receipts, logs, or API responses — receipts contain public keys and signature booleans only.
   - Every mutating endpoint requires a valid issuer signature over the request body (issue/revoke are themselves credential-gated operations).
   - Fail-closed: any verification exception → refuse, with the exception logged to receipts, never swallowed.
4. **Separation of concerns**: one file, one responsibility (crypto ≠ credentials ≠ policy ≠ receipts ≠ API); target <200 lines/module; no file imports across challenge modules except through `core/`.
5. **Auditability**: every state change emits a DecisionReceipt; the receipt log is append-only (no UPDATE/DELETE paths exist in code).
6. **Testing as spec**: `tests/` mirrors the domain — tamper, replay, expiry, revocation, and scope-escape each have a dedicated test; CI-green is required before demo work begins.

These standards apply to C1 now and are inherited by C2–C8 unchanged.

## 1. What this module is

**TrustCore**: the credential + verification + policy foundation of the shared core (Module 1). It is a standalone service + importable library (not UI-coupled) that issues, verifies, and revokes **verifiable credentials** (W3C-VC-shaped, Ed25519-signed), and gates actions through a Cedar policy engine. Every agent gets a trust profile assembled from signed claims — a completed-task history (task-based claims), scoped authority delegations (authority-based claims), and capability attestations (capability-based claims) — because the challenge demands a trust profile with "history, scope of authority, vouches/attestations," and omitting any of the three would leave the profile incoherent. Crucially: there is **no aggregate score anywhere** — every surfaced number is a count or filter over specific, individually verifiable signed claims. Challenge 2 (Decision Engine) imports the Cedar engine and credential verifier unchanged; Challenges 3–8 consume the same primitives.

## 2. Data model

Minimal but real. All entities stored in SQLite (repo runs from a clean clone with zero external services; Redis/Langfuse are optional, wired via env flags).

```
Agent
  id: string (uuid)
  name: string
  public_key: string (Ed25519, base64) — the agent's identity
  owner: string (human or org name)
  created_at: timestamp

Credential (W3C-VC-shaped signed claim)
  id: string
  issuer_key: string (Ed25519 public key of issuer)
  subject_agent_id: string -> Agent.id
  type: enum("TaskCompletion", "AuthorityGrant", "CapabilityAttestation", "Vouch")
  claim: jsonb            — e.g. {action:"purchase", max_amount:1000, currency:"USD"}
  scope: jsonb            — e.g. {domains:["acme.com"], actions:["purchase","refund"]}
  issued_at, expires_at: timestamp
  revoked_at: timestamp | null
  revocation_reason: string | null
  signature: string (Ed25519 over canonical JSON of all fields above)

Task / TaskRequest
  id: string
  requester_agent_id: string -> Agent.id   (the counterparty)
  executor_agent_id: string -> Agent.id
  description: string
  required_capability: string | null       — e.g. "procurement"
  action: string                           — e.g. "purchase"
  amount: numeric | null
  status: enum("proposed","accepted","refused","completed","failed")
  decision_receipt_id: string -> DecisionReceipt.id

DecisionReceipt (audit primitive, reused by all later challenges)
  id: string
  ts: timestamp
  agent_id: string
  action: string
  inputs: jsonb        — task, counterparty id, credentials checked
  signals: jsonb       — which claims matched, expiry/revocation status
  policy_decision: enum("allow","refuse","escalate")
  reasoning: string    — human-readable, one or two sentences (LLM only here)
  llm_called: boolean  — must be false for obvious allow/refuse
  tokens: int, cost_usd: numeric (0 when llm_called=false)
```

Relationships: `Agent 1—N Credential` (as subject), `Agent 1—N Credential` (as issuer, via key), `Task 1—1 DecisionReceipt`, `Agent 1—N Task` on both sides.

## 3. Architecture snapshot

This doubles as the required deliverable ("identity → claims → verification → policy").

```
                          ┌─────────────────────────── TrustCore ───────────────────────────┐
                          │                                                                 │
  Human owner ──signs──▶  Identity Registry (Ed25519 keys per agent)                        │
                          │         │                                                       │
                          │         ▼                                                       │
  Issuer agents ──sign──▶ Claim Store (VC-shaped credentials, expiry + revocation lists)    │
                          │         │                                                       │
                          │         ▼                                                       │
  Counterparty request ─▶ Verifier (signature, expiry, revocation, scope match)             │
                          │         │                                                       │
                          │         ▼                                                       │
                          │   Cedar Policy Engine ──▶ allow / refuse / escalate             │
                          │         │              (pure function: action + claims →        │
                          │         ▼               decision; NO LLM on this path)          │
                          │   Decision Receipts (JSON, append-only, per decision)           │
                          │         │                                                       │
                          │         ▼                                                       │
                          │   Langfuse tracer (opt-in; records receipts + any LLM calls)    │
                          └─────────────────────────────────────────────────────────────────┘
                                          ▲
              ┌───────────────────────────┼───────────────────────────┐
              │                           │                           │
     Agent A (buyer, python proc)   Agent B (vendor, python proc)   React UI (read-only inspector
              │                           │                          + issue/revoke console)
              └─────── both call TrustCore HTTP API (verify / decide / issue / revoke) ───────┘
```

Key properties:
- The **LLM is never on the enforcement path**. Cedar returns allow/refuse; the LLM is called only (a) for borderline `escalate` cases to draft reasoning, and (b) to render receipt explanations. Hard rule 2 honored.
- Verification is pure crypto + policy: `nacl.sign.verify` + Cedar evaluation. Deterministic, cheap, replayable.

## 4. The 90-second demo, beat by beat

Live demo URL (deployed on Render free tier; fallback: recorded walkthrough). Two independent agent processes + the inspector UI open side by side.

- **0:00–0:10** — Screen: TrustCore inspector showing Agent A (BuyerBot, owned by "Acme") and Agent B (VendorBot). Narration: "Two independent agents. VendorBot is about to be asked to sell."
- **0:10–0:25** — BuyerBot sends VendorBot a task: "Purchase 100 units @ $8 each from vendor X." VendorBot calls TrustCore `/decide` with BuyerBot's key. UI flashes the live decision receipt: **ACCEPTED** — because BuyerBot holds (1) an `AuthorityGrant{purchase, ≤$1000}` signed by Acme's key, (2) two `TaskCompletion` credentials signed by prior counterparties, (3) nothing expired, nothing revoked. Each cited credential is clickable → shows raw signed JSON + verify checkmark. "Every number traces to a signed claim — no score."
- **0:25–0:40** — Task completes; VendorBot's process signs a `TaskCompletion` credential for BuyerBot. Inspector shows BuyerBot's history grow from 2 → 3 completions, live.
- **0:40–0:55** — **The refusal.** A third agent (SpooferBot) requests the same purchase. It presents a *forged* credential (valid JSON, garbage signature) and claims authority. `/decide` → **REFUSED**, receipt shows: "signature invalid; zero valid authority claims for action=purchase." The forge attempt is logged.
- **0:55–1:10** — **The revocation.** Acme revokes BuyerBot's purchase authority in the console (signed revocation). BuyerBot immediately re-requests the purchase → **REFUSED**, receipt: "authority claim revoked at 12:03:41 by Acme key …f2a9." 
- **1:10–1:30** — Zoom out on the receipt log: three receipts, each JSON, each replayable. Close on the thesis slide (also in README): "In two years, agent identity = keys + scoped claims, not platforms."

## 5. The failure/attack scenario

**Scenario: signature forgery + scope confusion, defended in depth.** SpooferBot (a real third process, not a flag on BuyerBot) attempts three attacks in sequence, each defended and shown:

1. **Forged credential**: SpooferBot crafts a well-formed `AuthorityGrant{purchase, unlimited}` claiming Acme as issuer, signs it with its own key. → Caught: issuer-key lookup fails signature verification (`nacl` verify against Acme's registered key). Receipt: refuse, reason `invalid_signature`.
2. **Replayed stolen credential**: SpooferBot replays BuyerBot's *genuine* credential. → Caught: credential `subject` is BuyerBot's key, not the caller's. Subject-binding check refuses. (This is the attack most demo trust systems miss.)
3. **Scope escape**: SpooferBot holds a *valid* credential — a real `AuthorityGrant{purchase, ≤$50}` it legitimately earned — and tries a $800 purchase. → Caught: Cedar policy compares action+amount against claim scope; amount exceeds scope → refuse. No LLM involved in any of the three.

Rollback/containment: refused actions never mutate state; the only writes are the append-only refusal receipts, which is exactly the desired forensic trail.

## 6. File/folder structure

```
builder-league/
├── README.md                     # clean-clone run instructions, demo URL, thesis
├── GATES.md                      # phase gates (unlazy ledger)
├── core/                         # THE SHARED CORE (reused by all 8 challenges)
│   ├── trustcore/                # Module 1 (this challenge)
│   │   ├── crypto.py             # Ed25519 sign/verify, canonical JSON (PyNaCl)
│   │   ├── credentials.py        # VC-shaped issue/verify/revoke + scope matching
│   │   ├── registry.py           # agent identity registry (SQLite)
│   │   ├── policy/               # Cedar policies + tiny evaluator wrapper
│   │   │   ├── trust.cedar       # allow/refuse/escalate rules
│   │   │   └── engine.py
│   │   ├── receipts.py           # DecisionReceipt append-only log
│   │   ├── api.py                # FastAPI: /verify /decide /issue /revoke /receipts
│   │   └── langfuse_hook.py      # opt-in tracing decorator (no-op w/o env keys)
│   └── shared/                   # (stubs now: eventbus, diff — filled by later challenges)
├── agents/
│   ├── buyer.py                  # Agent A process
│   ├── vendor.py                 # Agent B process
│   └── spoofer.py                # attack agent (demo + failure test)
├── ui/                           # React + Tailwind + shadcn/ui inspector
│   └── src/…                     # trust profile view, live receipts, revoke console
├── tests/
│   ├── test_crypto.py
│   ├── test_credentials.py       # incl. replay + scope-escape cases
│   └── test_policy.py
├── demo/
│   └── script.md                 # the 90s runbook, beat-timed
├── docs/
│   ├── plans/2026-09-11-c1-trust-plan.md   # this file
│   ├── architecture.md           # the §3 diagram, expanded
│   └── thesis.md                 # ≤300-word 2-year thesis
├── docker-compose.yml            # trustcore + ui (+ optional langfuse/redis)
└── pyproject.toml / package.json
```

## 7. What I will NOT build (out of scope)

- **No full DID/SSI stack** (no did: method resolution, no ledger/chain anchoring). Credentials are *VC-shaped* JSON + Ed25519; this is the honest "extends an existing standard" bonus without a blockchain.
- **No aggregate reputation score** — deliberately excluded (disqualifier), replaced by claim-traceable counts.
- **No cross-organization federation / trust registry of registries** — single deployment, keys registered locally.
- **No persistent production-grade secrets management** — keys in `.env`/local files; README flags this as demo-grade.
- **No multi-tenant auth on the inspector UI** — demo console is open (it's a demo surface, not the enforcement point).
- **Langfuse/Redis are opt-in** behind env flags so the clean-clone run needs only Python + Node.

## 8. Risk list: 3 ways this could trip a disqualifier

1. **Risk: it degenerates into "a reputation score with no underlying mechanism."**
   Avoidance: the data model has no score field; the UI renders only counts and lists where every row expands to the underlying signed credential with a verify checkmark. Test `test_credentials.py` asserts every displayed aggregate is derivable from stored claims. The phrase "no aggregate score" is a standing design rule copied into README.
2. **Risk: the demo doesn't show a real trust-gated decision (second disqualifier: "no demo of a trust-gated decision").**
   Avoidance: the demo script (§4) contains three gated decisions — accept, refuse-on-forgery, refuse-on-revocation — each producing a machine-readable receipt live on screen. The accept/refuse gate is `/decide`, called by two independent agent processes over HTTP, satisfying the cross-agent bonus signal.
3. **Risk: "real signing/verification, not vibes" fails because crypto is faked or the LLM quietly gates decisions.**
   Avoidance: verification is PyNaCl Ed25519 over canonical JSON with unit tests for tamper, replay, and expiry; the Cedar path is LLM-free by construction, and `DecisionReceipt.llm_called` is asserted `false` in tests for all obvious allow/refuse cases. A judge can flip one signature byte and watch the refusal flip.

---

*Review this plan. On approval I will scaffold the repo and implement TrustCore, the three agents, the UI, tests, and the demo runbook, then verify against GATES.md before reporting done.*
