# C2 demo runbook — The Decision Engine (90 seconds)

Live at the deployed URL → **C2 · Decision Engine** tab. One-click seed via
`POST /api/decision/demo` (the UI's "Seed the demo" button calls it). All
decisions are computed from signals — there is no prompt box.

## Beats

- **0:00–0:10** — Narration: "Three agents propose actions in three domains.
  The engine decides whether each may act — from signals, not vibes." Click
  **Seed the demo**. Three agents appear (TriageBot, DeployBot, ModBot), each
  with real signed authority and a track record.

- **0:10–0:25** — Domain **refund** → "Clean $120 refund (invoice + reason)".
  Click it. Outcome **EXECUTE**, confidence ~0.9, risk low. Point at the five
  signal bars, the `evidence_used`, and the reversibility line
  ("refund_reversal, low cost, full"). A receipt lands in the audit feed.

- **0:25–0:40** — Domain **refund** → "$2400 refund, missing invoice_id".
  Outcome **ASK** (or defer/escalate) — never execute. The amber
  **Missing information** box names `invoice_id`. Risk bar is up (over the
  $500 threshold). "It doesn't guess — it asks, and tells you what for."

- **0:40–0:55** — Domain **deploy** → "$8000 deploy, fully evidenced (still
  irreversible)". Outcome **ESCALATE**: blast radius over the $2000 threshold
  and rollback is partial+high-cost. Reversibility line reads "partial".
  resolution_path: `risk_high_not_reversible`.

- **0:55–1:15** — **The failure test.** Domain **deploy** → "Failure test:
  $8000 deploy, missing change_ticket". DeployBot holds full valid authority
  and strong history — but it's irreversible, over threshold, and missing a
  critical field. The engine must NOT execute: it **asks** (naming
  `change_ticket`) or escalates. Show the authority signal is green (value
  1.0) — proof the refusal comes from evidence/risk/reversibility, not a fake
  authority failure. Then note: a forged grant on the same action → **REFUSE**
  via real signature verification.

- **1:15–1:30** — Zoom out on the audit feed: every decision a receipt with
  its full signal vector, `llm off` on all. Close on thesis: "In two years,
  every agent action passes a decision layer that can say no — and say why."

## API (for a judge who wants the raw contract)

- `POST /api/decision/demo` — seed three domains
- `GET  /api/decision/domains` — the domain catalog (thresholds, evidence)
- `POST /api/decision/decide` — `{domain, action, actor_key, amount, context}`
  → the DecisionRecord (outcome, confidence, risk, signals, missing info)
- `GET  /api/decision/decisions` — the audit list
- `GET  /api/decision/{id}` — one decision
