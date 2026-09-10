← All challenges
live
66d 5h left
$500 + Decision Architect badge
The Decision Engine
Can you build an AI system that knows when it is allowed to act?

Brief
Overview
Most "AI agents" execute every instruction they receive. Real-world systems need an explicit decision layer that decides whether to act at all, based on confidence, risk, evidence, reversibility, and the cost of being wrong.

What you'll build
A decision layer that takes a proposed action + context and returns one of: execute · ask · defer · escalate · refuse
Each decision surfaces confidence, risk score, evidence used, missing information, and reversibility
A full audit trail per decision (inputs, signals, reasoning, outcome)
At least 3 example domains wired in (e.g. ticket triage, refund approval, code deploy, content moderation)
Deliverables
Working build (repo + live demo or recorded walkthrough)
90-second Loom walking through one full decision end-to-end
Architecture snapshot (diagram or one-pager): inputs → signals → decision → audit
One deliberate failure test: a case designed to break it, and what happens when it does
A two-year thesis (≤300 words) on where decision layers go next
Why it matters
The hardest part of agentic systems is not "calling tools", it is knowing when not to. Whoever nails this owns the trust layer of AI work.

Badge
Decision Architect, awarded on shortlist/win.

Requirements
Submission checklist
Public repo URL (GitHub/GitLab), must run from a clean clone with a README
Live demo URL (required): a working link anyone can open
90-second Loom or video walkthrough (optional, but recommended)
Notes: AI tools used, key decisions, what's intentionally out of scope
How you'll be measured
Reviewed on a 100-point rubric by the DOO team and judges:

Weight	Criterion	What we look for
25	Conceptual clarity	Does the build actually address the mission's core question?
25	Technical depth	Real system, not a prompt wrapper. Architecture has substance.
20	Demo quality	A stranger understands it in 90 seconds. Crisp, honest, tight.
15	Failure thinking	You picked a hard edge case and showed what happens.
15	Future thesis	Two-year direction is sharp and opinionated, not generic.
Bonus signals
Easy to run locally (clear README, .env.example)
Real or realistic synthetic data, not toy examples
Honest about limits, "this breaks when…" earns points
Disqualifications
Pure prompt wrappers with no system around them
No demo, or a demo that doesn't show the core mechanic
Repos that 404, won't install, or hide the actual logic
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
