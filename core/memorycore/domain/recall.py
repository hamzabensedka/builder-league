"""Recall: scope-gated retrieval that says how sure it is.

Not vector RAG. Retrieval is keyword/slot matching over scoped facts, ranked
by relevance x effective (decayed) confidence, and it returns a RELIANCE
RECEIPT: the facts it is relying on, a calibrated aggregate confidence, and
the gaps it could not fill. Below ACT_THRESHOLD the honest answer is
"I'm not sure" — the caller asks or hedges instead of acting confident.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime

from core.memorycore.domain.facts import Fact
from core.memorycore.domain.forgetting import ForgetReason

# Below this calibrated confidence the agent must say it might be wrong.
ACT_THRESHOLD = 0.55

# A single fact must clear this to be relied on at all.
RELY_FLOOR = 0.25

_TOKEN_RE = re.compile(r"[a-z0-9_.]+")


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.lower()))


@dataclass(frozen=True)
class RecallResult:
    query: str
    facts: tuple[Fact, ...]
    calibrated_confidence: float
    gaps: tuple[str, ...] = field(default_factory=tuple)
    sure: bool = False

    def reliance_receipt(self, now: datetime) -> dict:
        """What the agent is relying on and how sure it is — the receipt the
        brief demands retrieval must show."""
        return {
            "query": self.query,
            "sure": self.sure,
            "calibrated_confidence": round(self.calibrated_confidence, 4),
            "relied_on": [
                {
                    "fact_id": f.id,
                    "slot": f.slot,
                    "value": f.value,
                    "source": f.provenance.source,
                    "source_kind": str(f.provenance.kind),
                    "effective_confidence": round(f.effective_confidence(now), 4),
                }
                for f in self.facts
            ],
            "gaps": list(self.gaps),
        }


def _scope_ok(fact: Fact, *, user_id: str, agent_id: str, task_id: str | None) -> bool:
    """Privacy gate: user isolation always; task-scoped facts never leak into
    another task's recall."""
    if fact.user_id != user_id or fact.agent_id != agent_id:
        return False
    return fact.task_id is None or fact.task_id == task_id


def _fact_tokens(fact: Fact) -> set[str]:
    """Matchable tokens for a fact: slot LEAF terms + value tokens. The
    'user'/'agent' prefix of a slot is scope, not content — matching on it
    would make every user-scoped fact spuriously relevant to every query."""
    slot_leaf = fact.slot.split(".")[-1]
    return _tokens(f"{slot_leaf.replace('_', ' ')} {fact.value}")


def _relevance(fact: Fact, query_tokens: set[str]) -> float:
    fact_tokens = _fact_tokens(fact)
    if not fact_tokens:
        return 0.0
    overlap = len(query_tokens & fact_tokens)
    if overlap == 0:
        return 0.0
    # Jaccard-ish, biased to coverage of the fact's slot terms
    return overlap / len(query_tokens | fact_tokens) + overlap / (2 * len(fact_tokens))


def calibrated_confidence(facts: list[Fact] | tuple[Fact, ...], *, now: datetime) -> float:
    """Aggregate reliance confidence. The chain is only as strong as its
    weakest relied-on link — overconfidence comes from aggregating generously,
    so we don't."""
    if not facts:
        return 0.0
    return min(f.effective_confidence(now) for f in facts)


def recall(
    facts: list[Fact],
    *,
    query: str,
    user_id: str,
    agent_id: str,
    task_id: str | None = None,
    now: datetime,
    tombstones: dict[str, ForgetReason] | None = None,
    limit: int = 5,
) -> RecallResult:
    """Scope gate -> match -> rank -> calibrate. Pure and deterministic."""
    forgotten = tombstones or {}
    candidates = [
        f
        for f in facts
        if f.id not in forgotten and _scope_ok(f, user_id=user_id, agent_id=agent_id,
                                               task_id=task_id)
    ]
    query_tokens = _tokens(query)
    scored = []
    for f in candidates:
        rel = _relevance(f, query_tokens)
        conf = f.effective_confidence(now)
        if rel > 0.0 and conf >= RELY_FLOOR:
            scored.append((rel * conf, f.id, f))
    scored.sort(key=lambda t: (-t[0], t[1]))  # deterministic tiebreak by id
    ranked = tuple(f for _, _, f in scored[:limit])

    calibrated = calibrated_confidence(ranked, now=now)
    gaps: tuple[str, ...] = ()
    if not ranked:
        gaps = (f"nothing remembered matching '{query}' in this scope",)
    elif calibrated < ACT_THRESHOLD:
        gaps = tuple(
            f"low confidence in '{f.slot}' = '{f.value}' "
            f"({f.effective_confidence(now):.2f}) — corroboration needed"
            for f in ranked
            if f.effective_confidence(now) < ACT_THRESHOLD
        )
    return RecallResult(
        query=query,
        facts=ranked,
        calibrated_confidence=calibrated,
        gaps=gaps,
        sure=bool(ranked) and calibrated >= ACT_THRESHOLD,
    )
