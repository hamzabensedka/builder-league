"""The ranker — the interface's whole job is deciding what NOT to show.

At most ONE hypothesis becomes a card. Kinds the operator has corrected twice
are exhausted: the interface stops guessing and degrades gracefully to a
manual view (raw evidence, human decides) instead of pushing a third wrong
card. Deterministic, LLM-free, fail-closed.
"""

from dataclasses import dataclass, field
from typing import Any

from core.ambientcore.domain.intents import IntentHypothesis

SURFACE_THRESHOLD = 0.55  # below this, a guess isn't worth the interruption
EXHAUSTION_LIMIT = 2      # corrections on one kind before manual fallback


@dataclass(frozen=True)
class RankVerdict:
    """What the canvas should render right now.

    mode: "card" (surface the hypothesis), "calm" (nothing needs a decision),
    or "manual" (stop guessing — show raw evidence and let the human decide).
    """

    mode: str
    hypothesis: IntentHypothesis | None = None
    exhausted_kinds: tuple[str, ...] = ()
    raw_events: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "hypothesis": self.hypothesis.as_dict() if self.hypothesis else None,
            "exhausted_kinds": list(self.exhausted_kinds),
            "raw_events": list(self.raw_events),
        }


def rank_next(
    hypotheses: list[IntentHypothesis],
    *,
    corrections: list[dict[str, Any]],
    raw_events: list[Any] | None = None,
) -> RankVerdict:
    """Pick the one card to surface, or degrade to calm/manual."""
    counts: dict[str, int] = {}
    for c in corrections:
        counts[c["kind"]] = counts.get(c["kind"], 0) + 1
    exhausted = tuple(sorted(k for k, n in counts.items() if n >= EXHAUSTION_LIMIT))

    # a kind past the exhaustion limit never produces a card again — the
    # interface admits it keeps guessing wrong and hands the evidence over
    live = [h for h in hypotheses
            if h.kind not in exhausted and h.confidence >= SURFACE_THRESHOLD]
    if live:
        return RankVerdict(mode="card", hypothesis=live[0], exhausted_kinds=exhausted)

    if exhausted:
        tail = tuple(
            e.as_dict() if hasattr(e, "as_dict") else dict(e)
            for e in (raw_events or [])[-10:]
        )
        return RankVerdict(mode="manual", exhausted_kinds=exhausted, raw_events=tail)

    return RankVerdict(mode="calm", exhausted_kinds=exhausted)
