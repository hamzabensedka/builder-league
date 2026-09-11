"""Ports for MemoryCore: storage and audit, defined by the application layer.

Mirrors the repo's hexagonal convention: the service depends on these
protocols; adapters (in-memory for the demo) implement them.
"""

from typing import Protocol

from core.memorycore.domain.facts import Fact
from core.memorycore.domain.forgetting import Tombstone


class MemoryStore(Protocol):
    """Facts are never updated in place and never deleted: corroboration and
    supersession write NEW versions; forgetting writes tombstones. The store
    is effectively append-only, like the TrustCore receipt log."""

    def save(self, fact: Fact) -> None: ...
    def get(self, fact_id: str) -> Fact | None: ...
    def all(self) -> list[Fact]: ...
    def by_slot(self, *, user_id: str, agent_id: str, slot: str) -> list[Fact]: ...


class TombstoneLog(Protocol):
    """Append-only record of forgetting: what was forgotten, why, when."""

    def append(self, tombstone: Tombstone) -> None: ...
    def list(self, limit: int = 100) -> list[Tombstone]: ...
    def reasons(self) -> dict[str, str]: ...  # fact_id -> reason


class Clock(Protocol):
    def now(self): ...
