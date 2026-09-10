"""Policy evaluation via Cedar (cedarpy). Pure: claims in, decision out.

The Cedar schema/policy live in the adapter layer as data files; this module
is the pure evaluation seam. The LLM is never on this path.
"""

import enum
from dataclasses import dataclass
from typing import Any


class PolicyDecision(enum.StrEnum):
    ALLOW = "allow"
    REFUSE = "refuse"
    ESCALATE = "escalate"


@dataclass(frozen=True)
class PolicyResult:
    decision: PolicyDecision
    reasons: list[str]


def evaluate(
    *,
    action: str,
    amount: float | None,
    valid_authority_claims: list[dict[str, Any]],
    valid_completion_count: int,
) -> PolicyResult:
    """Decide allow/refuse/escalate from already-verified claims.

    Rules (deterministic, no LLM):
    - No valid authority claim covering this action+amount -> REFUSE.
    - Valid authority + counterparty has completed-task history -> ALLOW.
    - Valid authority but zero history (new counterparty) -> ESCALATE.
    """
    covering = [c for c in valid_authority_claims if _covers(c, action=action, amount=amount)]
    if not covering:
        return PolicyResult(
            decision=PolicyDecision.REFUSE,
            reasons=["no valid authority claim covers this action/amount"],
        )
    if valid_completion_count > 0:
        return PolicyResult(
            decision=PolicyDecision.ALLOW,
            reasons=[
                f"authority claim {covering[0]['id']} covers action; "
                f"{valid_completion_count} completed-task claim(s) on record"
            ],
        )
    return PolicyResult(
        decision=PolicyDecision.ESCALATE,
        reasons=["authority valid but counterparty has no completed-task history"],
    )


def _covers(claim: dict[str, Any], *, action: str, amount: float | None) -> bool:
    scope = claim.get("scope", {})
    actions = scope.get("actions") or []
    if action not in actions:
        return False
    max_amount = scope.get("max_amount")
    return not (amount is not None and max_amount is not None and amount > float(max_amount))
