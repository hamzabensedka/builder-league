"""D2: resolution — every ordered rule fires; determinism; resolution_path set."""

from core.decisioncore.domain.policies import DEPLOY, REFUND
from core.decisioncore.domain.resolve import Outcome, ResolutionFacts, resolve


def facts(authority="valid", reversible=True, missing=None):
    return ResolutionFacts(authority=authority, reversible=reversible,
                           missing_required=missing or [])


# rule 1 — forged/invalid authority → REFUSE (overrides everything)
def test_invalid_authority_refuses_even_when_confident():
    r = resolve(policy=REFUND, confidence=0.95, risk=0.1, facts=facts(authority="invalid"))
    assert r.outcome == Outcome.REFUSE
    assert r.path == "hard_block:invalid_authority"


# rule 2 — no usable authority → ESCALATE
def test_uncertain_authority_escalates():
    r = resolve(policy=REFUND, confidence=0.9, risk=0.1, facts=facts(authority="uncertain"))
    assert r.outcome == Outcome.ESCALATE
    assert r.path == "hard_block:uncertain_authority"


# rule 3 — under-evidenced → ASK naming missing
def test_low_confidence_asks_and_names_missing():
    r = resolve(policy=REFUND, confidence=0.4, risk=0.2,
                facts=facts(missing=["invoice_id"]))
    assert r.outcome == Outcome.ASK
    assert r.path == "hard_floor:insufficient_confidence"
    assert "invoice_id" in r.reason


# rule 4 — high risk + not reversible → ESCALATE
def test_high_risk_irreversible_escalates():
    r = resolve(policy=DEPLOY, confidence=0.9, risk=0.9,
                facts=facts(reversible=False))
    assert r.outcome == Outcome.ESCALATE
    assert r.path == "risk_high_not_reversible"


# rule 5 — high risk + reversible + evidence missing → DEFER
def test_high_risk_reversible_missing_evidence_defers():
    r = resolve(policy=REFUND, confidence=0.7, risk=0.7,
                facts=facts(reversible=True, missing=["reason"]))
    assert r.outcome == Outcome.DEFER
    assert r.path == "risk_high_evidence_pending"
    assert "reason" in r.reason


# rule 6 — confident + acceptable risk → EXECUTE
def test_confident_low_risk_executes():
    r = resolve(policy=REFUND, confidence=0.9, risk=0.2, facts=facts())
    assert r.outcome == Outcome.EXECUTE
    assert r.path == "confident_acceptable_risk"


# rule 7 — default gather-don't-guess → ASK
def test_default_asks():
    # confidence above floor but below execute bar, low risk, nothing missing
    r = resolve(policy=REFUND, confidence=0.6, risk=0.2, facts=facts())
    assert r.outcome == Outcome.ASK
    assert r.path == "default:gather_dont_guess"


# determinism — same inputs → same outcome, always
def test_determinism():
    kwargs = dict(policy=REFUND, confidence=0.7, risk=0.7,
                  facts=facts(reversible=True, missing=["reason"]))
    first = resolve(**kwargs)
    for _ in range(20):
        again = resolve(**kwargs)
        assert again.outcome == first.outcome
        assert again.path == first.path
