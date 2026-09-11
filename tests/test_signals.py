"""D1: the five weighted signals — satisfied/unsatisfied/partial readings."""

from core.decisioncore.domain.policies import (
    DEPLOY,
    REFUND,
    Compensation,
)
from core.decisioncore.domain.signals import (
    authority_signal,
    cost_of_wrong_signal,
    evidence_signal,
    history_signal,
    reversibility_signal,
)

# --- authority ---------------------------------------------------------------

def test_authority_valid_is_full_confidence():
    s = authority_signal(policy=REFUND, authority="valid", detail="grant covers action")
    assert s.value == 1.0
    assert s.contributes_to == "confidence"
    assert s.weight == REFUND.confidence_weights["authority"]


def test_authority_uncertain_and_invalid():
    assert authority_signal(policy=REFUND, authority="uncertain", detail="").value == 0.35
    assert authority_signal(policy=REFUND, authority="invalid", detail="").value == 0.0


# --- reversibility (SimCore compensation pattern) ----------------------------

def test_reversibility_full_when_cheap_complete():
    c = Compensation(exists=True, kind="refund_reversal", cost="low", partial=False)
    assert c.reversibility_score() == 1.0
    s = reversibility_signal(policy=REFUND, compensation=c)
    assert s.value == 1.0
    assert "refund_reversal" in s.detail


def test_reversibility_partial_high_cost_is_low():
    c = Compensation(exists=True, kind="rollback_deploy", cost="high", partial=True)
    # 0.3 base for high cost, halved for partial
    assert c.reversibility_score() == 0.15
    s = reversibility_signal(policy=DEPLOY, compensation=c)
    assert s.value == 0.15


def test_reversibility_none_when_no_compensation():
    c = Compensation(exists=False, kind="none_defined", cost="high", partial=True)
    assert c.reversibility_score() == 0.0
    s = reversibility_signal(policy=REFUND, compensation=c)
    assert s.value == 0.0
    assert "irreversible" in s.detail


# --- evidence: required vs present, missing NAMED ----------------------------

def test_evidence_full_when_all_required_present():
    s, missing, present = evidence_signal(
        policy=REFUND, context={"invoice_id": "INV-1", "reason": "defective"}
    )
    assert missing == []
    assert set(present) == {"invoice_id", "reason"}
    assert s.value >= 0.8


def test_evidence_partial_names_missing():
    s, missing, present = evidence_signal(
        policy=REFUND, context={"reason": "defective"}  # invoice_id missing
    )
    assert missing == ["invoice_id"]
    assert "invoice_id" not in present
    assert s.value < 0.8
    assert "invoice_id" in s.detail


def test_evidence_optional_bonus_raises_value():
    full, _, _ = evidence_signal(
        policy=REFUND, context={"invoice_id": "INV-1", "reason": "x"}
    )
    bonus, _, _ = evidence_signal(
        policy=REFUND,
        context={"invoice_id": "INV-1", "reason": "x", "customer_history": "gold"},
    )
    assert bonus.value > full.value


# --- cost_of_wrong vs threshold ---------------------------------------------

def test_cost_below_threshold_is_low_risk():
    s = cost_of_wrong_signal(policy=REFUND, amount=120)  # threshold 500
    assert s.value < 0.5
    assert "over threshold" not in s.detail


def test_cost_over_threshold_is_high_risk():
    s = cost_of_wrong_signal(policy=REFUND, amount=2400)  # 4.8x threshold
    assert s.value == 1.0
    assert "over threshold" in s.detail


def test_cost_none_is_moderate():
    s = cost_of_wrong_signal(policy=REFUND, amount=None)
    assert s.value == 0.3


# --- history from the receipt log -------------------------------------------

def test_history_no_record_is_neutral_low():
    s = history_signal(policy=REFUND, total=0, favorable=0)
    assert s.value == 0.3
    assert "no prior" in s.detail


def test_history_rate():
    s = history_signal(policy=REFUND, total=10, favorable=9)
    assert s.value == 0.9
    assert "9/10" in s.detail
