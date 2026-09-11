"""A2: contradiction detection — real change detection, change-blind to noise."""

from core.adaptivecore.domain.detection import detect_contradictions
from core.adaptivecore.domain.events import advance_cursor, make_event, new_events
from core.adaptivecore.domain.plans import make_assumption, make_step

WORLD = {
    "suppliers": {
        "NorthParts": {"price": 7.5, "available": True, "delivery_days": 3},
        "SouthSupply": {"price": 7.8, "available": True, "delivery_days": 5},
    },
    "budget_limit": 1000.0,
    "budget_committed": 0.0,
    "authority_valid": True,
}


def _steps():
    price_a = make_assumption("price_at_most", supplier="NorthParts", max_price=8.0)
    headroom_a = make_assumption("budget_headroom_at_least", min_headroom=900.0)
    return [
        make_step(0, "verify_price", {"supplier": "NorthParts"}, [price_a]),
        make_step(1, "place_order", {"supplier": "NorthParts", "qty": 100}, [headroom_a]),
    ]


def test_no_contradictions_in_healthy_world():
    steps = _steps()
    events = [make_event(seq=1, ts="t", kind="delivery_delayed",
                         payload={"supplier": "SouthSupply", "days": 9})]
    assert detect_contradictions(steps, WORLD, events) == []


def test_contradiction_on_real_price_change_with_trigger_attribution():
    steps = _steps()
    event = make_event(seq=1, ts="2026-09-11T12:00:00Z", kind="price_changed",
                       payload={"supplier": "NorthParts", "new_price": 14.0})
    world = {**WORLD, "suppliers": {**WORLD["suppliers"], "NorthParts": {
        "price": 14.0, "available": True, "delivery_days": 3}}}
    contradictions = detect_contradictions(steps, world, [event])
    assert len(contradictions) == 1
    c = contradictions[0]
    assert c.assumption_kind == "price_at_most"
    assert c.step_id == steps[0].id
    assert c.triggering_event_ids == [event.id]


def test_irrelevant_event_yields_no_contradiction_and_no_trigger():
    """Change-blind: an event that doesn't touch any active assumption must
    produce zero contradictions — the anti-'re-prompt every N seconds' proof."""
    steps = _steps()
    event = make_event(seq=1, ts="t", kind="price_changed",
                       payload={"supplier": "SouthSupply", "new_price": 8.2})
    world = {**WORLD, "suppliers": {**WORLD["suppliers"], "SouthSupply": {
        "price": 8.2, "available": True, "delivery_days": 5}}}
    assert detect_contradictions(steps, world, [event]) == []


def test_executed_step_cascades_when_downstream_steps_pending():
    """A world change AFTER a step executed contradicts its assumption when
    later steps were planned on that reading — the cascade case."""
    steps = _steps()
    steps[0].status = "done"  # verify_price executed at $7.50
    world = {**WORLD, "suppliers": {**WORLD["suppliers"], "NorthParts": {
        "price": 14.0, "available": True, "delivery_days": 3}}}
    event = make_event(seq=1, ts="t", kind="price_changed",
                       payload={"supplier": "NorthParts", "new_price": 14.0})
    contradictions = detect_contradictions(steps, world, [event])
    assert len(contradictions) == 1
    assert contradictions[0].assumption_kind == "price_at_most"
    assert contradictions[0].step_id == steps[0].id  # attributed to the done step


def test_fully_executed_plan_is_not_relitigated():
    """History is not re-litigated: with nothing pending, a done step's broken
    assumption is not a contradiction (the mission already completed)."""
    steps = _steps()
    for s in steps:
        s.status = "done"
    world = {**WORLD, "suppliers": {**WORLD["suppliers"], "NorthParts": {
        "price": 14.0, "available": True, "delivery_days": 3}}}
    assert detect_contradictions(steps, world, []) == []


def test_budget_contradiction_from_live_committed():
    steps = _steps()
    event = make_event(seq=2, ts="t", kind="hold_placed", payload={"amount": 600.0})
    world = {**WORLD, "budget_committed": 600.0}
    contradictions = detect_contradictions(steps, world, [event])
    assert len(contradictions) == 1
    assert contradictions[0].assumption_kind == "budget_headroom_at_least"
    assert contradictions[0].triggering_event_ids == [event.id]


def test_event_stream_cursor():
    events = [make_event(seq=i, ts="t", kind="hold_placed", payload={"amount": i})
              for i in (1, 2, 3)]
    assert new_events(events, 0) == events
    assert new_events(events, 2) == [events[2]]
    assert advance_cursor(events, 0) == 3
    assert advance_cursor(events, 3) == 3  # no new events → cursor stays


def test_unknown_event_kind_rejected():
    import pytest

    with pytest.raises(ValueError):
        make_event(seq=1, ts="t", kind="meteor_strike", payload={})
