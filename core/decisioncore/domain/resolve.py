"""Resolution: (confidence, risk, facts) → one of five outcomes. Pure.

An ordered rule table — the first matching rule wins, and the winning rule's
name is recorded as resolution_path so every outcome is explainable. This is
the heart of "a real decision engine, not a prompt wrapper": the mapping from
signals to outcome is explicit, deterministic, and tested rule by rule.

The five outcomes:
  execute  — confident, acceptable risk → act
  ask      — under-evidenced → gather the named missing information first
  defer    — not ready now but retryable later (e.g. evidence still arriving)
  escalate — high risk a human must own (irreversible + costly)
  refuse   — hard block (forged/missing authority on a privileged action)
"""

import enum
from dataclasses import dataclass, field

from core.decisioncore.domain.policies import DomainPolicy


class Outcome(enum.StrEnum):
    EXECUTE = "execute"
    ASK = "ask"
    DEFER = "defer"
    ESCALATE = "escalate"
    REFUSE = "refuse"


@dataclass(frozen=True)
class ResolutionFacts:
    """The non-numeric facts the rules consult, gathered by the service."""

    authority: str  # "valid" | "uncertain" | "invalid"
    reversible: bool  # compensating action exists AND is not partial-high-cost
    missing_required: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Resolution:
    outcome: Outcome
    path: str  # which rule fired
    reason: str


def resolve(
    *, policy: DomainPolicy, confidence: float, risk: float, facts: ResolutionFacts
) -> Resolution:
    """Ordered rules; first match wins. Deterministic, no LLM."""
    high_risk = risk >= policy.risk_bar

    # 1. Forged/invalid authority on a privileged action → hard block.
    if facts.authority == "invalid":
        return Resolution(
            outcome=Outcome.REFUSE,
            path="hard_block:invalid_authority",
            reason="authority evidence failed verification (forged, revoked, or out of scope)",
        )

    # 2. No usable authority at all → a human must decide who may act.
    if facts.authority == "uncertain":
        return Resolution(
            outcome=Outcome.ESCALATE,
            path="hard_block:uncertain_authority",
            reason="no valid authority grant on record — cannot self-authorize",
        )

    # 3. Under-evidenced → ask, and name what is missing.
    if confidence < policy.confidence_floor:
        missing = ", ".join(facts.missing_required) or "supporting evidence"
        return Resolution(
            outcome=Outcome.ASK,
            path="hard_floor:insufficient_confidence",
            reason=f"confidence {confidence:.2f} below floor {policy.confidence_floor:.2f}; "
            f"missing: {missing}",
        )

    # 4. High risk and NOT safely reversible → escalate to a human.
    if high_risk and not facts.reversible:
        return Resolution(
            outcome=Outcome.ESCALATE,
            path="risk_high_not_reversible",
            reason=f"risk {risk:.2f} ≥ {policy.risk_bar:.2f} and no cheap full compensating "
            "action exists — a human must own this",
        )

    # 5. High risk, reversible, but evidence incomplete → defer until ready.
    if high_risk and facts.missing_required:
        return Resolution(
            outcome=Outcome.DEFER,
            path="risk_high_evidence_pending",
            reason=f"risk {risk:.2f} is high but a compensating action exists; "
            f"defer until evidence arrives: {', '.join(facts.missing_required)}",
        )

    # 6. Confident and risk acceptable → execute.
    if confidence >= policy.execute_bar:
        return Resolution(
            outcome=Outcome.EXECUTE,
            path="confident_acceptable_risk",
            reason=f"confidence {confidence:.2f} ≥ {policy.execute_bar:.2f} "
            f"with risk {risk:.2f} < {policy.risk_bar:.2f}",
        )

    # 7. Default: gather, don't guess.
    return Resolution(
        outcome=Outcome.ASK,
        path="default:gather_dont_guess",
        reason=f"confidence {confidence:.2f} below execute bar {policy.execute_bar:.2f} "
        "and no hard block — ask for what would raise it",
    )
