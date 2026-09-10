"""Ports: protocols the application layer depends on. Adapters implement these.

Dependency inversion: application services receive these via constructor
injection and never import adapter modules (enforced by import-linter).
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from core.trustcore.domain.credentials import Credential
from core.trustcore.domain.policy import PolicyDecision


@dataclass(frozen=True)
class Receipt:
    """Machine-readable audit record for one decision. Append-only by design."""

    id: str
    ts: datetime
    agent_id: str
    action: str
    inputs: dict[str, Any]
    signals: dict[str, Any]
    decision: PolicyDecision
    reasoning: str
    llm_called: bool = False
    tokens: int = 0
    cost_usd: float = 0.0


class AgentRegistry(Protocol):
    def register(self, *, name: str, public_key: str, owner: str) -> str: ...
    def get_public_key(self, agent_id: str) -> str | None: ...
    def find_by_key(self, public_key: str) -> str | None: ...
    def list_agents(self) -> list[dict[str, Any]]: ...


class CredentialStore(Protocol):
    def save(self, credential: Credential) -> None: ...
    def get(self, credential_id: str) -> Credential | None: ...
    def for_subject(self, subject_key: str) -> list[Credential]: ...
    def mark_revoked(self, credential_id: str, *, at: datetime, reason: str) -> None: ...


class ReceiptLog(Protocol):
    """Append-only. Implementations MUST NOT expose update/delete."""

    def append(self, receipt: Receipt) -> None: ...
    def list(self, *, limit: int = 50) -> list[Receipt]: ...


class Clock(Protocol):
    def now(self) -> datetime: ...
