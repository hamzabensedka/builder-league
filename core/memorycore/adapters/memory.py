"""In-memory adapters for MemoryCore. Consistent with the repo convention:
zero infra, clean clone runs; the store is append-only by construction (facts
are immutable value objects; forgetting is a separate tombstone log).
"""

from datetime import UTC, datetime

from core.memorycore.domain.facts import Fact
from core.memorycore.domain.forgetting import Tombstone


class InMemoryMemoryStore:
    def __init__(self) -> None:
        self._facts: dict[str, Fact] = {}

    def save(self, fact: Fact) -> None:
        # corroboration/supersession writes a NEW Fact version under the same
        # id — there is no in-place mutation of fields
        self._facts[fact.id] = fact

    def get(self, fact_id: str) -> Fact | None:
        return self._facts.get(fact_id)

    def all(self) -> list[Fact]:
        return list(self._facts.values())

    def by_slot(self, *, user_id: str, agent_id: str, slot: str) -> list[Fact]:
        return [
            f
            for f in self._facts.values()
            if f.user_id == user_id and f.agent_id == agent_id and f.slot == slot
        ]

    def reset(self) -> None:
        """Clear all facts for a fresh demo seed."""
        self._facts.clear()


class InMemoryTombstoneLog:
    def __init__(self) -> None:
        self._entries: list[Tombstone] = []

    def append(self, tombstone: Tombstone) -> None:
        self._entries.append(tombstone)

    def list(self, limit: int = 100) -> list[Tombstone]:
        return self._entries[-limit:][::-1]  # newest first

    def reasons(self) -> dict[str, str]:
        return {t.fact_id: str(t.reason) for t in self._entries}

    def reset(self) -> None:
        """Clear all tombstones for a fresh demo seed."""
        self._entries.clear()


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class ManualClock:
    """Deterministic clock for tests and the scripted demo: time only moves
    when the scenario says so, so staleness is a deliberate beat, not a race."""

    def __init__(self, start: datetime) -> None:
        self._now = start

    def now(self) -> datetime:
        return self._now

    def advance(self, *, days: int = 0, hours: int = 0) -> datetime:
        from datetime import timedelta

        self._now = self._now + timedelta(days=days, hours=hours)
        return self._now
