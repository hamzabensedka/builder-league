"""In-memory adapters: card store, manual clock, and the scripted narrator
fallback (no network, deterministic — clean clones run fully offline)."""

import threading
from datetime import UTC, datetime
from typing import Any

from core.ambientcore.domain.card import DecisionCard


class InMemoryCardStore:
    """Append-only by proxy: cards are immutable values, save() replaces by id."""

    def __init__(self) -> None:
        self._cards: dict[str, DecisionCard] = {}
        self._order: list[str] = []
        self._lock = threading.Lock()

    def save(self, card: DecisionCard) -> None:
        with self._lock:
            if card.id not in self._cards:
                self._order.append(card.id)
            self._cards[card.id] = card

    def get(self, card_id: str) -> DecisionCard | None:
        return self._cards.get(card_id)

    def all(self) -> list[DecisionCard]:
        return [self._cards[i] for i in self._order]

    def reset(self) -> None:
        """Clear all cards for a fresh demo seed."""
        with self._lock:
            self._cards.clear()
            self._order.clear()


class ManualClock:
    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime.now(UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, **kwargs: Any) -> None:
        from datetime import timedelta
        self._now = self._now + timedelta(**kwargs)


_KIND_LINE = {
    "deploy_needs_review": "A deploy parked itself on your desk — diff already computed.",
    "drift_contain": "An agent drifted out of pattern; containment is one tap.",
    "restock_needed": "Stock is below threshold; the restock is pre-simulated.",
    "budget_risk": "Projected spend is closing on the enforced limit.",
}


class ScriptedNarrator:
    """Deterministic stand-in: same hypothesis in, same line out."""

    def narrate(self, hypothesis: dict[str, Any]) -> tuple[str, str]:
        kind = hypothesis.get("kind", "")
        line = _KIND_LINE.get(kind, "This looks like it needs a decision.")
        if hypothesis.get("demoted"):
            line = f"(lower confidence — you corrected this before) {line}"
        return line, "scripted"
