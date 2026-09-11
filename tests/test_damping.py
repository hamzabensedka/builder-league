"""A4: damping — hysteresis, revision budget, oscillation detection."""

from core.adaptivecore.domain.damping import (
    ALLOWED,
    DAMPED,
    ESCALATE_BUDGET,
    ESCALATE_OSCILLATION,
    DampingState,
    evaluate_damping,
    record_revision,
)
from core.adaptivecore.domain.detection import Contradiction


def _price_contradiction(observed: float) -> Contradiction:
    return Contradiction(
        assumption_id="a1", assumption_kind="price_at_most", step_id="s1",
        statement="NorthParts price ≤ $8.00",
        expected="price ≤ 8.00", observed=f"price = {observed:.2f}",
        severity=(observed - 8.0) / 8.0, critical=True, triggering_event_ids=["e1"],
    )


def _budget_contradiction() -> Contradiction:
    return Contradiction(
        assumption_id="a2", assumption_kind="budget_headroom_at_least", step_id="s2",
        statement="budget headroom ≥ $900.00",
        expected="headroom ≥ 900.00", observed="headroom = 400.00",
        severity=0.55, critical=True, triggering_event_ids=["e2"],
    )


def test_no_contradictions_is_damped_trivially():
    d = evaluate_damping(state=DampingState(), contradictions=[], new_plan_shape="x",
                         current_seq=1)
    assert d.verdict == DAMPED


def test_first_contradiction_allowed():
    d = evaluate_damping(state=DampingState(), contradictions=[_price_contradiction(14.0)],
                         new_plan_shape="shape-b", current_seq=1)
    assert d.verdict == ALLOWED
    assert len(d.surviving) == 1


def test_hysteresis_absorbs_sub_margin_flap():
    state = DampingState(margin_pct=0.02, cooldown_span=0)
    record_revision(state, contradictions=[_price_contradiction(8.2)],
                    new_plan_shape="shape-b", current_seq=1)
    # price moves to 8.25 — only 0.6% from last trigger 8.20 → absorbed
    d = evaluate_damping(state=state, contradictions=[_price_contradiction(8.25)],
                         new_plan_shape="shape-c", current_seq=2)
    assert d.verdict == DAMPED
    assert d.surviving == []
    assert "hysteresis" in d.reason


def test_hysteresis_passes_meaningful_move():
    state = DampingState(margin_pct=0.02, cooldown_span=0)
    record_revision(state, contradictions=[_price_contradiction(8.2)],
                    new_plan_shape="shape-b", current_seq=1)
    d = evaluate_damping(state=state, contradictions=[_price_contradiction(9.0)],
                         new_plan_shape="shape-c", current_seq=2)
    assert d.verdict == ALLOWED


def test_mixed_contradictions_partially_damped():
    state = DampingState(margin_pct=0.02, cooldown_span=0)
    record_revision(state, contradictions=[_price_contradiction(8.2)],
                    new_plan_shape="shape-b", current_seq=1)
    d = evaluate_damping(
        state=state,
        contradictions=[_price_contradiction(8.25), _budget_contradiction()],
        new_plan_shape="shape-c", current_seq=2,
    )
    assert d.verdict == ALLOWED
    assert [c.assumption_kind for c in d.surviving] == ["budget_headroom_at_least"]
    assert "damped" in d.reason


def test_cooldown_absorbs_immediate_retrigger():
    state = DampingState(cooldown_span=2)
    record_revision(state, contradictions=[_price_contradiction(8.2)],
                    new_plan_shape="shape-b", current_seq=5)
    # cooldown_until_seq = 7; at seq 6 the world is still settling
    d = evaluate_damping(state=state, contradictions=[_price_contradiction(9.5)],
                         new_plan_shape="shape-c", current_seq=6)
    assert d.verdict == DAMPED
    assert "cooldown" in d.reason
    # at seq 8 the cooldown has passed
    d2 = evaluate_damping(state=state, contradictions=[_price_contradiction(9.5)],
                          new_plan_shape="shape-c", current_seq=8)
    assert d2.verdict == ALLOWED


def test_revision_budget_exhaustion_escalates():
    state = DampingState(max_revisions=3, revision_count=3, cooldown_span=0)
    d = evaluate_damping(state=state, contradictions=[_budget_contradiction()],
                         new_plan_shape="shape-z", current_seq=10)
    assert d.verdict == ESCALATE_BUDGET
    assert "3/3" in d.reason
    assert "human" in d.reason


def test_oscillation_a_b_a_escalates():
    state = DampingState(cooldown_span=0)
    state.recent_plan_shapes = ["shape-a", "shape-b"]
    d = evaluate_damping(state=state, contradictions=[_price_contradiction(14.0)],
                         new_plan_shape="shape-a", current_seq=5)
    assert d.verdict == ESCALATE_OSCILLATION
    assert "A→B→A" in d.reason


def test_a_b_c_is_not_oscillation():
    state = DampingState(cooldown_span=0)
    state.recent_plan_shapes = ["shape-a", "shape-b"]
    d = evaluate_damping(state=state, contradictions=[_price_contradiction(14.0)],
                         new_plan_shape="shape-c", current_seq=5)
    assert d.verdict == ALLOWED


def test_record_revision_updates_state():
    state = DampingState(cooldown_span=1)
    record_revision(state, contradictions=[_price_contradiction(8.2)],
                    new_plan_shape="shape-b", current_seq=3)
    assert state.revision_count == 1
    assert state.recent_plan_shapes == ["shape-b"]
    assert state.cooldown_until_seq == 4
    assert state.last_trigger_values["price_at_most"] == 8.2
    d = state.as_dict()
    assert d["revision_count"] == 1 and d["max_revisions"] == 3


def test_oscillation_checked_before_budget():
    """Oscillation is the sharper signal — it fires even with budget left."""
    state = DampingState(max_revisions=3, revision_count=2, cooldown_span=0)
    state.recent_plan_shapes = ["shape-a", "shape-b"]
    d = evaluate_damping(state=state, contradictions=[_price_contradiction(14.0)],
                         new_plan_shape="shape-a", current_seq=9)
    assert d.verdict == ESCALATE_OSCILLATION
