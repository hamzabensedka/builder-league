"""Contradiction resolution: what happens when two facts claim the same slot.

Deterministic policy, fully inspectable:
- same value               -> CORROBORATE (existing fact gets a boost)
- decisive margin          -> SUPERSEDE (incoming wins) or REJECT_INCOMING
- near-equal confidence    -> CONTRADICTION (BOTH flagged, neither trusted)

"Near-equal" is deliberate: when memory can't tell which of two claims is
right, the honest answer is to trust neither — that is the whole challenge.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from core.memorycore.domain.facts import Fact

# Confidence margin below which neither fact is trusted.
DECISIVE_MARGIN = 0.15


class ConflictOutcome(Enum):
    CORROBORATE = "corroborate"
    SUPERSEDE = "supersede"
    REJECT_INCOMING = "reject_incoming"
    CONTRADICTION = "contradiction"

    def __str__(self) -> str:  # pragma: no cover - convenience
        return self.value


@dataclass(frozen=True)
class ConflictResolution:
    outcome: ConflictOutcome
    winner_id: str | None = None
    loser_id: str | None = None  # tombstoned with reason superseded/contradicted
    flagged_ids: tuple[str, ...] = field(default_factory=tuple)  # both, on CONTRADICTION
    reason: str = ""


def resolve_conflict(*, existing: Fact, incoming: Fact, now: datetime) -> ConflictResolution:
    """Resolve two facts claiming the same slot (same user + agent scope)."""
    if existing.slot != incoming.slot:
        raise ValueError("conflict requires same slot")
    if existing.value.lower() == incoming.value.lower():
        return ConflictResolution(
            outcome=ConflictOutcome.CORROBORATE,
            winner_id=existing.id,
            reason="same value from an independent sighting corroborates the fact",
        )

    existing_conf = existing.effective_confidence(now)
    incoming_conf = incoming.effective_confidence(now)
    margin = abs(incoming_conf - existing_conf)

    if margin < DECISIVE_MARGIN:
        return ConflictResolution(
            outcome=ConflictOutcome.CONTRADICTION,
            flagged_ids=(existing.id, incoming.id),
            reason=(
                f"conflicting values for '{existing.slot}' at near-equal confidence "
                f"({existing_conf:.2f} vs {incoming_conf:.2f}) — neither is trusted"
            ),
        )

    if incoming_conf > existing_conf:
        return ConflictResolution(
            outcome=ConflictOutcome.SUPERSEDE,
            winner_id=incoming.id,
            loser_id=existing.id,
            reason=(
                f"incoming '{incoming.value}' ({incoming_conf:.2f}) decisively beats "
                f"remembered '{existing.value}' ({existing_conf:.2f})"
            ),
        )

    return ConflictResolution(
        outcome=ConflictOutcome.REJECT_INCOMING,
        winner_id=existing.id,
        loser_id=incoming.id,
        reason=(
            f"remembered '{existing.value}' ({existing_conf:.2f}) decisively beats "
            f"incoming '{incoming.value}' ({incoming_conf:.2f}) — incoming not stored"
        ),
    )
