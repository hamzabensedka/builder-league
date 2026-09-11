"""Facts: the unit of memory. Pure domain — no I/O, no frameworks.

Every fact carries the four tags the brief demands:
- source: where it came from (provenance: user_stated / observed / inferred / imported)
- confidence: base_confidence = source trust x extraction confidence
- freshness: TTL + half-life decay (effective_confidence decays over time)
- scope: user / agent / task — who the fact may apply to

Facts are immutable value objects. Forgetting is a tombstone (see forgetting.py),
never a silent delete — the memory keeps the receipt of what it forgot and why.
"""

import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum


class SourceKind(Enum):
    """Where a fact came from. Trust is ordered: what the user told you
    outweighs what you saw, which outweighs what you guessed or bulk-imported."""

    USER_STATED = "user_stated"
    OBSERVED = "observed"
    INFERRED = "inferred"
    IMPORTED = "imported"

    def __str__(self) -> str:  # pragma: no cover - convenience
        return self.value


# How much a source kind is trusted, all else equal. Deterministic and
# inspectable — this table IS the model, there is no hidden scorer.
SOURCE_TRUST: dict[SourceKind, float] = {
    SourceKind.USER_STATED: 1.00,
    SourceKind.OBSERVED: 0.70,
    SourceKind.INFERRED: 0.50,
    SourceKind.IMPORTED: 0.40,
}

DEFAULT_HALF_LIFE_DAYS = 30


@dataclass(frozen=True)
class Provenance:
    source: str  # e.g. "user", "booking-email", "import:crm"
    kind: SourceKind
    extraction_confidence: float  # 0..1, how sure the extractor was

    def __post_init__(self) -> None:
        if not self.source:
            raise ValueError("provenance source required")
        if not 0.0 < self.extraction_confidence <= 1.0:
            raise ValueError("extraction_confidence must be in (0, 1]")


@dataclass(frozen=True)
class Fact:
    """One remembered claim about a slot, scoped, provenanced, decaying."""

    id: str
    slot: str  # e.g. "user.city", "user.seat_preference"
    value: str
    provenance: Provenance
    base_confidence: float  # SOURCE_TRUST[kind] x extraction_confidence, <= 1
    user_id: str
    agent_id: str
    task_id: str | None  # None = user-scope; set = visible only within that task
    learned_at: datetime
    expires_at: datetime | None  # TTL; None = decays but never hard-expires
    half_life_days: int
    corroborations: int = 0  # independent sightings of the same value
    derived_from: tuple[str, ...] = field(default_factory=tuple)

    def effective_confidence(self, now: datetime) -> float:
        return decayed_confidence(self, now)

    def is_expired(self, now: datetime) -> bool:
        return self.expires_at is not None and now >= self.expires_at

    def as_dict(self, now: datetime) -> dict:
        return {
            "id": self.id,
            "slot": self.slot,
            "value": self.value,
            "source": self.provenance.source,
            "source_kind": str(self.provenance.kind),
            "base_confidence": round(self.base_confidence, 4),
            "effective_confidence": round(self.effective_confidence(now), 4),
            "corroborations": self.corroborations,
            "scope": {
                "user_id": self.user_id,
                "agent_id": self.agent_id,
                "task_id": self.task_id,
            },
            "learned_at": self.learned_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "half_life_days": self.half_life_days,
            "derived_from": list(self.derived_from),
        }


def make_fact(
    *,
    slot: str,
    value: str,
    provenance: Provenance,
    user_id: str,
    agent_id: str,
    learned_at: datetime,
    task_id: str | None = None,
    ttl_days: int | None = None,
    half_life_days: int = DEFAULT_HALF_LIFE_DAYS,
    derived_from: tuple[str, ...] = (),
    corroborations: int = 0,
) -> Fact:
    """Fail-closed construction: a fact without slot/value/scope cannot exist."""
    if not slot.strip():
        raise ValueError("fact slot required")
    if not value.strip():
        raise ValueError("fact value required")
    if not user_id or not agent_id:
        raise ValueError("fact scope (user_id, agent_id) required")
    if half_life_days <= 0:
        raise ValueError("half_life_days must be positive")
    if ttl_days is not None and ttl_days <= 0:
        raise ValueError("ttl_days must be positive when set")
    base = min(1.0, SOURCE_TRUST[provenance.kind] * provenance.extraction_confidence)
    return Fact(
        id=str(uuid.uuid4()),
        slot=slot.strip(),
        value=value.strip(),
        provenance=provenance,
        base_confidence=base,
        user_id=user_id,
        agent_id=agent_id,
        task_id=task_id,
        learned_at=learned_at,
        expires_at=(learned_at + timedelta(days=ttl_days)) if ttl_days else None,
        half_life_days=half_life_days,
        corroborations=corroborations,
        derived_from=tuple(derived_from),
    )


def decayed_confidence(fact: Fact, now: datetime) -> float:
    """Effective confidence: exponential decay on base confidence, boosted by
    corroboration (each independent sighting recovers 10% of the distance to
    1.0, capped), hard-zero after TTL expiry.

    Deterministic: same fact + same clock reading -> same number, always."""
    if fact.is_expired(now):
        return 0.0
    age_days = (
        0.0
        if now <= fact.learned_at
        else (now - fact.learned_at).total_seconds() / 86400.0
    )
    decayed = fact.base_confidence * math.pow(0.5, age_days / fact.half_life_days)
    # corroboration boost: diminishing returns toward 1.0
    boosted = 1.0 - (1.0 - decayed) * math.pow(0.9, fact.corroborations)
    # floor at a tiny epsilon so a no-TTL fact never reads as exactly zero
    # (exact zero is reserved for TTL expiry — the only hard death)
    return max(1e-9, min(1.0, boosted))
