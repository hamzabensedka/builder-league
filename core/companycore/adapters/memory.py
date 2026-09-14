"""In-memory adapters + the scripted LLM fallback (no network, deterministic)."""

from datetime import UTC, datetime
from typing import Any

from core.companycore.domain.events import CompanyEvent
from core.companycore.domain.log import EventLog


class InMemoryEventStore:
    def __init__(self) -> None:
        self._log = EventLog()

    def append(self, event: CompanyEvent) -> None:
        self._log.append(event)

    def all(self) -> list[CompanyEvent]:
        return self._log.all()

    def tail(self, n: int) -> list[CompanyEvent]:
        return self._log.tail(n)

    def export(self) -> list[dict[str, Any]]:
        return self._log.export()

    def next_seq(self) -> int:
        return self._log.next_seq()

    def reset(self) -> None:
        """Clear the spine for a fresh demo seed (re-seed starts a new run)."""
        self._log.reset()


class ManualClock:
    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime.now(UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, **kwargs: Any) -> None:
        from datetime import timedelta
        self._now = self._now + timedelta(**kwargs)


class ScriptedLLM:
    """Deterministic stand-in for the ChiefOfStaff: same snapshot in, same directive out."""

    def propose(self, snapshot: dict[str, Any]) -> tuple[str, str]:
        runway = snapshot.get("kpis", {}).get("runway_days", 99)
        if runway < 21:
            return ('{"action":"freeze_spend","target":"discretionary","amount_cap":null,'
                    f'"rationale":"runway {runway}d below 21d threshold"}}'), "scripted"
        return ('{"action":"none","target":"","amount_cap":null,'
                '"rationale":"company healthy; no intervention"}'), "scripted"
