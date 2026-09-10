# TrustCore — Architecture Snapshot

Required deliverable chain: **identity → claims → verification → policy**.

```
                          ┌─────────────────────────── TrustCore ───────────────────────────┐
                          │                                                                 │
  Human owner ──signs──▶  1. IDENTITY: Ed25519 keypair per agent (public key = identity)    │
                          │         │                                                       │
                          │         ▼                                                       │
  Issuer agents ──sign──▶  2. CLAIMS: VC-shaped credentials (issuer, subject, type,         │
                          │            claim, scope, expiry, revocation, signature)         │
                          │         │                                                       │
                          │         ▼                                                       │
  Counterparty request ─▶  3. VERIFICATION: Ed25519 signature over canonical JSON +         │
                          │            expiry + revocation + subject-binding + scope        │
                          │         │                                                       │
                          │         ▼                                                       │
                          │   4. POLICY: allow / refuse / escalate (pure function of        │
                          │            verified claims — NO LLM on this path)               │
                          │         │                                                       │
                          │         ▼                                                       │
                          │   5. RECEIPTS: append-only JSON per decision                    │
                          │            (inputs, signals, reasoning, llm_called=false)       │
                          └─────────────────────────────────────────────────────────────────┘
                                          ▲
              ┌───────────────────────────┼───────────────────────────┐
              │                           │                           │
     Agent A (buyer process)     Agent B (vendor process)      React inspector UI
              │                           │                     (claims + verify ✓,
              └────── all actors call TrustCore HTTP API (/api/trust/*) ──────────┘
```

## Layers (hexagonal, enforced by import-linter)

| Layer | Contains | May import | Must not import |
|-------|----------|-----------|-----------------|
| `core/trustcore/domain` | crypto, credentials, policy — pure, zero I/O | stdlib, PyNaCl | fastapi, sqlalchemy, redis, httpx |
| `core/trustcore/application` | use-case services, ports (Protocols), Receipt | domain only | adapters, frameworks |
| `core/trustcore/adapters` | in-memory stores (SQLite later), clocks | application, domain | — |
| `api/` | FastAPI boundary: Pydantic DTOs, signature gates | application, domain | — |
| `ui/` | React inspector (read + revoke console) | HTTP API | core internals |

## Trust decision flow (per `/api/trust/decide`)

1. Fetch all credentials whose `subject_key` = requester's public key.
2. For each: `verify_credential` → failures among {`invalid_signature`,
   `expired`, `revoked`}. All failures recorded in the receipt's signals.
3. Partition valid credentials into `AuthorityGrant`s and `TaskCompletion`s.
4. `evaluate(action, amount, valid_authority, completion_count)`:
   - no authority claim covers action+amount → **refuse**
   - authority covers + history > 0 → **allow**
   - authority covers + zero history → **escalate** (LLM may draft reasoning here, never decides)
5. Append a `Receipt` (append-only store — no update/delete code paths exist).

## Attack defenses (plan §5, each a test)

| Attack | Defense | Where |
|--------|---------|-------|
| Forged credential | signature verify against issuer's registered key | `domain/crypto.py`, `test_credentials.py` |
| Replay (stolen credential) | subject-binding: credential subject must equal caller | `domain/credentials.py` (signed payload) |
| Scope escape (valid cred, over-limit action) | deterministic scope match (action ∈ actions, amount ≤ max) | `domain/policy.py`, `test_policy.py` |
| Malicious revocation by non-issuer | revoke endpoint requires issuer request signature | `api/main.py`, `test_api.py` |
| Unsigned revocation edit | indistinguishable from tamper → invalid_signature | `test_demo_scenario.py` |
