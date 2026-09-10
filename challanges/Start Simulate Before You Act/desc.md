← All challenges
live
66d 5h left
$500 + World Model Builder badge
Simulate Before You Act
Can an AI system think through consequences before it changes something?

Brief
Overview
Agents that act on real systems need to think through consequences first. Build a simulation layer that runs before any write, and shows the human what's about to happen.

What you'll build
Before executing a write or external action, the agent simulates the likely outcome
The simulation shows projected effects, side effects, who/what is impacted, and the rollback path
The user approves, tweaks, or rejects in one step
At least one high-stakes action (send money, mass email, delete data, deploy code) gated this way
Deliverables
Working build (repo + live demo or recorded walkthrough)
90-second Loom showing a "simulate → review → execute" cycle on a real action
Architecture snapshot: intent → simulate → present → execute/rollback
A failure test: simulation under-predicts a side effect, show the safety net
Two-year thesis (≤300 words) on simulation-gated agents
Why it matters
"Undo" is not enough at agent speed. Whoever ships the simulate-first pattern owns the safety story.

Requirements
Submission checklist
Public repo URL (clean clone runs)
Live demo URL (required): a working link anyone can open
90-second Loom or video walkthrough (optional, but recommended)
Notes: AI tools used, key decisions, out of scope
How you'll be measured
Weight	Criterion	What we look for
25	Conceptual clarity	Simulation actually changes the decision, not just narrates it.
25	Technical depth	Real preview of effects, real rollback path.
20	Demo quality	Reviewer feels safe approving the action in 90s.
15	Failure thinking	Wrong prediction is caught downstream.
15	Future thesis	Strong view on simulation as default for agents.
Bonus signals
Diff-style presentation of "before vs after"
Works against a real API/system, not a mock
Disqualifications
A "are you sure?" confirm dialog dressed up as simulation
No real action being gated
No demo
Submit your build
Repo URL (GitHub/GitLab)
https://github.com/you/mission-build
Demo URL (live, required)
https://your-demo.app
Loom / video walkthrough (optional)
https://loom.com/share/...
Notes (what to look at, AI usage, decisions)

A live demo URL is required. The video walkthrough is optional.

Submit entry
