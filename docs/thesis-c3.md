# Thesis — C3: The Adaptive Agent

An agent that re-prompts itself every N seconds is not adaptive; it is
expensive. Adaptation is a *detection* problem: the agent must know its model
of the world broke, and know it before acting on the stale model.

AdaptiveCore makes the model explicit. Every plan step declares typed
assumptions — price caps, budget headroom, authority, availability, delivery
windows. The world pushes changes as events with real side effects (a
concurrent hold genuinely shrinks the shared SimCore ledger; a revocation
genuinely kills a TrustCore credential). Each advance re-verifies active
assumptions against observed reality; only a contradiction — a belief that
held at planning time and fails now — may trigger a re-plan. No timers, no
polling loops, no LLM: detection is a pure function, and import-linter keeps
it that way.

Re-planning is a rule product, not a hallucination: cheapest feasible
supplier, order re-sized to real headroom, every revised purchase gated by
DecisionCore and previewed on a SimCore fork before activation. Each revision
ships the receipt a judge needs: the contradicted assumptions with expected
vs observed values, the triggering events, a structural plan diff, and an
audit receipt — "I changed my mind because…" as data, not prose.

Adaptation itself can fail, so the loop carries damping: hysteresis absorbs
sub-margin noise, a revision budget caps churn, and A→B→A oscillation
detection hands an unstable world to a human. The failure test flaps a price
across the decision boundary and watches the agent flip suppliers twice,
refuse the third flip, and escalate — receipted.

Beside it, the baseline runs blind: same world, same events, no detection.
It overspends the enforced budget and gets caught by SimCore's invariant —
failing against reality, not against a script. That side-by-side is the
thesis: adaptation is worth building only because its absence is a silent,
real loss.
