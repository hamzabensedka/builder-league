"""DecisionService: proposed action + context → one of five outcomes, receipted.

Composes TrustCore (authority evidence) and the SimCore compensation pattern
(reversibility) into confidence + risk, then resolves deterministically. No
LLM on any path — every number is weighted arithmetic over verified facts,
and the full signal vector is appended to the audit trail per decision.
"""

import builtins
import copy
import uuid
from datetime import UTC, datetime
from typing import Any

from core.decisioncore.application.ports import (
    AuditTrail,
    AuthorityVerifier,
    DecisionStore,
    HistoryReader,
)
from core.decisioncore.domain.policies import DomainPolicy, get_policy
from core.decisioncore.domain.resolve import ResolutionFacts, resolve
from core.decisioncore.domain.signals import (
    SignalScore,
    authority_risk_signal,
    authority_signal,
    cost_of_wrong_signal,
    evidence_signal,
    history_signal,
    reversibility_risk_signal,
    reversibility_signal,
)


class DecisionService:
    def __init__(
        self,
        *,
        authority: AuthorityVerifier,
        history: HistoryReader,
        decisions: DecisionStore,
        audit: AuditTrail,
        authority_probe: Any = None,  # () -> a forked AuthorityVerifier (C8 pattern)
    ) -> None:
        self._authority = authority
        self._history = history
        self._decisions = decisions
        self._audit = audit
        # Injected by the composition root: builds a forked TrustService over a
        # deep copy of live state, so authority verification is REAL (same
        # signatures, same policy) but its receipt lands on the fork — never
        # polluting the shared history log mid-decision. Falls back to the live
        # verifier when no probe is supplied (tests that don't assert history
        # determinism), but the API always injects the probe.
        self._authority_probe = authority_probe

    def list_domains(self) -> list[dict[str, Any]]:
        from core.decisioncore.domain.policies import DOMAINS

        return [
            {
                "domain": p.domain,
                "actions": p.actions,
                "required_evidence": p.required_evidence,
                "cost_threshold": p.cost_threshold,
                "description": p.description,
            }
            for p in DOMAINS.values()
        ]

    # --- the decision -----------------------------------------------------

    def decide(
        self,
        *,
        domain: str,
        action: str,
        actor_key: str,
        amount: float | None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        policy = get_policy(domain)
        if action not in policy.actions:
            raise ValueError(
                f"action {action!r} not in domain {domain!r}: {policy.actions}"
            )
        context = context or {}

        # Snapshot the receipt log BEFORE the authority probe. History reflects
        # only pre-existing receipts, so identical proposals see identical
        # history regardless of what the probe writes. (When a forked probe is
        # injected, its receipts land off the live log entirely.)
        history_snapshot = self._history.list_receipts(limit=10_000)
        total, favorable = self._history_counts(
            history_snapshot, actor_key=actor_key, action=action
        )

        # 1. authority evidence — real signature/scope verification, on a fork
        #    when available so the check never pollutes the live history log
        authority_verdict, authority_detail = self._check_authority(
            policy, actor_key=actor_key, action=action, amount=amount
        )

        # 2. reversibility evidence — the SimCore compensation pattern
        compensation = policy.compensation_for(action)
        reversible = compensation.exists and not (
            compensation.partial and compensation.cost == "high"
        )

        # 3-5. the remaining signals from the raw inputs
        ev_signal, missing_required, present = evidence_signal(policy=policy, context=context)

        signals: list[SignalScore] = [
            authority_signal(policy=policy, authority=authority_verdict, detail=authority_detail),
            reversibility_signal(policy=policy, compensation=compensation),
            ev_signal,
            cost_of_wrong_signal(policy=policy, amount=amount),
            history_signal(policy=policy, total=total, favorable=favorable),
            authority_risk_signal(policy=policy, authority=authority_verdict),
            reversibility_risk_signal(policy=policy, compensation=compensation),
        ]

        confidence = self._weighted_sum(signals, "confidence", policy.confidence_weights)
        risk = self._weighted_sum(signals, "risk", policy.risk_weights)

        resolution = resolve(
            policy=policy,
            confidence=confidence,
            risk=risk,
            facts=ResolutionFacts(
                authority=authority_verdict,
                reversible=reversible,
                missing_required=missing_required,
            ),
        )

        # missing information: absent required fields + authority/history gaps
        missing_information = list(missing_required)
        if authority_verdict == "uncertain":
            missing_information.append("valid_authority_grant")
        if total == 0:
            missing_information.append("track_record")

        record = {
            "id": str(uuid.uuid4()),
            "ts": datetime.now(UTC).isoformat(),
            "domain": domain,
            "proposed": {
                "domain": domain,
                "action": action,
                "actor_key": actor_key,
                "amount": amount,
                "context": context,
            },
            "outcome": str(resolution.outcome),
            "confidence": round(confidence, 3),
            "risk": round(risk, 3),
            "signals": [s.as_dict() for s in signals],
            "evidence_used": present,
            "missing_information": missing_information,
            "reversibility": compensation.as_dict(),
            "resolution_path": resolution.path,
            "reasoning": resolution.reason,
            "llm_called": False,
            "receipt_id": None,
        }

        # audit trail — append to the same append-only log as C1/C8
        receipt = self._audit.record_event(
            actor=f"decisioncore:{actor_key[:12]}",
            action=f"{domain}.{action}",
            note=f"{resolution.outcome}: {resolution.reason}",
            inputs={
                "domain": domain,
                "action": action,
                "amount": amount,
                "confidence": round(confidence, 3),
                "risk": round(risk, 3),
                "resolution_path": resolution.path,
                "missing_information": missing_information,
            },
        )
        record["receipt_id"] = getattr(receipt, "id", None)

        self._decisions.append(record)
        return record

    def get(self, decision_id: str) -> dict[str, Any] | None:
        return self._decisions.get(decision_id)

    def list(self, *, limit: int = 50) -> builtins.list[dict[str, Any]]:
        return self._decisions.list(limit=limit)

    # --- internals ----------------------------------------------------------

    def _check_authority(
        self, policy: DomainPolicy, *, actor_key: str, action: str, amount: float | None
    ) -> tuple[str, str]:
        """Run TrustCore's real decide() and map its verdict to an authority reading.

        Crucially distinguishes three refuse causes:
        - scope-exceeded (a valid grant exists but amount > its max_amount): the
          actor IS credentialed; the over-threshold cost is the RISK signal's
          job, so authority reads "valid" here and cost_of_wrong drives the
          ask/escalate. TrustCore appends its own receipt for the check.
        - no grant at all → "uncertain" (cannot self-authorize → escalate)
        - forged/revoked signature → "invalid" (hard refuse)
        """
        verifier = self._authority_probe() if self._authority_probe else self._authority
        receipt = verifier.decide(
            requester_key=actor_key,
            action=action,
            amount=amount,
            description=f"decisioncore authority check ({policy.domain})",
        )
        decision = str(receipt.decision)
        if decision in ("allow", "escalate"):
            return "valid", f"valid signed grant covers {action}"
        # refuse: inspect WHY. Failures (bad signature/revoked) → invalid.
        failures = receipt.signals.get("failures") or []
        if failures:
            return "invalid", "authority failed verification (forged/revoked/out-of-scope)"
        if receipt.signals.get("valid_authority", 0) > 0:
            # a valid grant exists but didn't cover this action/amount → the
            # actor is credentialed; over-scope cost is risk, not authority.
            return "valid", f"grant valid for {action}; amount exceeds its scope"
        return "uncertain", "no authority grant on record for this actor"

    def _history_counts(
        self, receipts: "builtins.list[Any]", *, actor_key: str, action: str
    ) -> tuple[int, int]:
        """Outcome rate for this actor+action over a SNAPSHOT of receipts.

        Reads only TrustCore decision receipts (the actor's trust decisions on
        this action) — NOT DecisionCore's own audit events (which carry actor
        'decisioncore:…'). Passing a pre-decision snapshot keeps the signal
        deterministic across identical calls."""
        total = favorable = 0
        actor_id = self._authority.find_agent_id(actor_key)
        for r in receipts:
            rid = getattr(r, "agent_id", "") or ""
            raction = getattr(r, "action", "") or ""
            if rid != actor_id or raction != action:
                continue
            total += 1
            if str(getattr(r, "decision", "")) in ("allow", "execute"):
                favorable += 1
        return total, favorable

    @staticmethod
    def _weighted_sum(
        signals: "builtins.list[SignalScore]", kind: str, weights: dict[str, float]
    ) -> float:
        """Weighted mean over the signals contributing to `kind`, normalized by
        the sum of the policy's weights for that side so scores stay in 0..1."""
        total_weight = sum(weights.values()) or 1.0
        acc = sum(s.value * s.weight for s in signals if s.contributes_to == kind)
        return acc / total_weight


def make_authority_probe(trust: Any, trust_factory: Any) -> Any:
    """Build the C8-style fork probe for authority checks.

    Returns a callable producing a forked TrustService over a deep copy of the
    live trust state. Authority verification is REAL (same signed credentials,
    same policy, fail-closed), but the probe's decision receipt lands on the
    fork — never on the shared history log, so the history signal stays a true
    pre-decision snapshot and identical proposals stay deterministic.

    trust_factory: () -> (registry, creds, receipts, clock), injected by the
    composition root (the same seam SimCore uses) so the application layer
    never imports adapters.
    """
    from core.trustcore.application.services import TrustService

    def probe() -> TrustService:
        registry, creds, receipts, clock = trust_factory()
        for agent in trust.list_agents():
            registry.register(
                name=agent["name"], public_key=agent["public_key"], owner=agent["owner"]
            )
        for cred in trust.list_credentials():
            creds.save(copy.deepcopy(cred))
        for r in reversed(trust.list_receipts(limit=10_000)):
            receipts.append(copy.deepcopy(r))
        return TrustService(registry=registry, credentials=creds, receipts=receipts, clock=clock)

    return probe
