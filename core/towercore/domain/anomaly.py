"""Drift detection — deterministic rules over the event stream.

No LLM, no vibes: three explicit rules, each producing a DriftFlag with the
evidence attached. When the tower acts on a flag (auto-pause), the flag's
detail IS the audit justification.

Rules (each matches only meaningful events, not routine workflow steps):
1. denial_burst  — >= N action_denied within the last W *meaningful* events:
   the agent is colliding with enforcement repeatedly. The rogue scenario's
   primary signal — a corrupted objective drives repeated refusals.
2. escalation_burst — >= N approval_requested within the last W *meaningful*
   events: the agent keeps demanding over-threshold/over-authority actions a
   human must clear. Containment trigger when denials aren't the failure mode.
3. cost_runaway  — cumulative cost over the agent's budget.
4. oscillation   — the last 4 *distinct* executed actions read A,B,A,B AND
   repeat: real flip-flop churn. Routine start-of-loop steps are excluded so a
   restart after a denied action doesn't false-positive (signal shape borrowed
   from AdaptiveCore's damping).
"""

from dataclasses import dataclass
from typing import Any

from core.towercore.domain.events import AgentEvent
from core.towercore.domain.stream import EventStream

DENIAL_BURST_THRESHOLD = 3
DENIAL_BURST_WINDOW = 10
ESCALATION_BURST_THRESHOLD = 2
ESCALATION_BURST_WINDOW = 8
OSCILLATION_LOOKBACK = 4

# Routine workflow steps that must NOT count toward burst/oscillation windows.
# Including them lets a restart-after-denial masquerade as churn; the detectors
# should watch enforcement outcomes and repeated demands, not the loop's shape.
ROUTINE_ACTIONS = {
    "check_stock", "size_order", "verify_delivery",
    "pop_ticket", "pick_release", "verify_ticket",
}


def _meaningful(events: list[AgentEvent]) -> list[AgentEvent]:
    """Events that carry enforcement signal: decisions, outcomes, demands,
    drift, interventions — not the loop's routine housekeeping steps."""
    out = []
    for e in events:
        if e.kind in ("action_executed", "action_denied", "approval_requested",
                      "drift_flagged", "intervention_applied", "blocker_raised",
                      "cost_recorded"):
            if e.kind == "action_executed" and e.payload.get("action") in ROUTINE_ACTIONS:
                continue
            out.append(e)
    return out


@dataclass(frozen=True)
class DriftFlag:
    agent_id: str
    kind: str  # denial_burst | cost_runaway | oscillation
    summary: str
    detail: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "kind": self.kind,
            "summary": self.summary,
            "detail": self.detail,
        }


def detect_drift(
    stream: EventStream, agent_id: str, *, budget_usd: float
) -> list[DriftFlag]:
    """Evaluate all rules over the agent's event history. Pure and total:
    same stream in → same flags out (tested)."""
    events = _meaningful(stream.for_agent(agent_id))
    flags: list[DriftFlag] = []

    burst = _denial_burst(events)
    if burst:
        flags.append(burst)
    esc = _escalation_burst(events)
    if esc:
        flags.append(esc)
    runaway = _cost_runaway(events, agent_id=agent_id, budget_usd=budget_usd)
    if runaway:
        flags.append(runaway)
    oscillation = _oscillation(events, agent_id=agent_id)
    if oscillation:
        flags.append(oscillation)
    return flags


def _escalation_burst(events: list[AgentEvent]) -> DriftFlag | None:
    window = events[-ESCALATION_BURST_WINDOW:]
    requests = [e for e in window if e.kind == "approval_requested"]
    if len(requests) >= ESCALATION_BURST_THRESHOLD:
        return DriftFlag(
            agent_id=requests[-1].agent_id,
            kind="escalation_burst",
            summary=(
                f"{len(requests)} over-authority action requests in the last "
                f"{len(window)} events — demanding actions a human must clear"
            ),
            detail={
                "requests": len(requests),
                "window": ESCALATION_BURST_WINDOW,
                "actions": [e.payload.get("action") for e in requests],
            },
        )
    return None


def _denial_burst(events: list[AgentEvent]) -> DriftFlag | None:
    window = events[-DENIAL_BURST_WINDOW:]
    denials = [e for e in window if e.kind == "action_denied"]
    if len(denials) >= DENIAL_BURST_THRESHOLD:
        return DriftFlag(
            agent_id=denials[-1].agent_id,
            kind="denial_burst",
            summary=(
                f"{len(denials)} denied actions in the last "
                f"{len(window)} events — colliding with enforcement"
            ),
            detail={
                "denials": len(denials),
                "window": DENIAL_BURST_WINDOW,
                "events_seen": len(window),
                "denied_actions": [e.payload.get("action") for e in denials],
            },
        )
    return None


def _cost_runaway(
    events: list[AgentEvent], *, agent_id: str, budget_usd: float
) -> DriftFlag | None:
    spent = sum(
        float(e.payload.get("cost_usd", 0.0)) for e in events if e.kind == "cost_recorded"
    )
    if spent > budget_usd:
        return DriftFlag(
            agent_id=agent_id,
            kind="cost_runaway",
            summary=f"spent ${spent:.4f} against a ${budget_usd:.4f} budget",
            detail={"spent_usd": round(spent, 6), "budget_usd": budget_usd},
        )
    return None


def _oscillation(events: list[AgentEvent], *, agent_id: str) -> DriftFlag | None:
    actions = [
        e.payload.get("action") for e in events
        if e.kind == "action_executed" and e.payload.get("action")
    ]
    recent = actions[-OSCILLATION_LOOKBACK:]
    if len(recent) == OSCILLATION_LOOKBACK and recent[0] == recent[2] and recent[1] == recent[3] \
            and recent[0] != recent[1]:
        return DriftFlag(
            agent_id=agent_id,
            kind="oscillation",
            summary=f"flip-flopping: {' -> '.join(recent)}",
            detail={"pattern": recent},
        )
    return None
