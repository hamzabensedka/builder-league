"""In-memory adapters for DecisionCore ports.

Same pattern as TrustCore/SimCore: thread-locked, append-only stores so the
clean-clone run needs zero external services. Swapping to SQLite later
touches only this module.
"""

import threading
from typing import Any


class InMemoryDecisionStore:
    """Append-only decision records keyed by id. Deliberately no update/delete."""

    def __init__(self) -> None:
        self._records: dict[str, dict[str, Any]] = {}
        self._order: list[str] = []
        self._lock = threading.Lock()

    def append(self, record: dict[str, Any]) -> None:
        with self._lock:
            if record["id"] not in self._order:
                self._order.append(record["id"])
            self._records[record["id"]] = record

    def get(self, decision_id: str) -> dict[str, Any] | None:
        return self._records.get(decision_id)

    def list(self, *, limit: int = 50) -> list[dict[str, Any]]:
        return [self._records[i] for i in self._order[-limit:]][::-1]
