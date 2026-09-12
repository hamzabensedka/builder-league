"""TDD: DecisionCard lifecycle — the one thing on screen. Fail-closed
transitions; the card carries its evidence chain and (when pre-simulated) the
computed before/after diff with rollback preview."""

import pytest

from core.ambientcore.domain.card import (
    CARD_STATES,
    DecisionCard,
    make_card,
)
from core.ambientcore.domain.intents import make_hypothesis


def _hyp():
    return make_hypothesis(
        kind="deploy_needs_review", target="deploybot", confidence=0.8,
        evidence=("approval_requested: deploy_production ($1200)",),
        proposed_action={"action": "deploy_production", "amount": 1200.0,
                         "description": "resolve parked deploy"},
    )


def test_card_states_exact_set():
    assert CARD_STATES == frozenset({
        "surfaced", "approved", "edited", "rejected", "manual",
    })


def test_make_card_from_hypothesis():
    card = make_card(hypothesis=_hyp(), rationale="deploy parked 40m", brain="scripted")
    assert card.state == "surfaced"
    assert card.hypothesis.kind == "deploy_needs_review"
    assert card.rationale == "deploy parked 40m"
    d = card.as_dict()
    assert d["hypothesis"]["confidence"] == 0.8
    assert d["sim"] is None  # no pre-simulation attached yet


def test_attach_sim_diff():
    card = make_card(hypothesis=_hyp(), rationale="r", brain="scripted")
    sim = {"id": "sim-1", "fork_diff": {"ledger_entries": {"added": [{}]}},
           "rollback_preview": {"entries": [{"kind": "refund"}]}}
    card2 = card.with_sim(sim)
    assert card2.sim is not None
    assert card2.sim["id"] == "sim-1"
    assert card.state == card2.state == "surfaced"


def test_approve_from_surfaced():
    card = make_card(hypothesis=_hyp(), rationale="r", brain="scripted")
    done = card.approve(operator="op")
    assert done.state == "approved"
    assert done.operator == "op"
    assert card.state == "surfaced"  # immutable: original untouched


def test_reject_requires_note():
    card = make_card(hypothesis=_hyp(), rationale="r", brain="scripted")
    with pytest.raises(ValueError):
        card.reject(operator="op", note="")
    done = card.reject(operator="op", note="wrong call")
    assert done.state == "rejected"
    assert done.resolution_note == "wrong call"


def test_edit_reparametrizes_action():
    card = make_card(hypothesis=_hyp(), rationale="r", brain="scripted")
    edited = card.edit(operator="op",
                       new_action={"action": "deploy_production", "amount": 400.0,
                                   "description": "smaller blast radius"})
    assert edited.state == "edited"
    assert edited.action["amount"] == 400.0
    # original action preserved for the audit trail
    assert edited.original_action["amount"] == 1200.0


def test_illegal_transitions_raise():
    card = make_card(hypothesis=_hyp(), rationale="r", brain="scripted")
    done = card.approve(operator="op")
    with pytest.raises(ValueError):
        done.reject(operator="op", note="too late")
    with pytest.raises(ValueError):
        done.approve(operator="op")
    with pytest.raises(ValueError):
        done.edit(operator="op", new_action={"action": "x"})
    rejected = card.reject(operator="op", note="no")
    with pytest.raises(ValueError):
        rejected.approve(operator="op")


def test_manual_fallback_transition():
    card = make_card(hypothesis=_hyp(), rationale="r", brain="scripted")
    manual = card.to_manual(operator="op", note="second wrong guess")
    assert manual.state == "manual"
    assert manual.resolution_note == "second wrong guess"


def test_card_is_immutable_value():
    card = make_card(hypothesis=_hyp(), rationale="r", brain="scripted")
    with pytest.raises(Exception):  # frozen dataclass
        card.state = "approved"


def test_unknown_state_rejected_fail_closed():
    with pytest.raises(ValueError):
        DecisionCard(
            id="c1", hypothesis=_hyp(), state="flying", rationale="r",
            brain="scripted", action={}, original_action={}, sim=None,
            operator=None, resolution_note=None, ts="t",
        )
