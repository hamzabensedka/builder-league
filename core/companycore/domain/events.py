"""Typed company events: the one shared record every role writes to."""

import uuid
from dataclasses import dataclass, field
from typing import Any

EVENT_KINDS = frozenset({
    "lead_arrived", "quote_sent", "deal_won", "deal_lost", "invoice_issued",
    "invoice_collected", "po_raised", "po_received", "bill_received",
    "bill_paid", "spend_frozen", "spend_unfrozen", "escalation_raised",
    "escalation_resolved", "directive_proposed", "directive_applied",
    "directive_rejected", "role_paused", "role_restored", "day_ticked",
})


@dataclass(frozen=True)
class CompanyEvent:
    id: str
    day: int
    seq: int
    actor: str
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "day": self.day, "seq": self.seq,
                "actor": self.actor, "kind": self.kind, "payload": self.payload}


def make_event(*, day: int, seq: int, actor: str, kind: str,
               payload: dict[str, Any] | None = None) -> CompanyEvent:
    """Fail-closed constructor: unknown kind, empty actor, or bad numbers raise."""
    if kind not in EVENT_KINDS:
        raise ValueError(f"unknown event kind {kind!r}")
    if not actor:
        raise ValueError("actor must be non-empty")
    if day < 0 or seq < 0:
        raise ValueError("day and seq must be >= 0")
    return CompanyEvent(id=str(uuid.uuid4()), day=day, seq=seq, actor=actor,
                        kind=kind, payload=payload or {})
