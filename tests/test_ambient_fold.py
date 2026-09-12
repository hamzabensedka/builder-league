"""TDD: the intent fold — deterministic inference of what the operator needs
to decide next, folded from the TowerCore event stream. No LLM, no hardcoded
demo flows: candidates emerge from event shapes."""

import pytest

from core.ambientcore.domain.fold import (
    INTENT_KINDS,
    fold_intents,
)
from core.towercore.domain.events import make_event


def _ev(agent, seq, kind, payload):
    return make_event(agent_id=agent, run_id="run-1", seq=seq,
                      ts="2026-09-12T08:00:00+00:00", kind=kind, payload=payload)


def test_intent_kinds_exact_set():
    assert INTENT_KINDS == frozenset({
        "restock_needed", "deploy_needs_review", "drift_contain", "budget_risk",
    })


def test_pending_approval_yields_review_candidate():
    events = [
        _ev("deploybot", 1, "approval_requested",
            {"action": "deploy_production", "amount": 1200.0, "reason": "escalate",
             "version": "v12"}),
    ]
    hyps = fold_intents(events, fleet={"deploybot": {"status": "awaiting_approval"}},
                        corrections=[])
    kinds = [h.kind for h in hyps]
    assert "deploy_needs_review" in kinds
    h = next(h for h in hyps if h.kind == "deploy_needs_review")
    assert h.confidence > 0.0
    assert h.evidence  # non-empty evidence chain
    assert h.target == "deploybot"


def test_resolved_approval_is_not_resurfaced():
    events = [
        _ev("deploybot", 1, "approval_requested",
            {"action": "deploy_production", "amount": 1200.0, "reason": "escalate",
             "version": "v12"}),
        _ev("deploybot", 2, "approval_resolved",
            {"approval_id": "ap-1", "status": "approved", "operator": "op"}),
    ]
    hyps = fold_intents(events, fleet={"deploybot": {"status": "running"}},
                        corrections=[])
    assert not any(h.kind == "deploy_needs_review" for h in hyps)


def test_drift_flag_yields_contain_candidate():
    events = [
        _ev("deploybot", 1, "drift_flagged",
            {"kind": "escalation_burst", "summary": "3 escalations in 20 events"}),
    ]
    hyps = fold_intents(events, fleet={"deploybot": {"status": "paused"}},
                        corrections=[])
    h = next(h for h in hyps if h.kind == "drift_contain")
    assert h.target == "deploybot"
    assert any("escalation_burst" in e for e in h.evidence)


def test_paused_without_drift_is_not_contain_candidate():
    # a human paused the agent deliberately — no drift flag, no containment card
    events = [
        _ev("restockbot", 1, "intervention_applied",
            {"intervention": "pause", "operator": "op"}),
    ]
    hyps = fold_intents(events, fleet={"restockbot": {"status": "paused"}},
                        corrections=[])
    assert not any(h.kind == "drift_contain" for h in hyps)


def test_low_stock_yields_restock_candidate():
    events = [
        _ev("restockbot", 1, "action_executed",
            {"action": "check_stock", "stock": {"widgets": 2}, "low": ["widgets"]}),
    ]
    hyps = fold_intents(events, fleet={"restockbot": {"status": "running"}},
                        corrections=[])
    h = next(h for h in hyps if h.kind == "restock_needed")
    assert "widgets" in h.evidence[0] or any("widgets" in e for e in h.evidence)
    assert h.proposed_action["action"] == "purchase"
    assert h.proposed_action["amount"] > 0


def test_no_signal_events_yield_no_candidates():
    events = [
        _ev("restockbot", 1, "step_started", {"step": "check_stock"}),
        _ev("restockbot", 2, "action_executed",
            {"action": "check_stock", "stock": {"widgets": 9}, "low": []}),
    ]
    assert fold_intents(events, fleet={"restockbot": {"status": "running"}},
                        corrections=[]) == []


def test_budget_risk_when_spend_near_limit():
    events = []
    fleet = {"restockbot": {"status": "running"}}
    ledger = {"projected_balance": 920.0, "limit": 1000.0}
    hyps = fold_intents(events, fleet=fleet, corrections=[], ledger=ledger)
    h = next(h for h in hyps if h.kind == "budget_risk")
    assert h.confidence > 0.0
    assert h.missing  # names what it does not know


def test_budget_risk_absent_when_comfortable():
    hyps = fold_intents([], fleet={}, corrections=[],
                        ledger={"projected_balance": 100.0, "limit": 1000.0})
    assert not any(h.kind == "budget_risk" for h in hyps)


def test_determinism_same_inputs_same_hypotheses():
    events = [
        _ev("deploybot", 1, "approval_requested",
            {"action": "deploy_production", "amount": 1200.0, "reason": "escalate"}),
        _ev("deploybot", 2, "drift_flagged",
            {"kind": "escalation_burst", "summary": "burst"}),
    ]
    fleet = {"deploybot": {"status": "awaiting_approval"}}
    a = fold_intents(events, fleet=fleet, corrections=[])
    b = fold_intents(events, fleet=fleet, corrections=[])
    assert [h.as_dict() for h in a] == [h.as_dict() for h in b]


def test_correction_demotes_matching_kind():
    events = [
        _ev("deploybot", 1, "drift_flagged",
            {"kind": "escalation_burst", "summary": "burst"}),
    ]
    fleet = {"deploybot": {"status": "paused"}}
    plain = fold_intents(events, fleet=fleet, corrections=[])
    corrected = fold_intents(
        events, fleet=fleet,
        corrections=[{"kind": "drift_contain", "note": "not useful", "ts": "t"}],
    )
    plain_c = next(h for h in plain if h.kind == "drift_contain").confidence
    demoted = next(h for h in corrected if h.kind == "drift_contain")
    assert demoted.confidence < plain_c
    assert demoted.demoted is True
    assert any("correction" in e for e in demoted.evidence)


def test_unknown_correction_kind_rejected_fail_closed():
    with pytest.raises(ValueError):
        fold_intents([], fleet={}, corrections=[{"kind": "nonsense", "note": "x"}])
