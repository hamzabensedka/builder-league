"""Replay — the last N events of an agent folded into readable trace lines.

Each line carries the raw seq + payload so the operator can cross-reference
the audit export; the text is a deterministic rendering of the event, never
a paraphrase that could hide what actually happened.
"""

from typing import Any

from core.towercore.domain.events import AgentEvent
from core.towercore.domain.stream import EventStream


def replay(stream: EventStream, agent_id: str, n: int) -> list[dict[str, Any]]:
    return [_line(e) for e in stream.tail(agent_id, n)]


def _line(e: AgentEvent) -> dict[str, Any]:
    p = e.payload
    text = {
        "step_started": f"started step: {p.get('step', '?')}",
        "decision_requested": (
            f"requested decision {p.get('domain', '?')}.{p.get('action', '?')}"
        ),
        "action_executed": f"executed {p.get('action', '?')}",
        "action_denied": f"DENIED {p.get('action', '?')} — {p.get('reason', 'unspecified')}",
        "blocker_raised": f"blocked: {p.get('blocker', '?')}",
        "drift_flagged": f"drift detected: {p.get('summary', p.get('kind', '?'))}",
        "cost_recorded": (
            f"cost +${p.get('cost_usd', 0):.4f} on {p.get('task', '?')}"
        ),
        "approval_requested": (
            f"parked for approval: {p.get('action', '?')} (${p.get('amount')}) — {p.get('reason')}"
        ),
        "approval_resolved": f"approval {p.get('status', '?')} by {p.get('operator', '?')}",
        "intervention_applied": (
            f"operator {p.get('operator', '?')} applied {p.get('intervention', '?')}"
        ),
    }.get(e.kind, e.kind)
    return {"seq": e.seq, "kind": e.kind, "ts": e.ts, "text": text, "payload": p}
