"""Seeded world generators. Deterministic: same seed -> same week."""

import random
from typing import Any

CUSTOMERS = ["Acme", "Globex", "Initech", "Umbrella", "Hooli", "Stark"]


def _week(seed: int, crunch_day: int | None) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    days: list[dict[str, Any]] = []
    for d in range(7):
        leads = []
        for i in range(rng.randint(1, 2)):
            units = rng.choice([10, 20, 40])
            leads.append({
                "lead_id": f"L{d}{i}",
                "customer": rng.choice(CUSTOMERS),
                "value": units * 280,
                "units": units,
            })
        churn = []
        if crunch_day is not None and d == crunch_day:
            churn = [{"lead_id": f"L{d}9", "customer": "Acme", "value": 15000, "units": 60,
                      "reason": "churned", "cash_hit": 30000}]
            # a big supplier bill lands early
            days.append({"leads": leads, "churn": churn,
                         "early_bill": {"bill_id": f"BX{d}", "supplier": "SouthSupply",
                                        "amount": 12000, "due_day": d}})
            continue
        days.append({"leads": leads, "churn": churn, "early_bill": None})
    return days


def normal_week(seed: int = 7) -> list[dict[str, Any]]:
    return _week(seed, None)


def cash_crunch(seed: int = 7) -> list[dict[str, Any]]:
    return _week(seed, 2)
