"""The purchase pipeline — ONE function, two targets.

Fork and live execution call the exact same code; only the injected
stores differ. That is what makes "simulation == what will happen" true
by construction instead of by promise.

No LLM anywhere on this path.
"""

from typing import Any

from core.simcore.domain.ledger import BudgetLedger
from core.trustcore.application.services import TrustService
from core.trustcore.domain.policy import PolicyDecision


def run_purchase(
    *,
    trust: TrustService,
    ledger: BudgetLedger,
    requester_key: str,
    amount: float,
    description: str,
    reference: str,
) -> dict[str, Any]:
    """Decide via TrustCore, then — only on allow — append the spend entry.

    Returns the decision receipt id, the decision, and the ledger entry (if
    any). Callers pass either the LIVE ledger (execution) or a forked one
    (simulation); TrustService.decide always appends a decision receipt,
    satisfying the append-only audit rule on both paths.
    """
    receipt = trust.decide(
        requester_key=requester_key,
        action="purchase",
        amount=amount,
        description=description,
    )
    entry = None
    if receipt.decision == PolicyDecision.ALLOW:
        entry = ledger.spend(agent_key=requester_key, amount=amount, reference=reference)
    return {
        "receipt_id": receipt.id,
        "decision": str(receipt.decision),
        "reasoning": receipt.reasoning,
        "ledger_entry": entry.as_dict() if entry else None,
    }
