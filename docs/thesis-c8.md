# Two-year thesis — simulation as the default for agents

In two years, "are you sure?" will be dead: no serious agent will write to a
real system without first showing a human a computed diff of what will change.

The reason is speed. Agents act in milliseconds across money, email, and
production infra; "undo" can't keep up because side effects spread slower
than the agent acts. A refund clawed back after a wrong mass-payout isn't a
rollback — it's damage control. The only durable safety story moves review
*before* the write, and makes that review concrete.

Concrete means three things, all load-bearing in this build:

1. **The preview is a diff, not a narration.** A human approves a structural
   before/after of real state — balances, new records, scope usage — not a
   sentence a model wrote about them. Narration can be persuasive and wrong;
   a diff computed from a fork of live state can't lie about *what changes*.

2. **Simulation and execution are one code path.** If the preview runs
   different logic than the real write, the preview is theatre. The only
   honest architecture is a single pipeline aimed at a fork (to preview) or
   the live store (to commit).

3. **Prediction will still be wrong — so the net is downstream.** A fork is
   a snapshot; the world moves between simulate and approve (a concurrent
   hold, a changed price). Simulation narrows surprise, it can't eliminate
   it. Systems that survive re-check invariants *after* execution, escalate
   automatically, and keep a real compensating action — not an "undo"
   promise — one click away, fully logged.

The winners in agent tooling won't be the ones with the most autonomy.
They'll be the ones whose agents a CFO lets touch money at 3am, because
every write arrived as a reviewable diff and every mistake had a logged,
verifiable reversal. Simulate-first is how agents earn that.

*(232 words)*
