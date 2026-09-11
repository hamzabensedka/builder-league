# Thesis — C5: The Agent Control Tower

When agents act across real systems, the scarce resource is not intelligence
but operational control. The org that owns the agent control plane owns AI
ops, the way owning the pager owned the last era of software. This is the SRE
layer of the agent era.

A read-only dashboard is a liability dressed as safety: it shows the fire
after the building is down. Control means operator and agent share one source
of truth. TowerCore makes every agent fact — action, refusal, cost, drift,
intervention — a single event in one append-only stream, then folds the fleet
view, the cost totals, and the audit export from that same log. The UI cannot
drift from reality because there is nothing to drift from.

Intervention must be enforced, not advisory. A kill switch the agent can
outrun is a suggestion. Every step passes the gate before acting: pause halts
the next step, kill is terminal, and killing auto-denies any parked approval
so a dead agent's action never slips out. Risky work parks in an approval
queue where a human, not a threshold, decides.

Drift is a detection problem, and containment cannot wait for a human to
notice. Deterministic rules watch the stream — denial bursts, escalation
bursts, cost runaway, oscillation — and the tower auto-pauses on a flag,
receipting the evidence. The human stays the final authority; the machine just
refuses to let a rogue agent keep moving while the pager buzzes.

The proof is the failure test: inject a corrupted objective into DeployBot and
watch enforcement refuse, the detector flag, the gate pause, the operator
replay and kill — one auditable chain from injection to containment. That
chain, exportable for compliance, is the discipline: agent operations is not
prompting harder, it is observability, enforced intervention, and a forensic
trail. Own that, and you own the fleet.
