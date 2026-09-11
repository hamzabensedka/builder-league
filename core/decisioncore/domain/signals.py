"""The five weighted signals. Pure functions: verified facts in, SignalScore out.

Each signal is named, weighted (weights come from the DomainPolicy), and
produces a normalized 0..1 reading plus a human-readable detail string. The
decision receipt stores every SignalScore, so any confidence/risk number can
be recomputed by hand from the receipt.

No I/O, no LLM — the facts (authority verdict, compensation map, context
fields, history counts) are gathered by the application layer and passed in.
"""

from dataclasses import dataclass
from typing import Any

from core.decisioncore.domain.policies import (
    SIGNAL_AUTHORITY,
    SIGNAL_COST_OF_WRONG,
    SIGNAL_EVIDENCE,
    SIGNAL_HISTORY,
    SIGNAL_REVERSIBILITY,
    Compensation,
    DomainPolicy,
)


@dataclass(frozen=True)
class SignalScore:
    name: str
    value: float  # normalized 0..1
    weight: float  # from DomainPolicy
    contributes_to: str  # "confidence" | "risk"
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": round(self.value, 3),
            "weight": self.weight,
            "contributes_to": self.contributes_to,
            "detail": self.detail,
        }


# ---------------------------------------------------------------------------
# authority — does the actor hold a valid signed grant covering this action?
# Facts come from TrustCore's decide() verdict (real signature/scope checks).
# ---------------------------------------------------------------------------

def authority_signal(
    *, policy: DomainPolicy, authority: str, detail: str
) -> SignalScore:
    """authority: "valid" | "uncertain" | "invalid" (from TrustCore)."""
    value = {"valid": 1.0, "uncertain": 0.35, "invalid": 0.0}[authority]
    return SignalScore(
        name=SIGNAL_AUTHORITY,
        value=value,
        weight=policy.confidence_weights[SIGNAL_AUTHORITY],
        contributes_to="confidence",
        detail=detail,
    )


def authority_risk_signal(*, policy: DomainPolicy, authority: str) -> SignalScore:
    """The risk-side mirror: invalid authority is maximum risk."""
    value = {"valid": 0.0, "uncertain": 0.6, "invalid": 1.0}[authority]
    return SignalScore(
        name=SIGNAL_AUTHORITY,
        value=value,
        weight=policy.risk_weights[SIGNAL_AUTHORITY],
        contributes_to="risk",
        detail="authority " + authority,
    )


# ---------------------------------------------------------------------------
# reversibility — is there a compensating action? (SimCore/C8 pattern)
# ---------------------------------------------------------------------------

def reversibility_signal(
    *, policy: DomainPolicy, compensation: Compensation
) -> SignalScore:
    score = compensation.reversibility_score()
    if not compensation.exists:
        detail = "no compensating action defined — irreversible"
    else:
        detail = (
            f"compensating action: {compensation.kind} "
            f"({compensation.cost} cost{', partial' if compensation.partial else ''})"
        )
    return SignalScore(
        name=SIGNAL_REVERSIBILITY,
        value=score,
        weight=policy.confidence_weights[SIGNAL_REVERSIBILITY],
        contributes_to="confidence",
        detail=detail,
    )


def reversibility_risk_signal(
    *, policy: DomainPolicy, compensation: Compensation
) -> SignalScore:
    return SignalScore(
        name=SIGNAL_REVERSIBILITY,
        value=round(1.0 - compensation.reversibility_score(), 3),
        weight=policy.risk_weights[SIGNAL_REVERSIBILITY],
        contributes_to="risk",
        detail="reversibility " + ("high" if compensation.exists else "none"),
    )


# ---------------------------------------------------------------------------
# evidence — required vs present context fields. Missing fields are NAMED.
# ---------------------------------------------------------------------------

def evidence_signal(
    *, policy: DomainPolicy, context: dict[str, Any]
) -> tuple[SignalScore, list[str], list[str]]:
    """Returns (signal, missing_required, present_fields)."""
    required = policy.required_evidence
    missing = [f for f in required if context.get(f) in (None, "", [])]
    present_required = [f for f in required if f not in missing]
    present_optional = [
        f for f in policy.optional_evidence if context.get(f) not in (None, "", [])
    ]

    required_ratio = (len(present_required) / len(required)) if required else 1.0
    optional_bonus = 0.0
    if policy.optional_evidence:
        optional_bonus = 0.2 * (len(present_optional) / len(policy.optional_evidence))
    value = min(1.0, 0.8 * required_ratio + optional_bonus)

    detail = (
        f"{len(present_required)}/{len(required)} required fields present"
        + (f"; missing: {', '.join(missing)}" if missing else "")
    )
    present = present_required + present_optional
    return (
        SignalScore(
            name=SIGNAL_EVIDENCE,
            value=round(value, 3),
            weight=policy.confidence_weights[SIGNAL_EVIDENCE],
            contributes_to="confidence",
            detail=detail,
        ),
        missing,
        present,
    )


# ---------------------------------------------------------------------------
# cost_of_wrong — amount/blast-radius vs the domain threshold.
# ---------------------------------------------------------------------------

def cost_of_wrong_signal(
    *, policy: DomainPolicy, amount: float | None
) -> SignalScore:
    if amount is None:
        value, detail = 0.3, "no amount given — treated as moderate risk"
    else:
        # ≤threshold → ramps 0..0.5; threshold→2×threshold → 0.5..1.0
        ratio = amount / policy.cost_threshold if policy.cost_threshold else 1.0
        value = min(1.0, 0.5 * ratio)
        detail = (
            f"amount {amount:g} vs threshold {policy.cost_threshold:g}"
            + (" (over threshold)" if amount > policy.cost_threshold else "")
        )
    return SignalScore(
        name=SIGNAL_COST_OF_WRONG,
        value=round(value, 3),
        weight=policy.risk_weights[SIGNAL_COST_OF_WRONG],
        contributes_to="risk",
        detail=detail,
    )


# ---------------------------------------------------------------------------
# history — past receipt outcomes for this actor+action (append-only log).
# ---------------------------------------------------------------------------

def history_signal(
    *, policy: DomainPolicy, total: int, favorable: int
) -> SignalScore:
    if total == 0:
        return SignalScore(
            name=SIGNAL_HISTORY,
            value=0.3,  # no track record → neutral-low, can force ask
            weight=policy.confidence_weights[SIGNAL_HISTORY],
            contributes_to="confidence",
            detail="no prior decisions on record for this actor+action",
        )
    rate = favorable / total
    return SignalScore(
        name=SIGNAL_HISTORY,
        value=round(rate, 3),
        weight=policy.confidence_weights[SIGNAL_HISTORY],
        contributes_to="confidence",
        detail=f"{favorable}/{total} past decisions favorable for this actor+action",
    )
