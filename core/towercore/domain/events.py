"""Typed agent events — the atoms of the control plane.

Every agent action, denial, cost entry, drift flag, and human intervention is
one AgentEvent in a single append-only stream. The registry, cost meter, and
operator UI are all views folded over this log, so the UI can never show state
the control plane didn't see.

Pure domain: no I/O, no frameworks. Fail-closed: malformed events are rejected
at construction, never silently absorbed.
"""

from dataclasses import dataclass
from typing import Any

EVENT_KINDS = (
    "step_started",
    "decision_requested",
    "action_executed",
    "action_denied",
    "blocker_raised",
    "drift_flagged",
    "cost_recorded",
    "approval_requested",
    "approval_resolved",
    "intervention_applied",
)


@dataclass(frozen=True)
class AgentEvent:
    """One immutable fact in the agent's operational history."""

    agent_id: str
    run_id: str
    seq: int  # per-agent monotonically increasing, 1-based
    ts: str  # ISO-8601 timestamp (injected clock; domain never reads wall time)
    kind: str
    payload: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        """Canonical serialization: stable key set, same shape for every kind."""
        return {
            "agent_id": self.agent_id,
            "run_id": self.run_id,
            "seq": self.seq,
            "ts": self.ts,
            "kind": self.kind,
            "payload": self.payload,
        }


def make_event(
    *,
    agent_id: str,
    run_id: str,
    seq: int,
    ts: str,
    kind: str,
    payload: dict[str, Any],
) -> AgentEvent:
    """Fail-closed constructor: anything malformed raises, nothing is coerced."""
    if not agent_id or not run_id:
        raise ValueError("event requires non-empty agent_id and run_id")
    if kind not in EVENT_KINDS:
        raise ValueError(f"unknown event kind {kind!r}; known: {sorted(EVENT_KINDS)}")
    if seq < 1:
        raise ValueError(f"seq must be >= 1, got {seq}")
    if not isinstance(payload, dict):
        raise ValueError("payload must be a dict")
    return AgentEvent(agent_id=agent_id, run_id=run_id, seq=seq, ts=ts, kind=kind,
                      payload=payload)
