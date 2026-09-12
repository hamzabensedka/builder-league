"""Ports the ambient application depends on. Adapters implement these.

The narrator port is the ONLY LLM seam: it writes the card's one-line
rationale and nothing else. The inference fold, ranking, and every state
change are deterministic domain/service code.
"""

from datetime import datetime
from typing import Any, Protocol

from core.ambientcore.domain.card import DecisionCard


class CardStore(Protocol):
    """Append-only card history keyed by id."""

    def save(self, card: DecisionCard) -> None: ...
    def get(self, card_id: str) -> DecisionCard | None: ...
    def all(self) -> list[DecisionCard]: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


class NarratorPort(Protocol):
    """Propose-only: returns (rationale_line, brain_label);
    brain in {"llm", "scripted"}. Never raises — degrades to scripted."""

    def narrate(self, hypothesis: dict[str, Any]) -> tuple[str, str]: ...
