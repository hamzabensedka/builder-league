# C8 demo runbook — Simulate Before You Act (90 seconds)

Live at the deployed URL → **C8 · Simulate first** tab. Free tier: first
click after idle may take ~30–60s to wake; `/health` answers first.

Prereq: none. Everything is one-click, server-side, fresh keypairs per run.

## Beats

**0:00–0:10 — Frame it.**
"BuyerBot wants to spend $900 of its $1,000 signed purchase authority.
Nothing executes until a human reviews the consequences."
→ Click **Seed the demo**. Buyer appears with real Ed25519 authority + history.

**0:10–0:25 — Simulate.**
→ Click **Simulate $900 purchase**.
The right panel fills with the approval screen: a **before/after diff** —
new `spend` entry, new ALLOW decision receipt, committed balance $0→$900,
scope usage 0→90%. Below it, the **rollback path**: a compensating refund
(+ optional revocation) shown *before* anything runs.
"There's no 'are you sure?' — the diff IS the approval."

**0:25–0:40 — Approve & execute.**
→ Click **Approve & execute**.
Live `/api/trust/decide` runs for real, the ledger appends, post-check is
green. "Simulation and execution are the same code — the diff told the truth."

**0:40–1:00 — The failure test.**
→ Click **Simulate $900 purchase** again, then — before approving — click
**Inject concurrent $200 hold**. VendorBot (a separate actor) reserves budget
in between; the simulation is now stale.
→ Click **Approve & execute** anyway.
Execution succeeds (the $900 authority is genuine), but the **post-execution
invariant check** catches `900 + 200 > 1000` → status flips to **ESCALATED**,
red banner shows the exact excess, **rollback is offered** with the
compensating entries pre-computed.

**1:00–1:20 — Roll back.**
→ Click **Roll back**.
A `refund` entry referencing the spend appends (append-only — nothing is
deleted), the enabling authority is revoked through the real signed C1 path,
the invariant is green again, and the receipt feed shows the whole chain:
simulate → execute → escalate → rollback.
"Undo isn't a promise — it's a logged, verifiable reversal."

**1:20–1:30 — Thesis.**
"In two years, no agent writes without a simulated, human-reviewed diff —
and every wrong prediction has a deterministic net under it."

## If something wakes slowly

The free Render tier cold-starts. If a button spins, wait ~30s and retry —
`/health` responds first and warms the service. Re-clicking **Seed the demo**
is always safe (fresh keypairs each run).
