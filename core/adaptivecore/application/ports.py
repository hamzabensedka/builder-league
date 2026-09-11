"""Ports: protocols the AdaptiveCore application layer depends on.

Dependency inversion: AdaptiveService receives these via constructor
injection and never imports adapter modules (import-linter enforced).
Composition, not duplication — budget effects flow through SimCore's
application surface, authority through TrustCore, step gating through
DecisionCore, audit through TrustCore's append-only log.
"""

from typing import Any, Protocol


class RunStore(Protocol):
    """Append-only run records. save() upserts by id (status/step-log progress);
    there is no delete."""

    def save(self, record: dict[str, Any]) -> None: ...
    def get(self, run_id: str) -> dict[str, Any] | None: ...
    def list(self, *, limit: int = 50) -> list[dict[str, Any]]: ...


class PlanStore(Protocol):
    """Append-only plan VERSIONS. save() adds; existing versions never change."""

    def save(self, plan: Any) -> None: ...  # -> domain Plan
    def get(self, plan_id: str) -> Any | None: ...
    def for_run(self, run_id: str) -> list[Any]: ...


class EventStream(Protocol):
    """Append-only world event stream."""

    def append(self, event: Any) -> None: ...  # -> domain WorldEvent
    def all(self) -> list[Any]: ...
    def next_seq(self) -> int: ...


class WorldStore(Protocol):
    """The supplier world (prices/availability/delivery)."""

    def get(self) -> dict[str, Any]: ...
    def set_supplier(self, name: str, **fields: Any) -> None: ...


class BudgetPort(Protocol):
    """SimCore's application surface — real shared budget state."""

    def committed(self) -> float: ...        # spent + active holds
    def limit(self) -> float: ...
    def place_hold(self, *, agent_key: str, amount: float, reference: str) -> dict[str, Any]: ...
    def release_hold(self, *, amount: float, reference: str) -> dict[str, Any]: ...
    def spend(self, *, agent_key: str, amount: float, reference: str) -> dict[str, Any]: ...
    def refund(self, *, compensates: str, agent_key: str, reference: str) -> dict[str, Any]: ...
    def invariant_ok(self) -> tuple[bool, list[dict[str, Any]]]: ...


class AuthorityPort(Protocol):
    """TrustCore's application surface — real credential state."""

    def authority_valid(self, *, agent_key: str, action: str) -> bool: ...
    def revoke_authority(self, *, agent_key: str, action: str, reason: str) -> str | None: ...
    def decide_purchase(self, *, requester_key: str, amount: float,
                        description: str) -> dict[str, Any]: ...  # {decision, receipt_id}


class StepGate(Protocol):
    """DecisionCore's decide() — every (re-)planned step is gated."""

    def decide(self, *, domain: str, action: str, actor_key: str,
               amount: float | None, context: dict[str, Any]) -> dict[str, Any]: ...


class StepPreview(Protocol):
    """SimCore's simulate() — a revised purchase is previewed on a fork first."""

    def simulate(self, *, requester_key: str, amount: float,
                 description: str) -> dict[str, Any]: ...


class AuditTrail(Protocol):
    """The shared append-only receipt log (TrustCore's)."""

    def record_event(self, *, actor: str, action: str, note: str,
                     inputs: dict[str, Any] | None = None, decision: Any = None) -> Any: ...
