# Demo script — C5 · The Agent Control Tower (90 seconds)

Live at https://builder-league-trust.onrender.com — tab **C5 · Control Tower**.

## Setup (0:00–0:10)

1. Open the C5 tab. Click **Enroll the fleet**. Three agents register with
   real Ed25519-signed authority (C1): RestockBot (purchase ≤$500), RefundBot
   (refund ≤$600), DeployBot (deploy, no amount scope). The live event stream
   on the right starts flowing the moment they act.

## Beat 1 — watch the fleet work (0:10–0:30)

2. Click **Step** on RestockBot three times: check stock → size order → a real
   purchase, simulated-before-write on the SimCore ledger and gated by
   TrustCore authority. Each step lands in the stream with its cost (metered
   estimate) and token count.
3. Point at the fleet table: status dot, last action, per-agent cost — all
   folded from the same event log, never a separate store.

## Beat 2 — an approval arrives mid-flight (0:30–0:50)

4. Click **Step** on DeployBot three times: pick release v12 → verify ticket →
   deploy. v12 has **no change ticket**, so DecisionCore escalates and the
   deploy **parks in the approval queue** (center column), naming the missing
   field. The agent's status flips to *awaiting approval*.
5. Click **Approve**. The gate releases the agent; the resolution is receipted
   to the stream. (Click **Deny** instead to watch the deploy skipped, never
   executed.)

## Beat 3 — replay any agent's reasoning (0:50–1:05)

6. Click **Replay** on DeployBot. A drawer folds the last N events into a
   readable trace: every step, the decision request, the escalation, the
   approval — each line carrying its sequence number so it cross-references
   the audit export exactly.

## Beat 4 — the failure test: an agent goes rogue (1:05–1:25)

7. Click **Inject rogue objective**. DeployBot's objective is corrupted
   mid-run: it now tries to deploy any version at any blast radius, no ticket.
8. Keep clicking **Step**, and **Deny** each over-authority demand that parks.
   After the second rogue demand the **escalation-burst** detector fires: a red
   **drift** badge appears and the tower **auto-pauses** the agent — containment
   without waiting for a human to notice.
9. Click **Kill**. Terminal state; the next step raises on the gate. Then click
   **Export audit** — the full incident as one ordered trail: injection →
   demands → denials → drift flag → auto-pause → kill.

## Close (1:25–1:30)

10. The point in one line: the fleet, the costs, the drift flags, and the audit
    export are all folds over ONE append-only stream, and every intervention is
    enforced on the agent's execution path — this is a control plane, not a
    dashboard.
