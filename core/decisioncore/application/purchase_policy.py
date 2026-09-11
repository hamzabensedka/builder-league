"""Purchase domain policy — the procurement gate AdaptiveCore steps pass through.

Registered here (DecisionCore's application surface) rather than inside
adaptivecore, because policies are DecisionCore domain data; AdaptiveCore
only calls decide() by domain name. Same shape as the C2 domains.
"""

from core.decisioncore.domain.policies import (
    SIGNAL_AUTHORITY,
    SIGNAL_COST_OF_WRONG,
    SIGNAL_EVIDENCE,
    SIGNAL_HISTORY,
    SIGNAL_REVERSIBILITY,
    Compensation,
    DomainPolicy,
)

PURCHASE = DomainPolicy(
    domain="purchase",
    actions=["purchase"],
    required_evidence=["invoice_id", "reason"],
    optional_evidence=["supplier"],
    cost_threshold=500.0,
    confidence_weights={
        SIGNAL_AUTHORITY: 0.30,
        SIGNAL_REVERSIBILITY: 0.15,
        SIGNAL_EVIDENCE: 0.30,
        SIGNAL_HISTORY: 0.25,
    },
    risk_weights={
        SIGNAL_COST_OF_WRONG: 0.50,
        SIGNAL_REVERSIBILITY: 0.30,
        SIGNAL_AUTHORITY: 0.20,
    },
    compensation={
        # A purchase against the budget ledger is reversible at low cost:
        # the C8 rollback path appends a compensating refund entry.
        "purchase": Compensation(exists=True, kind="refund_reversal", cost="low", partial=False),
    },
    confidence_floor=0.55,
    execute_bar=0.70,
    risk_bar=0.60,
    description="Purchase against the shared budget ledger (AdaptiveCore mission gate).",
)
