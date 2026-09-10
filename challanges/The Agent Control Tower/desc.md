← All challenges
live
66d 5h left
$500 + Agent Commander badge
The Agent Control Tower
How do humans manage an AI workforce when agents can act across real systems?

Brief
Overview
Once AI agents act across real systems, humans need a control surface, not a chatbot. Build the cockpit that lets a human operate, audit, and intervene on a fleet of agents in real time.

What you'll build
An operator UI showing the live agent fleet: status, recent actions, blockers, drift
An approval queue for risky actions, plus a per-agent kill switch
Cost and token usage per agent per task
Replay any agent's reasoning for the last N steps
At least 3 simulated agents doing different jobs you can watch and intervene on
Deliverables
Working build (repo + live demo or recorded walkthrough)
90-second Loom showing intervention in flight (approve, pause, kill, replay)
Architecture snapshot: agent events → control plane → operator UI
One failure test: an agent goes rogue, show how the tower catches and contains it
Two-year thesis (≤300 words) on agent operations as a discipline
Why it matters
The org that owns the agent control plane owns AI ops. This is the SRE layer of the agent era.

Requirements
Submission checklist
Public repo URL (clean clone runs)
Live demo URL (required): a working link anyone can open
90-second Loom or video walkthrough (optional, but recommended)
Notes: AI tools used, key decisions, out of scope
How you'll be measured
Weight	Criterion	What we look for
25	Conceptual clarity	UI matches how an operator actually thinks.
25	Technical depth	Real event stream + control plane, not a static dashboard.
20	Demo quality	A non-builder can run an intervention themselves.
15	Failure thinking	Rogue-agent scenario is concrete and contained.
15	Future thesis	Strong view on agent ops tooling.
Bonus signals
Multi-tenant or multi-team awareness
Audit log exportable for compliance
Disqualifications
A read-only dashboard with no intervention
No agents actually running, just mockups
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
