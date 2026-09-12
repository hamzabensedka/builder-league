"""DecisionCard — the single thing the canvas shows when it shows anything.

Immutable value object with a fail-closed lifecycle:

    surfaced -> approved | edited | rejected | manual

- approved: the human accepted; the service executes through the real cores.
- edited:   the human re-parametrized the proposed action (audit keeps both).
- rejected: the guess was wrong; the service records a correction (MemoryCore)
            that demotes this intent kind on the next fold.
- manual:   the interface stops guessing (repeated corrections) and hands the
            raw evidence to the human.

No I/O, no LLM. Transitions return NEW cards; illegal transitions raise.
"""

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

from core.ambientcore.domain.intents import IntentHypothesis

CARD_STATES = frozenset({"surfaced", "approved", "edited", "rejected", "manual"})

# legal transitions: surfaced -> any terminal-ish state; nothing leaves them
_LEGAL = {
    "surfaced": {"approved", "edited", "rejected", "manual"},
    "approved": set(),
    "edited": set(),
    "rejected": set(),
    "manual": set(),
}


@dataclass(frozen=True)
class DecisionCard:
    id: str
    hypothesis: IntentHypothesis
    state: str
    rationale: str  # one line; narrator output, parsed upstream
    brain: str  # "llm" | "scripted" — which narrator wrote the rationale
    action: dict[str, Any]
    original_action: dict[str, Any]
    sim: dict[str, Any] | None  # pre-computed SimCore diff + rollback preview
    operator: str | None
    resolution_note: str | None
    ts: str

    def __post_init__(self) -> None:
        if self.state not in CARD_STATES:
            raise ValueError(f"unknown card state {self.state!r}")

    # --- transitions (all return new cards; illegal ones raise) -------------

    def _transition(self, new_state: str, **changes: Any) -> "DecisionCard":
        if new_state not in _LEGAL[self.state]:
            raise ValueError(
                f"card {self.id} cannot go {self.state} -> {new_state}")
        return replace(self, state=new_state, **changes)

    def with_sim(self, sim: dict[str, Any]) -> "DecisionCard":
        """Attach the pre-computed SimCore diff (state unchanged)."""
        return replace(self, sim=sim)

    def approve(self, *, operator: str) -> "DecisionCard":
        return self._transition("approved", operator=operator,
                                ts=_now())

    def edit(self, *, operator: str, new_action: dict[str, Any]) -> "DecisionCard":
        if not new_action.get("action"):
            raise ValueError("edited action must keep an action name")
        return self._transition("edited", operator=operator, action=dict(new_action),
                                ts=_now())

    def reject(self, *, operator: str, note: str) -> "DecisionCard":
        if not note.strip():
            raise ValueError("reject requires a note — the correction IS the recovery")
        return self._transition("rejected", operator=operator,
                                resolution_note=note.strip()[:300], ts=_now())

    def to_manual(self, *, operator: str, note: str) -> "DecisionCard":
        return self._transition("manual", operator=operator,
                                resolution_note=note.strip()[:300] or "manual fallback",
                                ts=_now())

    # --- serialization --------------------------------------------------------

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "state": self.state,
            "rationale": self.rationale,
            "brain": self.brain,
            "hypothesis": self.hypothesis.as_dict(),
            "action": self.action,
            "original_action": self.original_action,
            "sim": self.sim,
            "operator": self.operator,
            "resolution_note": self.resolution_note,
            "ts": self.ts,
        }


def _now() -> str:
    return datetime.now(UTC).isoformat()


def make_card(
    *,
    hypothesis: IntentHypothesis,
    rationale: str,
    brain: str,
    card_id: str | None = None,
) -> DecisionCard:
    """Surface a hypothesis as a card. The id is deterministic per hypothesis
    so the same inference never double-surfaces under polling."""
    if card_id is None:
        card_id = f"card-{hashlib.sha256(hypothesis.id.encode()).hexdigest()[:10]}"
    return DecisionCard(
        id=card_id,
        hypothesis=hypothesis,
        state="surfaced",
        rationale=rationale.strip()[:300],
        brain=brain,
        action=dict(hypothesis.proposed_action),
        original_action=dict(hypothesis.proposed_action),
        sim=None,
        operator=None,
        resolution_note=None,
        ts=_now(),
    )
