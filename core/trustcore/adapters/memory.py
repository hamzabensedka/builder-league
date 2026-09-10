"""In-memory adapters implementing the application ports.

Used by tests and by the agents' demo harness. The HTTP server uses the same
ports, so swapping these for SQLite later touches only this layer.
"""

import threading
import uuid
from datetime import UTC, datetime
from typing import Any

from core.trustcore.application.ports import Receipt
from core.trustcore.domain.credentials import Credential


class InMemoryAgentRegistry:
    def __init__(self) -> None:
        self._agents: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def register(self, *, name: str, public_key: str, owner: str) -> str:
        with self._lock:
            agent_id = str(uuid.uuid4())
            self._agents[agent_id] = {
                "id": agent_id,
                "name": name,
                "public_key": public_key,
                "owner": owner,
            }
            return agent_id

    def get_public_key(self, agent_id: str) -> str | None:
        agent = self._agents.get(agent_id)
        return agent["public_key"] if agent else None

    def find_by_key(self, public_key: str) -> str | None:
        for agent_id, agent in self._agents.items():
            if agent["public_key"] == public_key:
                return agent_id
        return None

    def list_agents(self) -> list[dict[str, Any]]:
        return list(self._agents.values())


class InMemoryCredentialStore:
    def __init__(self) -> None:
        self._creds: dict[str, Credential] = {}
        self._lock = threading.Lock()

    def save(self, credential: Credential) -> None:
        with self._lock:
            self._creds[credential.id] = credential

    def get(self, credential_id: str) -> Credential | None:
        return self._creds.get(credential_id)

    def for_subject(self, subject_key: str) -> list[Credential]:
        return [c for c in self._creds.values() if c.subject_key == subject_key]

    def mark_revoked(self, credential_id: str, *, at: datetime, reason: str) -> None:
        from dataclasses import replace

        with self._lock:
            cred = self._creds[credential_id]
            self._creds[credential_id] = replace(cred, revoked_at=at, revocation_reason=reason)


class InMemoryReceiptLog:
    """Append-only: there is deliberately no update or delete method."""

    def __init__(self) -> None:
        self._receipts: list[Receipt] = []
        self._lock = threading.Lock()

    def append(self, receipt: Receipt) -> None:
        with self._lock:
            self._receipts.append(receipt)

    def list(self, *, limit: int = 50) -> list[Receipt]:
        return self._receipts[-limit:][::-1]


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)
