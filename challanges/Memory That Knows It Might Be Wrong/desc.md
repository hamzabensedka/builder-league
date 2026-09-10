← All challenges
live
66d 5h left
$500 + Context Engineer badge
Memory That Knows It Might Be Wrong
How can AI remember without becoming inaccurate, invasive, or overconfident?

Brief
Overview
Agent memory today is either too thin to be useful or too greedy to be safe. Build a memory layer that knows what it knows, what it doesn't, and when to forget.

What you'll build
A memory layer that tags each fact with: source, confidence, freshness, scope (who/what it applies to)
On retrieval, the agent shows what it's relying on and how sure it is
A forgetting policy: stale, contradicted, or user-revoked memories are handled explicitly
A demo where the memory says "I might be wrong about this" and acts accordingly
Deliverables
Working build (repo + live demo or recorded walkthrough)
90-second Loom showing memory in action, including an "I'm not sure" moment
Architecture snapshot: write path, retrieval path, forgetting path
A failure test: contradictory facts, stale data, or a privacy revocation, show what happens
Two-year thesis (≤300 words) on agent memory done right
Why it matters
Bad memory makes agents confidently wrong. Good memory is the difference between a tool and a colleague.

Requirements
Submission checklist
Public repo URL (clean clone runs)
Live demo URL (required): a working link anyone can open
90-second Loom or video walkthrough (optional, but recommended)
Notes: AI tools used, key decisions, out of scope
How you'll be measured
Weight	Criterion	What we look for
25	Conceptual clarity	Memory model addresses accuracy, privacy, and overconfidence.
25	Technical depth	Real storage + retrieval + forgetting, not just RAG.
20	Demo quality	"I might be wrong" moment lands in 90s.
15	Failure thinking	Contradiction or revocation is handled explicitly.
15	Future thesis	Strong view on agent memory.
Bonus signals
User-facing memory inspector ("what do you remember about me?")
Privacy controls demoed, not just claimed
Disqualifications
Plain vector RAG with no confidence/forgetting model
No demo of the "wrong/forget" mechanic
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
