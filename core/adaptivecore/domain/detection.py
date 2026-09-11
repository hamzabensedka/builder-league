"""Change detection — deterministic re-verification of assumptions.

Pure domain, NO LLM, NO TIMER. The detector re-evaluates each ACTIVE
assumption against a WorldSnapshot and emits a Contradiction exactly when an
assumption fails. The application layer only calls this when new events
exist; irrelevant events yield zero contradictions (change-blindness is a
tested property, not a hope).

A WorldSnapshot is a plain dict assembled by the application layer from the
real world: supplier world store + the LIVE SimCore ledger (budget) + LIVE
TrustCore credentials (authority). Budget/authority checks therefore run
against enforced shared state, not a synthetic sandbox.
"""

from dataclasses import dataclass, field
from typing import Any

from core.adaptivecore.domain.events import WorldEvent
from core.adaptivecore.domain.plans import (
    AUTHORITY_VALID,
    BETTER_ALTERNATIVE,
    BUDGET_HEADROOM_AT_LEAST,
    DELIVERY_WITHIN_DAYS,
    PRICE_AT_MOST,
    SUPPLIER_AVAILABLE,
    Assumption,
    PlanStep,
)


@dataclass(frozen=True)
class Contradiction:
    assumption_id: str
    assumption_kind: str
    step_id: str
    statement: str
    expected: str
    observed: str
    severity: float  # normalized overshoot; feeds the damping min-delta gate
    critical: bool
    triggering_event_ids: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "assumption_id": self.assumption_id,
            "assumption_kind": self.assumption_kind,
            "step_id": self.step_id,
            "statement": self.statement,
            "expected": self.expected,
            "observed": self.observed,
            "severity": round(self.severity, 4),
            "critical": self.critical,
            "triggering_event_ids": list(self.triggering_event_ids),
        }


def _relevant(event: WorldEvent, a: Assumption) -> bool:
    """Does this event plausibly affect this assumption? (for attribution)"""
    p, k = event.payload, a.kind
    supplier = a.params.get("supplier")
    if event.kind == "price_changed":
        return k == PRICE_AT_MOST and p.get("supplier") == supplier
    if event.kind == "supplier_unavailable":
        affects = k in (SUPPLIER_AVAILABLE, PRICE_AT_MOST, DELIVERY_WITHIN_DAYS)
        return affects and p.get("supplier") == supplier
    if event.kind == "delivery_delayed":
        return k == DELIVERY_WITHIN_DAYS and p.get("supplier") == supplier
    if event.kind in ("hold_placed", "hold_released"):
        return k == BUDGET_HEADROOM_AT_LEAST
    if event.kind == "authority_revoked":
        return k == AUTHORITY_VALID and p.get("action") == a.params.get("action")
    if k == BETTER_ALTERNATIVE:
        # any price/availability move in the supplier market may open a
        # better alternative
        return event.kind in ("price_changed", "supplier_unavailable")
    return False


def check_assumption(a: Assumption, world: dict[str, Any],
                     events: list[WorldEvent]) -> Contradiction | None:
    """Re-verify ONE assumption against observed reality. Returns a
    Contradiction when it fails, else None. Pure function."""
    p = a.params
    suppliers: dict[str, dict[str, Any]] = world.get("suppliers", {})
    triggers = [e.id for e in events if _relevant(e, a)]

    if a.kind == PRICE_AT_MOST:
        s = suppliers.get(p["supplier"])
        price = s["price"] if s else None
        if s is None or not s.get("available", False):
            return None  # availability is a separate assumption's job
        # beyond cap → contradiction; near the cap (within warning window) →
        # unstable-world signal: the world keeps crossing the decision boundary
        warn_window = p["max_price"] * 1.03
        if price is not None and price <= p["max_price"] and price <= warn_window:
            return None
        if price is not None and price <= warn_window:
            severity = 0.05  # weak but real: inside tolerance, at the boundary
            return Contradiction(
                assumption_id=a.id, assumption_kind=a.kind, step_id="",
                statement=a.statement,
                expected=f"price ≤ {p['max_price']:.2f}",
                observed=f"price = {price:.2f} (within tolerance, at the boundary)",
                severity=severity, critical=False, triggering_event_ids=triggers,
            )
        severity = (price - p["max_price"]) / p["max_price"]
        return Contradiction(
            assumption_id=a.id, assumption_kind=a.kind, step_id="",
            statement=a.statement,
            expected=f"price ≤ {p['max_price']:.2f}",
            observed=f"price = {price:.2f}",
            severity=severity, critical=a.critical, triggering_event_ids=triggers,
        )

    if a.kind == SUPPLIER_AVAILABLE:
        s = suppliers.get(p["supplier"])
        if s is not None and s.get("available", False):
            return None
        return Contradiction(
            assumption_id=a.id, assumption_kind=a.kind, step_id="",
            statement=a.statement,
            expected="supplier available",
            observed="supplier unavailable",
            severity=1.0, critical=a.critical, triggering_event_ids=triggers,
        )

    if a.kind == BUDGET_HEADROOM_AT_LEAST:
        limit = float(world["budget_limit"])
        committed = float(world["budget_committed"])  # spent + active holds (live ledger)
        headroom = limit - committed
        if headroom >= p["min_headroom"]:
            return None
        return Contradiction(
            assumption_id=a.id, assumption_kind=a.kind, step_id="",
            statement=a.statement,
            expected=f"headroom ≥ {p['min_headroom']:.2f}",
            observed=f"headroom = {headroom:.2f} (committed {committed:.2f} of {limit:.2f})",
            severity=(p["min_headroom"] - headroom) / max(p["min_headroom"], 1e-9),
            critical=a.critical, triggering_event_ids=triggers,
        )

    if a.kind == AUTHORITY_VALID:
        if world.get("authority_valid", False):
            return None
        return Contradiction(
            assumption_id=a.id, assumption_kind=a.kind, step_id="",
            statement=a.statement,
            expected=f"valid authority for {p['action']}",
            observed="no valid signed grant (revoked/expired/forged)",
            severity=1.0, critical=a.critical, triggering_event_ids=triggers,
        )

    if a.kind == DELIVERY_WITHIN_DAYS:
        s = suppliers.get(p["supplier"])
        days = s.get("delivery_days") if s else None
        if days is not None and days <= p["max_days"]:
            return None
        return Contradiction(
            assumption_id=a.id, assumption_kind=a.kind, step_id="",
            statement=a.statement,
            expected=f"delivery ≤ {p['max_days']} days",
            observed=f"delivery = {days} days" if days is not None else "no delivery estimate",
            severity=((days or p["max_days"] * 2) - p["max_days"]) / max(p["max_days"], 1),
            critical=a.critical, triggering_event_ids=triggers,
        )

    if a.kind == BETTER_ALTERNATIVE:
        # non-critical stability signal: the plan's chosen supplier is no
        # longer the cheapest FEASIBLE option by more than the margin. Fires
        # when the world IMPROVED — the thing pure contradiction-detection
        # cannot see, and the raw material of oscillation.
        current = suppliers.get(p["supplier"])
        if current is None or not current.get("available", False):
            return None  # unavailability is SUPPLIER_AVAILABLE's job
        current_price = float(current["price"])
        price_cap = world.get("price_cap")
        limit = float(world.get("budget_limit", 0.0))
        headroom = limit - float(world.get("budget_committed", 0.0))
        max_days = p.get("max_days")
        best = None
        for name, s in suppliers.items():
            if not s.get("available", False):
                continue
            if max_days is not None and int(s.get("delivery_days", max_days + 1)) > max_days:
                continue
            price = float(s["price"])
            if price_cap is not None and price > price_cap:
                continue
            if price > 0 and int(headroom // price) <= 0:
                continue
            if best is None or price < best[1]:
                best = (name, price)
        if best is None or best[0] == p["supplier"]:
            return None
        if best[1] >= current_price * (1 - p["margin_pct"]):
            return None  # improvement below the margin: not worth churn
        return Contradiction(
            assumption_id=a.id, assumption_kind=a.kind, step_id="",
            statement=a.statement,
            expected=f"{p['supplier']} remains the best feasible supplier",
            observed=f"{best[0]} at ${best[1]:.2f} beats {p['supplier']} at ${current_price:.2f}",
            severity=(current_price - best[1]) / max(current_price, 1e-9),
            critical=a.critical, triggering_event_ids=triggers,
        )

    return None


def detect_contradictions(steps: list[PlanStep], world: dict[str, Any],
                          events: list[WorldEvent]) -> list[Contradiction]:
    """Re-verify assumptions against reality. Steps still ahead
    (pending/running) are always re-verified. A DONE step is re-verified too
    when its verdict feeds a step still pending (a cascade: the world changed
    AFTER the step executed, invalidating a decision built on its reading).
    Only NEW events (post-cursor) are attributed as triggers — change-blind
    by construction."""
    pending_exists = any(s.status in ("pending", "running") for s in steps)
    out: list[Contradiction] = []
    for step in steps:
        if step.status in ("pending", "running"):
            check = True
        elif step.status == "done" and pending_exists and step.assumptions:
            check = True  # cascade: re-verify executed steps that downstream steps rely on
        else:
            check = False
        if not check:
            continue
        for a in step.assumptions:
            c = check_assumption(a, world, events)
            if c is not None:
                out.append(Contradiction(
                    assumption_id=c.assumption_id, assumption_kind=c.assumption_kind,
                    step_id=step.id, statement=c.statement, expected=c.expected,
                    observed=c.observed, severity=c.severity, critical=c.critical,
                    triggering_event_ids=c.triggering_event_ids,
                ))
    return out
