"""IntentHypothesis — what the interface believes the operator needs to decide.

An immutable value object produced by the fold. Carries the evidence chain so
the UI can show WHY a card surfaced, the proposed action so the card can be
acted on, and the named gaps so the card can be honest about what it doesn't
know. Fail-closed: malformed hypotheses are rejected at construction.

Pure domain: no I/O, no frameworks, no LLM.
"""

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

INTENT_KINDS = frozenset({
    "restock_needed", "deploy_needs_review", "drift_contain", "budget_risk",
})


@dataclass(frozen=True)
class IntentHypothesis:
    id: str
    kind: str
    target: str  # agent_id or "fleet" the intent concerns
    confidence: float  # 0..1, post-demotion
    base_confidence: float  # before corrections — the demotion is visible
    evidence: tuple[str, ...]
    missing: tuple[str, ...]
    proposed_action: dict[str, Any] = field(default_factory=dict)
    demoted: bool = False
    correction_note: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "target": self.target,
            "confidence": round(self.confidence, 3),
            "base_confidence": round(self.base_confidence, 3),
            "evidence": list(self.evidence),
            "missing": list(self.missing),
            "proposed_action": self.proposed_action,
            "demoted": self.demoted,
            "correction_note": self.correction_note,
        }


def make_hypothesis(
    *,
    kind: str,
    target: str,
    confidence: float,
    evidence: tuple[str, ...],
    missing: tuple[str, ...] = (),
    proposed_action: dict[str, Any] | None = None,
    demoted: bool = False,
    correction_note: str | None = None,
    hypothesis_id: str | None = None,
) -> IntentHypothesis:
    """Fail-closed constructor: unknown kind, bad confidence, empty target raise."""
    if kind not in INTENT_KINDS:
        raise ValueError(f"unknown intent kind {kind!r}")
    if not target:
        raise ValueError("hypothesis target must be non-empty")
    if not 0.0 <= confidence <= 1.0:
        raise ValueError(f"confidence must be in [0,1], got {confidence}")
    # deterministic id: same inference inputs -> same hypothesis id, so a
    # demoted retry of the same situation is recognizably the same intent
    if hypothesis_id is None:
        seed = json.dumps({"kind": kind, "target": target,
                           "action": proposed_action or {}}, sort_keys=True)
        hypothesis_id = f"hyp-{hashlib.sha256(seed.encode()).hexdigest()[:10]}"
    return IntentHypothesis(
        id=hypothesis_id,
        kind=kind,
        target=target,
        confidence=confidence,
        base_confidence=confidence if not demoted else _base_before_demotion(confidence),
        evidence=tuple(evidence),
        missing=tuple(missing),
        proposed_action=proposed_action or {},
        demoted=demoted,
        correction_note=correction_note,
    )


def _base_before_demotion(confidence: float) -> float:
    """Reconstruct an approximate base for display; the fold always passes the
    true base via demoted=False first, so this only guards direct construction."""
    return min(1.0, confidence / 0.5)
