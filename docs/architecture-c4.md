# C4 — Memory That Knows It Might Be Wrong architecture

MemoryCore is a memory layer that knows what it knows, what it doesn't, and
when to forget. Not vector RAG: every mechanic the brief names — source,
confidence, freshness, scope, contradiction, revocation — is a first-class,
deterministic, testable domain object. There is no hidden scorer and no LLM
anywhere on the write, retrieval, or forgetting path.

## The fact is the unit

Every remembered claim carries the four tags the brief demands:

| Tag | Where it lives | How it behaves |
| --- | --- | --- |
| source | `Provenance(source, kind)` | `user_stated > observed > inferred > imported` — an explicit trust table |
| confidence | `base_confidence` | source trust × extraction confidence; boosted by corroboration, never above 1 |
| freshness | `half_life_days` + optional TTL | exponential decay; TTL expiry is the only hard zero |
| scope | `user_id / agent_id / task_id` | retrieval is scope-gated — user isolation always, task facts never leak |

Facts are immutable value objects. Corroboration and supersession write NEW
versions; nothing is mutated in place, nothing is silently deleted.

## Three paths, one audit spine

```
                         ┌──────────────────────────────────────────┐
 WRITE  observation ──▶  │ learn: dedup? ─ corroborate (boost)      │
                         │          └─ conflict? ─ resolve_conflict │
                         │             supersede / reject /         │
                         │             CONTRADICTION: trust NEITHER │
                         └──────────────┬───────────────────────────┘
                                        │ facts (immutable, decaying)
 RETRIEVE  query + scope ──▶ scope gate ─▶ keyword/slot match
                              ─▶ rank relevance × decayed confidence
                              ─▶ RELIANCE RECEIPT: relied_on +
                                 calibrated_confidence + gaps
                              ─▶ below ACT_THRESHOLD (0.55):
                                 verdict "unsure" — the agent hedges
                                 or asks instead of acting confident
                                        │
 FORGET   sweep (stale) ──┐              ▼
          conflict ───────┼──▶ TOMBSTONE (reason + detail + time)
          signed revoke ──┘    cascade to derived facts
                                        │
                         every learn / recall / forget ─▶ TrustCore
                         append-only receipt log (llm_called=false)
```

## Retrieval says how sure it is — and acts accordingly

`recall` returns a reliance receipt, not just facts: what it's relying on
(fact ids, values, per-fact effective confidence), a calibrated aggregate
(the *weakest* relied-on link — generous aggregation is where overconfidence
comes from, so we don't), and named gaps. Below the acting threshold the
verdict is `unsure` and the demo agent says "I might be wrong about this —
I only inferred it once" and asks to confirm. Nothing remembered at all is
`unknown`, a third, distinct state — "I don't know" is not "I'm not sure".

## Contradiction: the honest tie-break

Same-slot conflicts resolve deterministically:

- same value → **corroborate** (the existing fact gets a confidence boost);
- decisive margin (≥0.15 effective confidence) → **supersede** (or reject the
  incoming fact) — the loser is tombstoned with the margin in the receipt;
- near-equal → **contradiction**: BOTH facts are tombstoned and retrieval
  reports the conflict instead of picking a side. When memory can't tell
  which of two claims is right, the correct answer is to trust neither.

## Forgetting is explicit, receipted, and cascading

Three triggers, one mechanism — the tombstone, which keeps the fact id, slot,
value, reason, and time forever so the system can explain "I used to know
this, and here's why I stopped":

- **stale** — TTL expired or decayed below the usefulness floor; the sweeper
  names every fact it kills;
- **contradicted / superseded** — lost a same-slot conflict;
- **revoked** — the user signs a forget request (Ed25519 over the exact
  payload, verified fail-closed via TrustCore crypto; unsigned requests are
  refused). Revocation **cascades**: forget my city, and the timezone
  inferred from it dies too — privacy is not negotiable halfway.

The memory inspector (`GET /api/memory/inspect`) answers "what do you
remember about me?" with every live fact's tags plus the tombstone list.

## The failure test, concretely

`tests/test_memory_failure.py` exercises all three brief-named failures over
the real stack: near-equal contradiction trusts neither side; a TTL-expired
import is never relied on after the sweep; a forged revocation signature is
refused fail-closed and changes nothing; task- and user-scoped facts never
leak across boundaries; identical event sequences produce bit-identical
recalls across two independent stacks.

## Composition

| Need | Surface |
| --- | --- |
| Revocation signatures | TrustCore `verify_payload` (fail-closed) |
| Audit trail | TrustCore `record_event` → the SAME append-only receipt log |
| HTTP boundary | `api/main.py` `/api/memory/*` — Pydantic validation, thin adapter |
| Persistence | in-memory stores (repo convention; append-only by construction) |

Import-linter contract: MemoryCore reaches other cores only via
application+domain public surfaces, and is LLM-free — both enforced.
