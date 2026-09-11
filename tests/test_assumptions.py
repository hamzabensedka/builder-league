"""A1: assumption value objects + every assumption kind's holds/violated readings."""

import pytest

from core.adaptivecore.domain.detection import check_assumption
from core.adaptivecore.domain.plans import (
    ALL_KINDS,
    initial_plan,
    make_assumption,
    make_step,
)

WORLD = {
    "suppliers": {
        "NorthParts": {"price": 7.5, "available": True, "delivery_days": 3},
        "SouthSupply": {"price": 7.8, "available": True, "delivery_days": 5},
    },
    "budget_limit": 1000.0,
    "budget_committed": 0.0,
    "authority_valid": True,
}


def test_every_kind_holds_in_healthy_world():
    assumptions = [
        make_assumption("price_at_most", supplier="NorthParts", max_price=8.0),
        make_assumption("budget_headroom_at_least", min_headroom=900.0),
        make_assumption("authority_valid", action="purchase"),
        make_assumption("supplier_available", supplier="NorthParts"),
        make_assumption("delivery_within_days", supplier="NorthParts", max_days=5),
        make_assumption("better_alternative", critical=False, supplier="NorthParts",
                        margin_pct=0.02, max_days=5),
    ]
    assert {a.kind for a in assumptions} == set(ALL_KINDS)
    world = {**WORLD, "price_cap": 8.0}
    for a in assumptions:
        assert check_assumption(a, world, []) is None, a.kind


def test_price_at_most_violated_with_severity_and_statement():
    a = make_assumption("price_at_most", supplier="NorthParts", max_price=8.0)
    world = {**WORLD, "suppliers": {**WORLD["suppliers"], "NorthParts": {
        "price": 14.0, "available": True, "delivery_days": 3}}}
    c = check_assumption(a, world, [])
    assert c is not None
    assert c.assumption_kind == "price_at_most"
    assert "≤" in c.statement and "8.00" in c.statement
    assert c.expected == "price ≤ 8.00"
    assert "14.00" in c.observed
    assert c.severity == pytest.approx((14.0 - 8.0) / 8.0)
    assert c.critical is True


def test_budget_headroom_violated_against_live_committed():
    a = make_assumption("budget_headroom_at_least", min_headroom=900.0)
    world = {**WORLD, "budget_committed": 600.0}
    c = check_assumption(a, world, [])
    assert c is not None
    assert "headroom = 400.00" in c.observed
    # holds again once the hold clears
    assert check_assumption(a, WORLD, []) is None


def test_authority_valid_violated():
    a = make_assumption("authority_valid", action="purchase")
    c = check_assumption(a, {**WORLD, "authority_valid": False}, [])
    assert c is not None
    assert c.severity == 1.0


def test_supplier_available_violated():
    a = make_assumption("supplier_available", supplier="NorthParts")
    world = {**WORLD, "suppliers": {**WORLD["suppliers"], "NorthParts": {
        "price": 7.5, "available": False, "delivery_days": 3}}}
    c = check_assumption(a, world, [])
    assert c is not None
    assert c.observed == "supplier unavailable"


def test_delivery_within_days_violated():
    a = make_assumption("delivery_within_days", supplier="NorthParts", max_days=2)
    c = check_assumption(a, WORLD, [])  # NorthParts delivers in 3 days
    assert c is not None
    assert "3 days" in c.observed


def test_unknown_assumption_kind_rejected():
    with pytest.raises(ValueError):
        make_assumption("vibes", foo=1)


def test_unknown_step_action_rejected():
    with pytest.raises(ValueError):
        make_step(0, "teleport", {})


def test_plan_versioning_never_mutates():
    steps = [make_step(0, "verify_price", {"supplier": "NorthParts", "expected_price": 7.5})]
    p1 = initial_plan(goal="restock 100 units", steps=steps)
    assert p1.version == 1 and p1.supersedes is None and p1.created_reason == "initial"
    # shape is deterministic and stable
    assert p1.shape() == p1.shape()
    d = p1.as_dict()
    assert d["shape"] == p1.shape() and d["steps"][0]["status"] == "pending"


def test_non_critical_assumption_flag():
    a = make_assumption("delivery_within_days", critical=False, supplier="NorthParts", max_days=5)
    assert a.critical is False
    assert a.as_dict()["critical"] is False
