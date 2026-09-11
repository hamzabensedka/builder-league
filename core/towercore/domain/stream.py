"""EventStream — the append-only spine of the control plane.

One ordered log of every agent fact. Registry state, cost totals, and the
operator UI are all folds over this log; there is no second source of truth.
Append-only by design: no update/delete surface exists.

Per-agent sequence numbers are enforced contiguous (a gap means a lost event,
which an audit log must never silently accept) — fail-closed like the rest of
the codebase.
"""

from collections.abc import Callable

from core.towercore.domain.events import AgentEvent


class EventStream:
    def __init__(self) -> None:
        self._events: list[AgentEvent] = []
        self._next_seq: dict[str, int] = {}  # agent_id -> expected next seq
        self._subscribers: list[Callable[[AgentEvent], None]] = []

    # --- write path -----------------------------------------------------------

    def append(self, event: AgentEvent) -> None:
        """Append one event. Enforces per-agent contiguous sequencing."""
        expected = self._next_seq.get(event.agent_id, 1)
        if event.seq != expected:
            raise ValueError(
                f"seq gap for agent {event.agent_id}: expected {expected}, "
                f"got {event.seq} — an audit log must not skip events"
            )
        self._events.append(event)
        self._next_seq[event.agent_id] = expected + 1
        for sub in list(self._subscribers):
            try:
                sub(event)
            except Exception:  # noqa: S112 — a bad consumer must not corrupt the log
                continue

    def next_seq(self, agent_id: str) -> int:
        return self._next_seq.get(agent_id, 1)

    # --- read path ------------------------------------------------------------

    def all(self) -> list[AgentEvent]:
        return list(self._events)

    def for_agent(self, agent_id: str) -> list[AgentEvent]:
        return [e for e in self._events if e.agent_id == agent_id]

    def tail(self, agent_id: str, n: int) -> list[AgentEvent]:
        """Last n events for an agent, oldest-first — the replay source."""
        return self.for_agent(agent_id)[-n:] if n > 0 else []

    def export(self) -> list[dict]:
        """Canonical dicts in append order — the audit export payload."""
        return [e.as_dict() for e in self._events]

    # --- fan-out --------------------------------------------------------------

    def subscribe(self, callback: Callable[[AgentEvent], None]) -> Callable[[], None]:
        """Register a live consumer (SSE fan-out). New events only — history
        is read via for_agent/tail, never replayed into subscribers."""
        self._subscribers.append(callback)

        def unsubscribe() -> None:
            if callback in self._subscribers:
                self._subscribers.remove(callback)

        return unsubscribe
