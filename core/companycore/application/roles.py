"""Role policies. Deterministic; they RETURN intents — the service gates and applies them."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from core.companycore.domain.ledger import CompanyState

RUNWAY_FREEZE_DAYS = 21.0
RUNWAY_CRITICAL_DAYS = 14.0
MARGIN = 1.4
UNIT_COST = 200.0
LOW_STOCK_FACTOR = 1.5


@dataclass
class RoleContext:
    day: int
    state: CompanyState
    kpis: dict[str, Any]
    keys: dict[str, str]
    emit: Callable[..., None]


def sales_step(ctx: RoleContext) -> list[dict[str, Any]]:
    if "salesbot" in ctx.state.roles_paused:
        return []
    open_leads = [
        {"lead_id": lid, **p}
        for lid, p in ctx.state.pipeline.items()
        if "quoted" not in p
    ]
    if not open_leads:
        return []
    lead = max(open_leads, key=lambda l: l.get("value", 0))
    amount = round(float(lead.get("units", 0)) * UNIT_COST * MARGIN, 2)
    return [{
        "action": "quote",
        "amount": amount,
        "description": f"quote {lead['lead_id']} to {lead.get('customer')}",
        "payload": {"lead_id": lead["lead_id"], "customer": lead.get("customer"),
                    "amount": amount, "units": lead.get("units", 0),
                    "unit_cost": UNIT_COST},
    }]


def ops_step(ctx: RoleContext) -> list[dict[str, Any]]:
    if "opsbot" in ctx.state.roles_paused:
        return []
    backlog = sum(int(p.get("units", 0)) for p in ctx.state.pipeline.values())
    inbound = 0  # POs are received same-day by the service; no separate inbound tracking
    shortfall = int(backlog * LOW_STOCK_FACTOR) - (ctx.state.inventory + inbound)
    if shortfall <= 0:
        return []
    cost = round(shortfall * UNIT_COST, 2)
    return [{
        "action": "purchase_order",
        "amount": cost,
        "description": f"restock {shortfall} units",
        "payload": {"units": shortfall, "cost": cost, "supplier": "SouthSupply",
                    "receive_day": ctx.day + 1, "due_day": ctx.day + 14},
    }]


def finance_step(ctx: RoleContext) -> list[dict[str, Any]]:
    if "financebot" in ctx.state.roles_paused:
        return []
    intents: list[dict[str, Any]] = []
    # collect every due invoice
    for inv in list(ctx.state.ar.values()):
        if int(inv.get("due_day", 0)) <= ctx.day:
            intents.append({
                "action": "collect", "amount": float(inv["amount"]),
                "description": f"collect {inv['invoice_id']} from {inv.get('customer')}",
                "payload": {"invoice_id": inv["invoice_id"], "amount": float(inv["amount"])},
            })
    # pay due bills unless frozen
    if not ctx.state.spend_frozen:
        for bill in list(ctx.state.ap.values()):
            if int(bill.get("due_day", 0)) <= ctx.day:
                intents.append({
                    "action": "pay", "amount": float(bill["amount"]),
                    "description": f"pay {bill['bill_id']} to {bill.get('supplier')}",
                    "payload": {"bill_id": bill["bill_id"], "amount": float(bill["amount"])},
                })
    # freeze on low runway
    if ctx.kpis["runway_days"] < RUNWAY_FREEZE_DAYS and not ctx.state.spend_frozen:
        intents.append({
            "action": "freeze_spend", "amount": None,
            "description": f"runway {ctx.kpis['runway_days']}d < {RUNWAY_FREEZE_DAYS}d",
            "payload": {"runway_days": ctx.kpis["runway_days"]},
        })
    return intents
