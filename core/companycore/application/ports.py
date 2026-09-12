"""Ports the company application depends on. Adapters implement these."""

from datetime import datetime
from typing import Any, Protocol

from core.companycore.domain.events import CompanyEvent


class EventStore(Protocol):
    def append(self, event: CompanyEvent) -> None: ...
    def all(self) -> list[CompanyEvent]: ...
    def tail(self, n: int) -> list[CompanyEvent]: ...
    def export(self) -> list[dict[str, Any]]: ...
    def next_seq(self) -> int: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


class LLMPort(Protocol):
    """The ONLY LLM seam. Returns (raw_text, brain_label); brain in {"llm","scripted"}."""

    def propose(self, snapshot: dict[str, Any]) -> tuple[str, str]: ...
