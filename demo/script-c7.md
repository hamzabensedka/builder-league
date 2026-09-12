# C7 demo script — 90 seconds, live at the demo URL

Tab: **C7 · Canvas**. Workflow: ops operator on shift over the agent fleet.
Narration in quotes; actions in bold.

## Beat 0 — the contrast (0:00–0:15)

"The dashboard and the chatbot are the wrong defaults. This repo already
ships a monitoring dashboard for this exact fleet — the Control Tower tab."
**Click "⇄ What this replaces"** → Tower tab: fleet table, event feed,
approval queue. "Rows, feeds, queues. That's what we're replacing."
**Click back to C7 · Canvas.** "Same fleet. Same events. Watch."

## Beat 1 — calm by default (0:15–0:30)

**Click "Start the shift".** The canvas binds to the live fleet.
"Nothing is rendered. No KPI grid, no feed. The interface's job is deciding
what *not* to show." Point at the ambient line: *"Fleet steady. Nothing needs
you right now."* **Step RestockBot once** — a low-stock signal folds in.
Show the "Inferred, but deliberately not shown" list: the restock hypothesis
sits below threshold. "It saw it. It chose not to interrupt."

## Beat 2 — the interface acts first (0:30–0:55)

**Step DeployBot three times.** On the third step the v12 deploy has no
change ticket → DecisionCore escalates → the action parks.
"Nobody asked for anything. The interface initiated this." The single
decision card appears: *Deploy needs review*, confidence 80%, the evidence
chain, the pre-simulated SimCore outcome and the pre-computed rollback.
"The approval isn't a confirm dialog — it's a computed before/after. The
machine did the homework; I just decide." **Approve & execute.** The parked
tower approval resolves through the real queue.

## Beat 3 — the failure test: wrong-guess recovery (0:55–1:20)

**Step DeployBot** until another review card surfaces. **Reject it:**
"Not the right call." Point at card history: the rejection is receipted, and
a correction fact lands in MemoryCore. **Resume + step DeployBot again** —
the same kind of card returns, visibly *demoted*: confidence halved, badge
"you corrected this before". "The interface learned. Reject it again and it
stops guessing entirely — manual mode hands me the raw events instead of a
third confident mistake."

## Beat 4 — close (1:20–1:30)

"Chat is a fallback for a system that doesn't know what you need. This one
does: inference over interrogation, action before permission, and wrongness
as a first-class path. All of it receipted, none of it a prompt box."
