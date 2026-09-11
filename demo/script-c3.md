# Demo script — C3 · The Adaptive Agent (90 seconds)

Live at https://builder-league-trust.onrender.com — tab **C3 · Adaptive Agent**.

## Setup (0:00–0:10)

1. Open the C3 tab. Scenario picker defaults to **A · Supplier price spike**.
2. Click **Start adaptive + baseline**. This seeds RestockBot with a real
   Ed25519-signed $1,000 purchase grant plus 4 completion vouches (C1), then
   starts two runs on the same world: adaptive (left), baseline (right).

## Beat 1 — the plan (0:10–0:25)

3. Point at the left column: five steps, each with visible assumptions
   ("NorthParts price ≤ $8.00", "budget headroom ≥ $750.00"…). This is the
   world model made explicit — the thing that will be checked.
4. Click **Advance step →** twice. `verify_price` and `verify_authority`
   execute for real (the authority check is a real signature verification).

## Beat 2 — the world breaks (0:25–0:45)

5. Click **⚡ Price spike → $14.00**. The event lands in the stream (bottom
   panel) with its real effect recorded.
6. Click **Advance step →**. Watch the contradiction banner: the price
   assumption on the *already-executed* verify step breaks — a cascade,
   because the pending order was priced on that reading.

## Beat 3 — "I changed my mind because…" (0:45–1:05)

7. The revision card shows the whole trace: expected $8.00 vs observed $14.00,
   the triggering event, the plan diff (`place_order: supplier NorthParts →
   SouthSupply`, `total 750.0 → 780.0`), the DecisionCore gate verdict
   (`execute`), and the SimCore fork preview ($780 after, 78% of scope) —
   all computed before the new plan activated.
8. Click **Run to end**. The adaptive run completes: 100 units from
   SouthSupply, $780 committed, budget invariant green.

## Beat 4 — the baseline fails silently (1:05–1:20)

9. Right column: click **Run baseline (blind) →**. Same world, same spike —
   but no detection. The baseline orders at the stale plan… and in the
   full-price variant collides with SimCore's enforced invariant
   (`spent + holds ≤ $1,000`), escalated by the ledger, not by the agent.
   (For the sharpest contrast, restart the pair and inject the spike before
   the baseline's place_order step: the adaptive run re-plans; the baseline
   breaches and is caught by enforcement.)

## Beat 5 — the failure test (1:20–1:30)

10. Restart with **C · Flapping price**. Flap up ($8.10) → re-plan to
    SouthSupply. Flap down ($7.40) → better-alternative signal, re-plan back.
    Flap up again → the damping meter shows **escalate_oscillation**: A→B→A
    detected, run handed to a human, receipted. More flaps change nothing.
    That containment *is* the demo: adaptation that can't stop adapting is a
    bug, and here the bug is caught, explained, and audited.
