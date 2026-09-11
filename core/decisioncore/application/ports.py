"""Ports: protocols the DecisionCore application layer depends on.

Dependency inversion: DecisionService receives these via constructor injection
and never imports adapter modules (enforced by import-linter). Composition,
not duplication — authority evidence comes from TrustCore through this port,
reversibility from the SimCore compensation pattern.
"""

from typing import Any, Protocol


class AuthorityVerifier(Protocol):
    """Read-only authority/identity evidence from TrustCore (C1).

    decide() runs the real signature + expiry + revocation + scope checks and
    appends its own receipt; we consume the verdict, never re-implement it."""

    def decide(
        self, *, requester_key: str, action: str, amount: float | None, description: str = ""
    ) -> Any: ...  # -> trustcore Receipt (decision, signals, reasoning)

    def trust_profile(self, *, subject_key: str) -> dict[str, Any]: ...

    def find_agent_id(self, public_key: str) -> str | None: ...


class HistoryReader(Protocol):
    """Past decision receipts for the history signal (append-only log, C1)."""

    def list_receipts(self, *, limit: int = 50) -> list[Any]: ...


class DecisionStore(Protocol):
    """Append-only store of DecisionRecords. No update/delete."""

    def append(self, record: dict[str, Any]) -> None: ...
    def get(self, decision_id: str) -> dict[str, Any] | None: ...
    def list(self, *, limit: int = 50) -> list[dict[str, Any]]: ...


class AuditTrail(Protocol):
    """The shared append-only receipt log (TrustCore's). Every decision leaves a receipt."""

    def record_event(
        self, *, actor: str, action: str, note: str, inputs: dict[str, Any] | None = None,
        decision: Any = None,
    ) -> Any: ...
