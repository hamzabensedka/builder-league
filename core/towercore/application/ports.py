"""Ports: protocols the TowerCore application layer depends on.

Dependency inversion, same as the other cores: TowerService receives these
via constructor injection and never imports adapter modules (import-linter
enforced). The event log itself lives in the domain (EventStream); the ports
here cover what genuinely varies: wall-clock time, live fan-out, and the
composition surfaces of the existing cores.
"""

from typing import Any, Protocol

from core.towercore.domain.events import AgentEvent


class Clock(Protocol):
    def now_iso(self) -> str: ...


class Notifier(Protocol):
    """Live fan-out for the SSE layer. The stream remains the source of
    truth; the notifier is a best-effort push to connected operators."""

    def publish(self, event: AgentEvent) -> None: ...


class AuthorityGate(Protocol):
    """TrustCore's public surface: signed-authority decisions + audit."""

    def decide(
        self, *, requester_key: str, action: str, amount: float | None, description: str = ""
    ) -> Any: ...  # -> trustcore Receipt

    def register_agent(self, *, name: str, public_key: str, owner: str) -> str: ...


class DecisionEngine(Protocol):
    """DecisionCore's public surface: domain-gated decide()."""

    def decide(
        self, *, domain: str, action: str, actor_key: str, amount: float | None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...


class SimulationGate(Protocol):
    """SimCore's public surface: simulate → execute against the real ledger."""

    def simulate(
        self, *, requester_key: str, amount: float, description: str
    ) -> dict[str, Any]: ...

    def execute(self, sim_id: str) -> dict[str, Any]: ...
