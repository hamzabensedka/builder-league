"""KPIs are a fold over the same log — the UI can never show state the spine didn't record."""

from typing import Any

from core.companycore.domain.events import CompanyEvent
from core.companycore.domain.ledger import fold_state


def kpis(events: list[CompanyEvent], *, current_day: int, daily_burn: float) -> dict[str, Any]:
    s = fold_state(events)
    revenue = sum(float(e.payload["amount"]) for e in events if e.kind == "invoice_issued")
    cogs = sum(float(e.payload.get("units", 0)) * float(e.payload.get("unit_cost", 0))
               for e in events if e.kind == "deal_won")
    paid = sum(float(e.payload["amount"]) for e in events if e.kind == "bill_paid")
    won = sum(1 for e in events if e.kind == "deal_won")
    lost = sum(1 for e in events if e.kind == "deal_lost")
    closed = won + lost
    backlog = sum(int(p.get("units", 0)) for p in s.pipeline.values())
    backlog += sum(int(v.get("units", 0)) for v in s.ar.values())
    burn = max(daily_burn, 1.0)
    return {
        "day": current_day,
        "cash": round(s.cash, 2),
        "revenue": round(revenue, 2),
        "cost": round(paid + daily_burn * (current_day + 1), 2),
        "cogs": round(cogs, 2),
        "margin": round((revenue - cogs) / revenue, 3) if revenue > 0 else 0.0,
        "churn": round(lost / closed, 3) if closed else 0.0,
        "backlog_units": backlog,
        "runway_days": round(s.cash / burn, 1),
        "spend_frozen": s.spend_frozen,
    }
