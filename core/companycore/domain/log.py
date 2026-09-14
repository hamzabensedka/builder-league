"""Append-only event log: the company spine. Seq is contiguous; a gap is an error."""

from core.companycore.domain.events import CompanyEvent


class EventLog:
    def __init__(self) -> None:
        self._events: list[CompanyEvent] = []

    def append(self, event: CompanyEvent) -> None:
        if event.seq != len(self._events):
            raise ValueError(
                f"seq gap: expected {len(self._events)}, got {event.seq}")
        self._events.append(event)

    def next_seq(self) -> int:
        return len(self._events)

    def all(self) -> list[CompanyEvent]:
        return list(self._events)

    def tail(self, n: int) -> list[CompanyEvent]:
        return self._events[-n:]

    def events_for_day(self, day: int) -> list[CompanyEvent]:
        return [e for e in self._events if e.day == day]

    def export(self) -> list[dict]:
        return [e.as_dict() for e in self._events]

    def reset(self) -> None:
        """Clear the log for a fresh demo seed (append-only per run)."""
        self._events.clear()
