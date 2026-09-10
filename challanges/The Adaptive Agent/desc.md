← All challenges
live
66d 5h left
$500 + Adaptive Intelligence Builder badge
The Adaptive Agent
Can an AI system recognize that reality changed and safely change its mind?

Brief
Overview
Most agents commit to a plan and execute it blindly. The world keeps moving. Build an agent that notices when reality has changed and safely updates its plan, without losing context or making things worse.

What you'll build
An agent that runs a multi-step plan and continuously checks whether its world model is still valid
Re-planning triggers when new signals contradict prior assumptions (not on a fixed timer)
A visible "I changed my mind because…" trace for every revision
At least 2 demo scenarios where the original plan would have failed silently if not adapted
Deliverables
Working build (repo + live demo or recorded walkthrough)
90-second Loom walking through one adaptive run end-to-end
Architecture snapshot: plan → execute → observe → re-evaluate loop
A failure test: one scenario where adaptation goes wrong, and how you contain it
Two-year thesis (≤300 words) on adaptive planning in production agents
Why it matters
Static agents break the moment reality shifts. Adaptive agents are the difference between a demo and a deployable system.

Requirements
Submission checklist
Public repo URL (clean clone runs)
Live demo URL (required): a working link anyone can open
90-second Loom or video walkthrough (optional, but recommended)
Notes: AI tools used, key decisions, out of scope
How you'll be measured
Weight	Criterion	What we look for
25	Conceptual clarity	Adaptation is mission-driven, not random re-prompting.
25	Technical depth	Real plan/observe/revise loop with persisted state.
20	Demo quality	The "before/after" of adaptation is obvious in 90s.
15	Failure thinking	You showed where adaptation fails and how you handle it.
15	Future thesis	Sharp view on adaptive agents in production.
Bonus signals
Side-by-side comparison with a non-adaptive baseline
Streaming/event-driven inputs, not just polled snapshots
Disqualifications
"Re-prompt every N seconds" with no real change detection
No demo, broken repo, or hidden logic
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
