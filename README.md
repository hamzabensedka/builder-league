# Builder League — TrustCore (Challenge 1: The Agent That Earns Trust)

A trust layer for AI agents: W3C-VC-shaped **verifiable credentials** (Ed25519),
a deterministic **policy engine** (no LLM on the enforcement path), and an
**append-only decision receipt** for every gated action. Built as Module 1 of a
shared core reused by all 8 Builders League challenges.

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
.venv/Scripts/python -m pytest        # 38 tests
.venv/Scripts/python -m ruff check .  # lint
.venv/Scripts/lint-imports            # architecture contracts (3 kept)
```
