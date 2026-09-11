"""Re-planner — contradictions → a revised plan, deterministically.

Pure domain, no LLM: revision is a RULE product over the contradicted
assumptions and the observed world. The same world state always yields the
same revised plan (asserted in tests). Each revised step carries fresh
explicit assumptions, so the loop closes: the new plan is itself verifiable.

Mission domain: procurement restock. World suppliers carry
{price, available, delivery_days}; the re-planner picks the best feasible
supplier (price within any surviving price cap implied by contradictions,
available, fastest delivery) and re-sizes the order to fit observed budget
headroom. If nothing is feasible, the re-planner returns None — the service
then escalates rather than inventing a plan.
"""

import uuid
from dataclasses import dataclass
from typing import Any

from core.adaptivecore.domain.detection import Contradiction
from core.adaptivecore.domain.plans import (
    PRICE_AT_MOST,
    Plan,
    PlanStep,
    make_assumption,
    make_step,
)


@dataclass(frozen=True)
class ReplanResult:
    plan: Plan | None  # None → infeasible, escalate
    rationale: str  # deterministic "I changed my mind because…" sentence


def _rationale(contradictions: list[Contradiction], new: Plan | None) -> str:
    causes = "; ".join(f"{c.statement} — observed {c.observed}" for c in contradictions)
    if new is None:
        return f"I stopped because {causes}; no feasible alternative exists."
    order = next((s for s in new.steps if s.action == "place_order"), None)
    if order:
        p = order.params
        return (
            f"I changed my mind because {causes}. "
            f"Revised plan: order {p['qty']} units from {p['supplier']} "
            f"at ${p['unit_price']:.2f} (total ${p['qty'] * p['unit_price']:.2f})."
        )
    return f"I changed my mind because {causes}."


def _fresh_steps(*, supplier: dict[str, Any], qty: int,
                 max_days: int, authority_action: str,
                 price_cap: float | None = None) -> list[PlanStep]:
    name = supplier["name"]
    price = float(supplier["price"])
    total = round(qty * price, 2)
    # The price assumption caps at the larger of (current price, world cap) —
    # a cap below the current price would be born contradicted.
    cap = max(price, price_cap or price)
    return [
        make_step(0, "verify_price", {"supplier": name, "expected_price": price},
                  [make_assumption(PRICE_AT_MOST, supplier=name, max_price=cap)]),
        make_step(1, "verify_authority", {"action": authority_action},
                  [make_assumption("authority_valid", action=authority_action)]),
        make_step(2, "place_order", {
            "supplier": name, "qty": qty, "unit_price": price, "total": total,
            "action": authority_action,
        }, [
            make_assumption("budget_headroom_at_least", min_headroom=total),
            make_assumption("supplier_available", supplier=name),
            make_assumption("authority_valid", action=authority_action),
            # non-critical: fires when the world IMPROVES enough to beat this
            # supplier — the stability signal that exposes oscillation
            make_assumption("better_alternative", critical=False, supplier=name,
                            margin_pct=0.02, max_days=max_days),
        ]),
        make_step(3, "schedule_delivery", {"supplier": name, "within_days": max_days},
                  [make_assumption("delivery_within_days", supplier=name, max_days=max_days)]),
        make_step(4, "confirm_restock", {"qty": qty, "supplier": name}, []),
    ]


def build_initial_plan(*, goal: str, qty: int, supplier: dict[str, Any],
                       max_days: int, authority_action: str,
                       price_cap: float | None = None) -> Plan:
    """The v1 plan for a restock mission. `price_cap` is the mission's world
    price tolerance (e.g. $8.00) — the assumption the run will defend."""
    from core.adaptivecore.domain.plans import initial_plan

    steps = _fresh_steps(
        supplier=supplier, qty=qty, max_days=max_days,
        authority_action=authority_action, price_cap=price_cap,
    )
    return initial_plan(goal=goal, steps=steps)


def revise_plan(
    *,
    current: Plan,
    contradictions: list[Contradiction],
    world: dict[str, Any],
    goal_qty: int,
    max_days: int,
    authority_action: str,
    revision_id: str,
    price_cap: float | None = None,
) -> ReplanResult:
    """Produce Plan vN+1 from the contradictions + observed world. Pure and
    deterministic: same inputs → same plan (ids aside, content identical).

    Contradiction cascade: a price contradiction on a DONE verify step means
    the downstream place_order was priced on a stale reading — the revision
    must carry a fresh price defense, not just new params."""
    cascade_price = any(
        c.assumption_kind == PRICE_AT_MOST
        and any(s.id == c.step_id and s.status == "done" for s in current.steps)
        for c in contradictions
    )
    """Produce Plan vN+1 from the contradictions + observed world. Pure and
    deterministic: same inputs → same plan (ids aside, content identical)."""
    suppliers = [
        {"name": name, **info}
        for name, info in sorted(world.get("suppliers", {}).items())
        if info.get("available", False)
    ]
    if not suppliers:
        return ReplanResult(plan=None, rationale=_rationale(contradictions, None))

    limit = float(world.get("budget_limit", 0.0))
    committed = float(world.get("budget_committed", 0.0))
    headroom = max(limit - committed, 0.0)

    feasible = []
    for s in suppliers:
        unit = float(s["price"])
        days = int(s.get("delivery_days", max_days + 1))
        if days > max_days:
            continue
        # the mission's price cap is a hard constraint: a supplier whose price
        # sits above the tolerance is not an alternative, it's the same problem
        if price_cap is not None and unit > price_cap:
            continue
        qty = min(goal_qty, int(headroom // unit)) if unit > 0 else 0
        if qty <= 0:
            continue
        feasible.append((unit, days, -qty, s, qty))

    if not feasible:
        return ReplanResult(plan=None, rationale=_rationale(contradictions, None))

    # cheapest first; ties → faster delivery → larger quantity
    feasible.sort(key=lambda t: (t[0], t[1], t[2]))
    unit, _days, _negqty, supplier, qty = feasible[0]

    # keep the current supplier if it is still feasible and cheapest-equal —
    # stability bias: don't churn suppliers without cause
    current_order = next((s for s in current.steps if s.action == "place_order"), None)
    if current_order:
        cur_name = current_order.params.get("supplier")
        cur = next((f for f in feasible if f[3]["name"] == cur_name), None)
        if cur is not None and abs(cur[0] - unit) < 1e-9:
            unit, _d, _nq, supplier, qty = cur

    steps = _fresh_steps(
        supplier=supplier, qty=qty, max_days=max_days,
        authority_action=authority_action, price_cap=price_cap,
    )
    # cascade: if the price assumption broke AFTER its verify step ran, the
    # revised plan defends the price on the (pending) place_order step itself.
    # The defense caps at the mission tolerance (price_cap), NOT the current
    # price — a supplier that drifted above the cap must stay contradicted.
    if cascade_price:
        order = next(s for s in steps if s.action == "place_order")
        order.assumptions.insert(
            0, make_assumption(PRICE_AT_MOST, supplier=supplier["name"],
                               max_price=price_cap or float(supplier["price"])),
        )
        # the carried-over verify step's stale assumption is superseded
        for s in steps:
            if s.action == "verify_price":
                s.assumptions = [
                    make_assumption(PRICE_AT_MOST, supplier=supplier["name"],
                                    max_price=price_cap or float(supplier["price"])),
                ]

    # preserve execution history: steps already done carry over as done.
    # Cascade: when a price contradiction broke AFTER a verify step ran, the
    # carried-over verify step defends the NEW supplier's price (its old
    # reading is exactly what got contradicted).
    done_by_action = {s.action: s for s in current.steps if s.status == "done"}
    merged = []
    for s in steps:
        carried = done_by_action.get(s.action)
        if carried is not None and cascade_price and s.action == "verify_price":
            carried.assumptions = [
                make_assumption(PRICE_AT_MOST, supplier=supplier["name"],
                                max_price=price_cap or float(supplier["price"])),
            ]
        merged.append(carried if carried is not None else s)

    new_plan = Plan(
        id=str(uuid.uuid4()),
        goal=current.goal,
        version=current.version + 1,
        steps=tuple(merged),
        supersedes=current.id,
        created_reason=revision_id,
    )
    return ReplanResult(plan=new_plan, rationale=_rationale(contradictions, new_plan))


def step_signature(step: PlanStep) -> str:
    return f"{step.action}({step.params})"
