"""Human escalation inbox: ask/escalate outcomes park here, never execute silently."""

import uuid
from dataclasses import dataclass


@dataclass
class Escalation:
    id: str
    day: int
    actor: str
    summary: str
    detail: str
    resolved: bool = False
    resolution: str | None = None

    def as_dict(self) -> dict:
        return {"id": self.id, "day": self.day, "actor": self.actor,
                "summary": self.summary, "detail": self.detail,
                "resolved": self.resolved, "resolution": self.resolution}


class Inbox:
    def __init__(self) -> None:
        self._items: dict[str, Escalation] = {}

    def raise_escalation(self, *, id: str | None = None, day: int, actor: str,
                         summary: str, detail: str) -> Escalation:
        e = Escalation(id=id or str(uuid.uuid4()), day=day, actor=actor,
                       summary=summary, detail=detail)
        self._items[e.id] = e
        return e

    def resolve(self, id: str, resolution: str) -> Escalation:
        e = self._items.get(id)
        if e is None:
            raise ValueError(f"unknown escalation {id}")
        if e.resolved:
            raise ValueError(f"escalation {id} already resolved")
        e.resolved = True
        e.resolution = resolution
        return e

    def pending(self) -> list[Escalation]:
        return [e for e in self._items.values() if not e.resolved]

    def all(self) -> list[Escalation]:
        return list(self._items.values())
