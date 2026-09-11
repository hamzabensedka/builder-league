"""The world event stream — event-driven inputs, not polled snapshots.

Pure domain. Events are append-only records with stream positions; runs
consume them via a persisted cursor. World-changing events carry REAL side
effects (applied by the application layer through SimCore/TrustCore) and
record those effects in `applied_effects` so the trace shows what actually
changed, not just what was announced.
"""

import uuid
from dataclasses import dataclass, field
from typing import Any

EVENT_KINDS = [
    "price_changed",
    "supplier_unavailable",
    "hold_placed",
    "hold_released",
    "authority_revoked",
    "delivery_delayed",
]


@dataclass(frozen=True)
class WorldEvent:
    id: str
    ts: str  # ISO timestamp
    seq: int  # stream position, monotonically increasing
    kind: str  # one of EVENT_KINDS
    payload: dict[str, Any]
    applied_effects: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.kind not in EVENT_KINDS:
            raise ValueError(f"unknown event kind {self.kind!r}")

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "ts": self.ts,
            "seq": self.seq,
            "kind": self.kind,
            "payload": self.payload,
            "applied_effects": list(self.applied_effects),
        }


def make_event(*, seq: int, ts: str, kind: str, payload: dict[str, Any],
               applied_effects: list[str] | None = None) -> WorldEvent:
    return WorldEvent(
        id=str(uuid.uuid4()),
        ts=ts,
        seq=seq,
        kind=kind,
        payload=payload,
        applied_effects=applied_effects or [],
    )


def new_events(events: list[WorldEvent], cursor: int) -> list[WorldEvent]:
    """Events the run has not yet observed (strictly after the cursor)."""
    return [e for e in events if e.seq > cursor]


def advance_cursor(events: list[WorldEvent], cursor: int) -> int:
    """Move the cursor to the latest observed event position."""
    seen = new_events(events, cursor)
    if not seen:
        return cursor
    return max(e.seq for e in seen)
