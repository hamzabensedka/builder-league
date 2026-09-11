# C2 — The Decision Engine: Architecture

**inputs → signals → decision → audit**

DecisionCore is a deterministic decision layer. It takes a *proposed action +
context* in a registered domain and returns one of five outcomes —
**execute · ask · defer · escalate · refuse** — with every number computed
from real, named, weighted signals. There is **no LLM anywhere in
`core/decisioncore`**; that is enforced by an import-linter contract, not just
a promise.

## The pipeline

```
 proposed action            ┌─────────────── DecisionCore ───────────────┐
 + context                  │                                            │
        │                   │  1. AUTHORITY      TrustCore.decide() —    │
        ▼                   │     (confidence +  real Ed25519 signature, │
  POST /api/decision/decide │      risk)         expiry, revocation,     │
        │                   │                    scope. On a FORK so it  │
        │                   │                    never pollutes history. │
        │                   │  2. REVERSIBILITY  SimCore compensation    │
        │                   │     (confidence +  map — is there a cheap, │
        │                   │      risk)         complete reversal?      │
        │                   │  3. EVIDENCE       required vs present     │
        │                   │     (confidence)   context fields; missing │
        │                   │                    ones are NAMED.         │
        │                   │  4. COST-OF-WRONG  amount vs domain        │
        │                   │     (risk)         threshold, normalized.  │
        │                   │  5. HISTORY        past receipt outcomes   │
        │                   │     (confidence)   for actor+action.       │
        │                   │                                            │
        │                   │  weighted sums (pure) → confidence, risk   │
        │                   │  ordered resolution rules (pure) → outcome │
        │                   │  resolution_path records which rule fired  │
        │                   │                                            │
        │                   │  append-only audit → TrustCore receipt log │
        ▼                   └────────────────────────────────────────────┘
   DecisionRecord: outcome, confidence, risk, signals[], evidence_used[],
   missing_information[], reversibility, resolution_path, receipt_id
```

## Why composition, not duplication

- **TrustCore (C1)** is the *only* place authority is verified. DecisionCore
  calls its public `TrustService.decide()` and consumes the verdict — it never
  re-implements signature or scope checks.
- **SimCore (C8)** supplies the *compensation pattern*: reversibility is "does
  a compensating entry exist and is it cheap/complete", the same ledger idea
  as C8's rollback, surfaced as a pre-decision signal rather than a post-hoc fix.
- **The receipt log** is shared and append-only, so a decision's full signal
  vector is independently replayable.

## The resolution rules (ordered, first match wins)

1. authority `invalid` (forged/revoked) on a privileged action → **refuse**
2. authority `uncertain` (no grant on record) → **escalate**
3. confidence < domain floor (missing required evidence) → **ask** (names it)
4. risk high AND not safely reversible → **escalate**
5. risk high AND reversible AND evidence pending → **defer**
6. confidence ≥ execute bar AND risk acceptable → **execute**
7. otherwise → **ask** (gather, don't guess)

Every rule has a dedicated test; determinism is asserted (same inputs → same
outcome, `llm_called=false` on all receipts).

## The three domains

| Domain | Action | Cost threshold | Reversibility |
|--------|--------|---------------|---------------|
| refund | `issue_refund` | $500 | reversal, low cost, full |
| deploy | `deploy_production` | $2000 blast radius | rollback, high cost, **partial** |
| moderation | `remove_content` | 100 reach | restore, low cost, full |

Each domain has its own actor, signed credentials, required/optional evidence
contract, and signal weights — not toy stubs sharing one config.
