"""Forgetting: explicit, receipted, and cascading.

Three explicit triggers, matching the brief:
- stale:        TTL expired, or decayed below the usefulness floor
- contradicted: lost a same-slot conflict (or flagged in a tie)
- revoked:      the user signed a forget request (privacy)

Forgetting is a TOMBSTONE, not a delete: the fact id, reason, and time are
kept forever so retrieval can explain "I used to know this, and here's why I
stopped relying on it". Revocation cascades to derived facts — if you forget
my city, you must also forget the timezone you inferred from it.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from core.memorycore.domain.facts import Fact

# Below this effective confidence a fact is dead weight: retrieval would only
# be misled by it. Deterministic floor for the staleness sweeper.
USEFULNESS_FLOOR = 0.20


class ForgetReason(Enum):
    STALE = "stale"
    CONTRADICTED = "contradicted"
    SUPERSEDED = "superseded"
    REVOKED = "revoked"

    def __str__(self) -> str:  # pragma: no cover - convenience
        return self.value


@dataclass(frozen=True)
class Tombstone:
    fact_id: str
    slot: str
    value: str
    reason: ForgetReason
    forgotten_at: datetime
    detail: str = ""

    def as_dict(self) -> dict:
        return {
            "fact_id": self.fact_id,
            "slot": self.slot,
            "value": self.value,
            "reason": str(self.reason),
            "forgotten_at": self.forgotten_at.isoformat(),
            "detail": self.detail,
        }


def stale_facts(facts: list[Fact], *, now: datetime) -> list[Fact]:
    """Facts past TTL or decayed below the usefulness floor."""
    return [
        f
        for f in facts
        if f.is_expired(now) or f.effective_confidence(now) < USEFULNESS_FLOOR
    ]


def cascaded_forgets(root_fact_id: str, facts: list[Fact]) -> set[str]:
    """The root plus every fact derived from it, transitively. A revoked fact
    poisons its whole derivation subtree — privacy is not negotiable halfway."""
    by_parent: dict[str, list[str]] = {}
    for f in facts:
        for parent in f.derived_from:
            by_parent.setdefault(parent, []).append(f.id)
    doomed = {root_fact_id}
    frontier = [root_fact_id]
    while frontier:
        current = frontier.pop()
        for child in by_parent.get(current, []):
            if child not in doomed:
                doomed.add(child)
                frontier.append(child)
    return doomed
