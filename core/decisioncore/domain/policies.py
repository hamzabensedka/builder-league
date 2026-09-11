"""Domain policies — the per-domain configuration the engine decides against.

Pure data, zero I/O. A DomainPolicy is the complete contract for one domain:
what evidence an action needs, what it costs to be wrong, how each signal is
weighted, and whether a compensating action exists (the SimCore/C8 pattern —
reversal is a real compensating entry, never an undo).

Three real domains ship wired in: refund approval, code deploy, content
moderation. Each has its own actor, thresholds, and evidence contract — not
toy stubs sharing one config.
"""

from dataclasses import dataclass
from typing import Any

# Signal names (the five weighted inputs to every decision)
SIGNAL_AUTHORITY = "authority"
SIGNAL_REVERSIBILITY = "reversibility"
SIGNAL_EVIDENCE = "evidence"
SIGNAL_COST_OF_WRONG = "cost_of_wrong"
SIGNAL_HISTORY = "history"

ALL_SIGNALS = [
    SIGNAL_AUTHORITY,
    SIGNAL_REVERSIBILITY,
    SIGNAL_EVIDENCE,
    SIGNAL_COST_OF_WRONG,
    SIGNAL_HISTORY,
]


@dataclass(frozen=True)
class Compensation:
    """Reversibility evidence for an action (the C8 compensating-action pattern).

    exists:  is a compensating action defined at all?
    kind:    what the reversal is (refund_reversal, rollback_deploy, restore_content)
    cost:    low | medium | high — the cost of performing the reversal
    partial: True when the reversal cannot fully restore prior state
             (e.g. a production deploy — rollback exists but damage may be done)
    """

    exists: bool
    kind: str
    cost: str  # "low" | "medium" | "high"
    partial: bool

    def reversibility_score(self) -> float:
        """Normalized reversibility: 1.0 = trivially reversible, 0.0 = irreversible."""
        if not self.exists:
            return 0.0
        base = {"low": 1.0, "medium": 0.6, "high": 0.3}[self.cost]
        return round(base * (0.5 if self.partial else 1.0), 3)

    def as_dict(self) -> dict[str, Any]:
        return {
            "exists": self.exists,
            "kind": self.kind,
            "cost": self.cost,
            "partial": self.partial,
            "reversibility_score": self.reversibility_score(),
        }


@dataclass(frozen=True)
class DomainPolicy:
    """The complete decision contract for one domain."""

    domain: str
    actions: list[str]
    required_evidence: list[str]
    optional_evidence: list[str]
    cost_threshold: float  # amount/blast-radius above which being wrong is expensive
    # confidence weights: how much each signal contributes to confidence
    confidence_weights: dict[str, float]
    # risk weights: how much each signal contributes to risk
    risk_weights: dict[str, float]
    compensation: dict[str, Compensation]  # action -> Compensation
    # resolution tuning
    confidence_floor: float = 0.55  # below this → cannot execute (ask)
    execute_bar: float = 0.7  # confidence needed to execute when risk is acceptable
    risk_bar: float = 0.6  # risk at/above this is "high"
    description: str = ""

    def compensation_for(self, action: str) -> Compensation:
        """The reversibility verdict for an action. Unknown action = irreversible."""
        return self.compensation.get(
            action,
            Compensation(exists=False, kind="none_defined", cost="high", partial=True),
        )

    def validate(self) -> None:
        """Fail fast on a malformed policy rather than decide against garbage."""
        for w in (self.confidence_weights, self.risk_weights):
            unknown = set(w) - set(ALL_SIGNALS)
            if unknown:
                raise ValueError(f"{self.domain}: unknown signals in weights: {unknown}")


# ---------------------------------------------------------------------------
# The three wired-in domains. Real contracts, not toy stubs.
# ---------------------------------------------------------------------------

REFUND = DomainPolicy(
    domain="refund",
    actions=["issue_refund"],
    required_evidence=["invoice_id", "reason"],
    optional_evidence=["customer_history", "prior_refunds_count"],
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
        "issue_refund": Compensation(
            exists=True, kind="refund_reversal", cost="low", partial=False
        ),
    },
    confidence_floor=0.55,
    execute_bar=0.70,
    risk_bar=0.60,
    description="Approve a customer refund against invoice evidence.",
)

DEPLOY = DomainPolicy(
    domain="deploy",
    actions=["deploy_production"],
    required_evidence=["tests_passing", "approvals", "change_ticket"],
    optional_evidence=["canary_plan", "rollback_rehearsed"],
    cost_threshold=2000.0,
    confidence_weights={
        SIGNAL_AUTHORITY: 0.25,
        SIGNAL_REVERSIBILITY: 0.10,
        SIGNAL_EVIDENCE: 0.40,
        SIGNAL_HISTORY: 0.25,
    },
    risk_weights={
        SIGNAL_COST_OF_WRONG: 0.45,
        SIGNAL_REVERSIBILITY: 0.40,
        SIGNAL_AUTHORITY: 0.15,
    },
    compensation={
        # A prod deploy has a rollback, but rollback is costly and cannot
        # fully restore state (data may have been written, users impacted).
        "deploy_production": Compensation(
            exists=True, kind="rollback_deploy", cost="high", partial=True
        ),
    },
    confidence_floor=0.60,
    execute_bar=0.75,
    risk_bar=0.55,
    description="Deploy a service to production with blast-radius awareness.",
)

MODERATION = DomainPolicy(
    domain="moderation",
    actions=["remove_content"],
    required_evidence=["report_count", "policy_category"],
    optional_evidence=["prior_violations", "content_age_days"],
    cost_threshold=100.0,  # reach proxy: estimated affected viewers
    confidence_weights={
        SIGNAL_AUTHORITY: 0.30,
        SIGNAL_REVERSIBILITY: 0.20,
        SIGNAL_EVIDENCE: 0.30,
        SIGNAL_HISTORY: 0.20,
    },
    risk_weights={
        SIGNAL_COST_OF_WRONG: 0.40,
        SIGNAL_REVERSIBILITY: 0.35,
        SIGNAL_AUTHORITY: 0.25,
    },
    compensation={
        # Removed content can be restored — cheap and near-complete reversal.
        "remove_content": Compensation(
            exists=True, kind="restore_content", cost="low", partial=False
        ),
    },
    confidence_floor=0.50,
    execute_bar=0.65,
    risk_bar=0.60,
    description="Remove flagged content, reversible if wrong.",
)

DOMAINS: dict[str, DomainPolicy] = {p.domain: p for p in [REFUND, DEPLOY, MODERATION]}


def register_domain(policy: DomainPolicy) -> None:
    """Register an additional domain (e.g. the purchase policy AdaptiveCore
    gates through). Registration is explicit composition, validated."""
    policy.validate()
    DOMAINS[policy.domain] = policy

for _p in DOMAINS.values():
    _p.validate()


def get_policy(domain: str) -> DomainPolicy:
    policy = DOMAINS.get(domain)
    if policy is None:
        raise KeyError(f"unknown domain {domain!r}; known: {sorted(DOMAINS)}")
    return policy
