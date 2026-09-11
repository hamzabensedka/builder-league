"""Registry — live fleet state folded from the event stream + gate.

The registry is a VIEW, never a store: every number shown to the operator is
derived from the same append-only log the control plane enforces on. The UI
cannot drift from reality because there is nothing to drift from.

Status priority (highest wins): killed > paused > awaiting_approval >
blocked > running.
"""

from typing import Any

from core.towercore.domain.anomaly import detect_drift
from core.towercore.domain.gate import AWAITING, KILLED, PAUSED, InterventionGate
from core.towercore.domain.stream import EventStream


def fleet_view(
    stream: EventStream,
    gate: InterventionGate,
    *,
    budgets: dict[str, float],
    recent_n: int = 5,
) -> dict[str, dict[str, Any]]:
    """Fold the whole stream into per-agent operator state."""
    agent_ids = {e.agent_id for e in stream.all()} | set(gate.states()) | set(budgets)
    return {
        agent_id: _agent_view(stream, gate, agent_id, budgets.get(agent_id, 0.0), recent_n)
        for agent_id in sorted(agent_ids)
    }


def _agent_view(
    stream: EventStream,
    gate: InterventionGate,
    agent_id: str,
    budget_usd: float,
    recent_n: int,
) -> dict[str, Any]:
    events = stream.for_agent(agent_id)
    gate_state = gate.state(agent_id)

    blockers = [e.payload.get("blocker") for e in events if e.kind == "blocker_raised"]
    executed = [e for e in events if e.kind == "action_executed"]
    last_action = executed[-1].payload.get("action") if executed else None

    cost_usd = sum(
        float(e.payload.get("cost_usd", 0.0)) for e in events if e.kind == "cost_recorded"
    )
    tokens = sum(
        int(e.payload.get("tokens", 0)) for e in events if e.kind == "cost_recorded"
    )

    if gate_state == KILLED:
        status = "killed"
    elif gate_state == PAUSED:
        status = "paused"
    elif gate_state == AWAITING:
        status = "awaiting_approval"
    elif blockers:
        status = "blocked"
    else:
        status = "running"

    return {
        "agent_id": agent_id,
        "status": status,
        "last_action": last_action,
        "blockers": blockers,
        "drift": [f.as_dict() for f in detect_drift(stream, agent_id, budget_usd=budget_usd)],
        "cost_usd": round(cost_usd, 6),
        "cost_basis": "metered_estimate",
        "budget_usd": budget_usd,
        "tokens": tokens,
        "event_count": len(events),
        "recent": [e.as_dict() for e in events[-recent_n:]],
    }
