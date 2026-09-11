"""A3 (plandiff): structural diffs computed, never narrated."""

from core.adaptivecore.domain.plandiff import diff_plans
from core.adaptivecore.domain.plans import initial_plan, make_step


def _plan(supplier="NorthParts", qty=100, price=7.5, version=1, supersedes=None):
    steps = [
        make_step(0, "verify_price", {"supplier": supplier, "expected_price": price}),
        make_step(1, "verify_authority", {"action": "purchase"}),
        make_step(2, "place_order", {"supplier": supplier, "qty": qty,
                                     "unit_price": price, "total": qty * price}),
        make_step(3, "schedule_delivery", {"supplier": supplier, "within_days": 7}),
        make_step(4, "confirm_restock", {"qty": qty, "supplier": supplier}),
    ]
    return initial_plan(goal="restock", steps=steps) if version == 1 else \
        __import__("core.adaptivecore.domain.plans", fromlist=["Plan"]).Plan(
            id="p2", goal="restock", version=version, steps=tuple(steps),
            supersedes=supersedes, created_reason="rev",
        )


def test_supplier_switch_diff_shows_changed_fields():
    p1 = _plan("NorthParts", 100, 7.5)
    p2 = _plan("SouthSupply", 100, 7.8, version=2, supersedes="p1")
    diff = diff_plans(p1, p2)
    assert diff.added == [] and diff.removed == []
    fields = {(c.action, c.field) for c in diff.changed}
    assert ("place_order", "supplier") in fields
    assert ("place_order", "unit_price") in fields
    assert ("place_order", "total") in fields
    order_change = next(c for c in diff.changed
                        if c.action == "place_order" and c.field == "supplier")
    assert order_change.before == "NorthParts" and order_change.after == "SouthSupply"
    assert "NorthParts → SouthSupply" in diff.summary


def test_qty_change_diff():
    p1 = _plan(qty=100)
    p2 = _plan(qty=53, version=2, supersedes="p1")
    diff = diff_plans(p1, p2)
    qty_change = next(c for c in diff.changed
                      if c.action == "place_order" and c.field == "qty")
    assert qty_change.before == 100 and qty_change.after == 53


def test_added_and_removed_steps():
    p1 = _plan()
    steps = list(p1.steps[:3])  # drop delivery + confirm
    from core.adaptivecore.domain.plans import Plan
    p2 = Plan(id="p2", goal="restock", version=2, steps=tuple(steps),
              supersedes=p1.id, created_reason="rev")
    diff = diff_plans(p1, p2)
    removed_actions = {s.action for s in diff.removed}
    assert removed_actions == {"schedule_delivery", "confirm_restock"}
    assert diff.added == []


def test_identical_plans_empty_diff():
    p1 = _plan()
    p2 = _plan(version=2, supersedes="p1")
    diff = diff_plans(p1, p2)
    assert diff.added == [] and diff.removed == [] and diff.changed == []
    assert diff.summary == "no structural change"


def test_diff_serializes():
    p1, p2 = _plan(), _plan("SouthSupply", version=2, supersedes="p1")
    d = diff_plans(p1, p2).as_dict()
    assert set(d) == {"added", "removed", "changed", "summary"}
    assert all(set(c) == {"step_id", "action", "field", "before", "after"} for c in d["changed"])
