# C6 — The Autonomous Company Simulator — Architecture

**Northwind Components**: a small B2B parts company run as a loop of four
accountable agent roles on one shared, event-sourced record system.

## The spine

One append-only **CompanyEvent** log (`core/companycore/domain/log.py`) is the
single source of truth. Every quote, order, payment, invoice, freeze,
directive, and escalation is a typed event. **Ledger state, KPIs, the human
inbox, and day-replay are all pure folds over this log** — the UI can never
show state the spine didn't record, and "replay a day" is just a cutoff fold
(`replay_day(events, n)`). This is the direct answer to the challenge's
disqualifier "no shared state, just isolated prompt chains."

## The four roles

| Role | Brain | Real actions on the shared record |
| --- | --- | --- |
| SalesBot | scripted policy | qualify lead → quote → win/lose → invoice (AR) |
| OpsBot | scripted policy | watch inventory vs. backlog → raise PO → receive stock → AP bill |
| FinanceBot | scripted policy | collect due AR, pay due AP, enforce budget, freeze spend |
| ChiefOfStaff | OpenRouter LLM (scripted fallback) | one cross-functional directive/day, propose-only |

## Enforcement composition

Roles **propose**; the existing graded cores **enforce**. The company inherits
six challenges of rigor rather than re-implementing it:

- **TrustCore** — each role holds signed, scoped authority (Sales quote ≤$5k,
  Ops PO ≤$8k, Finance payment ≤$20k). Over-scope is cryptographically refused.
- **DecisionCore** — borderline actions return `ask`/`escalate` and park in the
  human inbox; they never execute silently.
- **SimCore / MemoryCore / TowerCore** — before/after previews on big moves,
  customer memory with calibrated uncertainty, and fleet-level drift/pause/kill.
- **LLM propose-only** — ChiefOfStaff output is parsed by a strict domain
  choke point (`directives.py`) into a typed directive; anything unparseable
  becomes a harmless `none`. The enforcement path is LLM-free (import-linter
  enforced), and a scripted fallback keeps clean clones running offline.

## The run-the-week loop

`POST /api/company/advance` ticks one day: world tick (leads, aging, due
items) → roles act in order (Sales → Ops → Finance → ChiefOfStaff), each
action gated before its event lands → KPI fold → `day_ticked`. Escalations
park in the human inbox until resolved inline.

## Escalation & self-correction

- **Human inbox**: `ask`/`escalate` outcomes raise a card the human answers;
  resolutions are themselves events, so replays include the human's choices.
- **Self-correction (cash crunch)**: a churn + early-bill shock drops runway
  below threshold → Finance freezes spend, Ops defers POs, Sales pushes
  collections, ChiefOfStaff ratifies — no human click required.
- **Failure test (rogue sales)**: an injected fault makes Sales over-discount
  → TrustCore refuses → refusal streak → `role_paused` → Ops/Finance
  compensate; the operator replays and kills or restores the role.
