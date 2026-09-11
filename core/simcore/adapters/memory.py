"""In-memory adapters for SimCore ports.

Same pattern as TrustCore's adapters: thread-locked, append-only stores so
the clean-clone run needs zero external services. Swapping to SQLite later
touches only this module.
"""

import threading

from core.simcore.domain.ledger import BudgetLedger


class InMemoryLedgerStore:
    """Holds THE BudgetLedger (single shared budget for the demo).

    Append-only by proxy: the ledger itself has no update/delete."""

    def __init__(self, ledger: BudgetLedger | None = None) -> None:
        self._ledger = ledger or BudgetLedger()
        self._lock = threading.Lock()

    def get(self) -> BudgetLedger:
        return self._ledger

    def reset(self, ledger: BudgetLedger) -> None:
        with self._lock:
            self._ledger = ledger


class InMemorySimulationStore:
    """Append-only simulation records keyed by id."""

    def __init__(self) -> None:
        self._sims: dict[str, dict] = {}
        self._order: list[str] = []
        self._lock = threading.Lock()

    def save(self, sim: dict) -> None:
        with self._lock:
            if sim["id"] not in self._sims:
                self._order.append(sim["id"])
            self._sims[sim["id"]] = sim

    def get(self, sim_id: str) -> dict | None:
        return self._sims.get(sim_id)

    def list(self, *, limit: int = 50) -> list[dict]:
        return [self._sims[i] for i in self._order[-limit:]][::-1]
