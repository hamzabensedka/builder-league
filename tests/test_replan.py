"""A3 (replan): contradictions → deterministic revised plan."""

from core.adaptivecore.domain.detection import detect_contradictions
from core.adaptivecore.domain.events import make_event
from core.adaptivecore.domain.plans import initial_plan, make_assumption, make_step
from core.adaptivecore.domain.replan import build_initial_plan, revise_plan

SUPPLIERS = {
    "NorthParts": {"price": 7.5, "available": True, "delivery_days": 3},
    "SouthSupply": {"price": 7.8, "available": True, "delivery_days": 5},
}
WORLD = {
    "suppliers": SUPPLIERS,
    "budget_limit": 1000.0,
    "budget_committed": 0.0,
    "authority_valid": True,
}
KW = dict(goal_qty=100, max_days=7, authority_action="purchase", revision_id="rev-1")


def _initial():
    return build_initial_plan(
        goal="restock 100 units", qty=100,
        supplier={"name": "NorthParts", **SUPPLIERS["NorthParts"]},
        max_days=7, authority_action="purchase", price_cap=8.0,
    )


def test_initial_plan_structure():
    p = _initial()
    assert [s.action for s in p.steps] == [
        "verify_price", "verify_authority", "place_order", "schedule_delivery", "confirm_restock"
    ]
    order = p.steps[2]
    assert order.params == {
        "supplier": "NorthParts", "qty": 100, "unit_price": 7.5, "total": 750.0,
        "action": "purchase",
    }
    kinds = {a.kind for a in order.assumptions}
    assert kinds == {"budget_headroom_at_least", "supplier_available",
                     "authority_valid", "better_alternative"}
    ba = next(a for a in order.assumptions if a.kind == "better_alternative")
    assert ba.critical is False


def test_price_spike_replans_to_cheapest_feasible_supplier():
    p1 = _initial()
    world = {**WORLD, "suppliers": {**SUPPLIERS, "NorthParts": {
        "price": 14.0, "available": True, "delivery_days": 3}}}
    event = make_event(seq=1, ts="t", kind="price_changed",
                       payload={"supplier": "NorthParts", "new_price": 14.0})
    contradictions = detect_contradictions(list(p1.steps), world, [event])
    result = revise_plan(current=p1, contradictions=contradictions, world=world, **KW)
    assert result.plan is not None
    p2 = result.plan
    assert p2.version == 2 and p2.supersedes == p1.id and p2.created_reason == "rev-1"
    order = next(s for s in p2.steps if s.action == "place_order")
    assert order.params["supplier"] == "SouthSupply"
    assert order.params["qty"] == 100
    assert order.params["total"] == 780.0
    # the trace explains itself
    assert "I changed my mind because" in result.rationale
    assert "SouthSupply" in result.rationale
    # fresh assumptions on the revised plan close the loop
    price_step = next(s for s in p2.steps if s.action == "verify_price")
    assert price_step.assumptions[0].params["supplier"] == "SouthSupply"


def test_budget_squeeze_replans_to_partial_order():
    p1 = _initial()
    world = {**WORLD, "budget_committed": 600.0}  # $400 headroom left
    contradictions = detect_contradictions(list(p1.steps), world, [])
    result = revise_plan(current=p1, contradictions=contradictions, world=world, **KW)
    assert result.plan is not None
    order = next(s for s in result.plan.steps if s.action == "place_order")
    # 400 // 7.5 = 53 units from NorthParts (cheapest)
    assert order.params["supplier"] == "NorthParts"
    assert order.params["qty"] == 53
    assert order.params["total"] == 397.5
    assert "53 units" in result.rationale


def test_no_feasible_supplier_returns_none():
    p1 = _initial()
    world = {**WORLD, "suppliers": {
        "NorthParts": {"price": 7.5, "available": False, "delivery_days": 3},
        "SouthSupply": {"price": 7.8, "available": False, "delivery_days": 5},
    }}
    contradictions = detect_contradictions(list(p1.steps), world, [])
    result = revise_plan(current=p1, contradictions=contradictions, world=world, **KW)
    assert result.plan is None
    assert "no feasible alternative" in result.rationale


def test_zero_headroom_returns_none():
    p1 = _initial()
    world = {**WORLD, "budget_committed": 1000.0}
    contradictions = detect_contradictions(list(p1.steps), world, [])
    result = revise_plan(current=p1, contradictions=contradictions, world=world, **KW)
    assert result.plan is None


def test_replan_is_deterministic():
    p1 = _initial()
    world = {**WORLD, "suppliers": {**SUPPLIERS, "NorthParts": {
        "price": 14.0, "available": True, "delivery_days": 3}}}
    contradictions = detect_contradictions(list(p1.steps), world, [])
    r1 = revise_plan(current=p1, contradictions=contradictions, world=world, **KW)
    r2 = revise_plan(current=p1, contradictions=contradictions, world=world, **KW)
    o1 = next(s for s in r1.plan.steps if s.action == "place_order")
    o2 = next(s for s in r2.plan.steps if s.action == "place_order")
    assert o1.params == o2.params
    assert r1.plan.shape() == r2.plan.shape()
    assert r1.rationale == r2.rationale


def test_slow_supplier_excluded_by_max_days():
    p1 = _initial()
    suppliers = {
        "NorthParts": {"price": 14.0, "available": True, "delivery_days": 3},
        "SouthSupply": {"price": 7.8, "available": True, "delivery_days": 30},  # too slow
        "FastFreight": {"price": 8.4, "available": True, "delivery_days": 2},
    }
    world = {**WORLD, "suppliers": suppliers}
    contradictions = detect_contradictions(list(p1.steps), world, [])
    result = revise_plan(current=p1, contradictions=contradictions, world=world, **KW)
    order = next(s for s in result.plan.steps if s.action == "place_order")
    assert order.params["supplier"] == "FastFreight"


def test_stability_bias_keeps_current_supplier_when_equal():
    """Don't churn suppliers without cause: if the current supplier is still
    feasible and price-equal to the best alternative, keep it."""
    suppliers = {
        "NorthParts": {"price": 7.8, "available": True, "delivery_days": 3},
        "SouthSupply": {"price": 7.8, "available": True, "delivery_days": 5},
    }
    p1 = initial_plan(goal="restock", steps=[
        make_step(0, "place_order", {"supplier": "NorthParts", "qty": 100},
                  [make_assumption("budget_headroom_at_least", min_headroom=900.0)]),
    ])
    world = {**WORLD, "suppliers": suppliers, "budget_committed": 300.0}
    contradictions = detect_contradictions(list(p1.steps), world, [])
    assert contradictions  # headroom 700 < 900
    result = revise_plan(current=p1, contradictions=contradictions, world=world, **KW)
    order = next(s for s in result.plan.steps if s.action == "place_order")
    assert order.params["supplier"] == "NorthParts"
