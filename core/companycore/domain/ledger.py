"""Pure fold: events -> company state. Replay is a cutoff fold."""

from dataclasses import dataclass, field
from typing import Any

from core.companycore.domain.events import CompanyEvent


@dataclass
class CompanyState:
    cash: float = 0.0
    inventory: int = 0
    pipeline: dict[str, dict[str, Any]] = field(default_factory=dict)
    ar: dict[str, dict[str, Any]] = field(default_factory=dict)
    ap: dict[str, dict[str, Any]] = field(default_factory=dict)
    spend_frozen: bool = False
    roles_paused: set[str] = field(default_factory=set)

    def as_dict(self) -> dict[str, Any]:
        return {
            "cash": round(self.cash, 2),
            "inventory": self.inventory,
            "pipeline": self.pipeline,
            "ar": self.ar,
            "ap": self.ap,
            "spend_frozen": self.spend_frozen,
            "roles_paused": sorted(self.roles_paused),
        }


def fold_state(events: list[CompanyEvent]) -> CompanyState:
    s = CompanyState()
    for e in sorted(events, key=lambda x: x.seq):
        p = e.payload
        if e.kind == "lead_arrived":
            s.pipeline[p["lead_id"]] = dict(p)
        elif e.kind == "quote_sent":
            s.pipeline.setdefault(p["lead_id"], {})["quoted"] = p["amount"]
        elif e.kind == "deal_won":
            s.pipeline.pop(p["lead_id"], None)
            s.inventory -= int(p.get("units", 0))
        elif e.kind == "deal_lost":
            s.pipeline.pop(p["lead_id"], None)
        elif e.kind == "invoice_issued":
            s.ar[p["invoice_id"]] = dict(p)
        elif e.kind == "invoice_collected":
            s.cash += float(p["amount"])
            s.ar.pop(p["invoice_id"], None)
        elif e.kind == "po_received":
            s.inventory += int(p.get("units", 0))
            s.ap[p["bill_id"]] = {"bill_id": p["bill_id"], "amount": p["cost"],
                                  "due_day": p.get("due_day", 0), "supplier": p.get("supplier", "")}
        elif e.kind == "bill_received":
            s.ap[p["bill_id"]] = dict(p)
        elif e.kind == "bill_paid":
            s.cash -= float(p["amount"])
            s.ap.pop(p["bill_id"], None)
        elif e.kind == "spend_frozen":
            s.spend_frozen = True
        elif e.kind == "spend_unfrozen":
            s.spend_frozen = False
        elif e.kind == "role_paused":
            s.roles_paused.add(p["role"])
        elif e.kind == "role_restored":
            s.roles_paused.discard(p["role"])
    return s


def replay_day(events: list[CompanyEvent], day: int) -> CompanyState:
    return fold_state([e for e in events if e.day <= day])
