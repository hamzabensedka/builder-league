"""Seed Northwind Components: real signed role authority + opening books."""

from collections.abc import Callable
from typing import Any

from core.trustcore.domain.credentials import CredentialType
from core.trustcore.domain.crypto import KeyPair

SCOPES = {
    "salesbot": (["quote"], 5000),
    "opsbot": (["purchase_order"], 8000),
    "financebot": (["payment"], 20000),
    "chiefofstaff": (["directive"], 0),
}


def seed_company(trust: Any, emit_opening: Callable[[str, str, dict], None]) -> dict[str, Any]:
    issuer = KeyPair.generate()
    keys: dict[str, str] = {}
    beats = []
    for role, (actions, max_amount) in SCOPES.items():
        kp = KeyPair.generate()
        trust.register_agent(name=role, public_key=kp.public_key_b64, owner="Northwind")
        scope: dict[str, Any] = {"actions": actions}
        if max_amount:
            scope["max_amount"] = max_amount
        trust.issue_credential(issuer=issuer, subject_key=kp.public_key_b64,
                               type=CredentialType.AUTHORITY_GRANT,
                               claim={"role": role, "actions": actions},
                               scope=scope, ttl_days=30)
        # completion history so decisions ALLOW rather than ESCALATE by default
        trust.issue_credential(issuer=issuer, subject_key=kp.public_key_b64,
                               type=CredentialType.TASK_COMPLETION,
                               claim={"task": f"{role} prior work", "outcome": "completed"},
                               scope={"actions": actions})
        keys[role] = kp.public_key_b64
    beats.append({"label": "four roles enrolled with signed, scoped authority"})

    # opening books: cash 50k, inventory 200, 2 AR, 1 AP
    emit_opening("seed", "invoice_collected", {"invoice_id": "SEED", "amount": 50000})
    emit_opening("seed", "po_received", {"po_id": "SEED-P", "units": 200, "bill_id": "SEED-B",
                                         "cost": 0, "due_day": 0, "supplier": "opening stock"})
    emit_opening("seed", "invoice_issued", {"invoice_id": "AR1", "deal_id": "D-AR1",
                                            "customer": "Acme", "amount": 4200, "due_day": 1,
                                            "units": 10})
    emit_opening("seed", "invoice_issued", {"invoice_id": "AR2", "deal_id": "D-AR2",
                                            "customer": "Globex", "amount": 2600, "due_day": 2,
                                            "units": 6})
    emit_opening("seed", "bill_received", {"bill_id": "AP1", "supplier": "SouthSupply",
                                           "amount": 3000, "due_day": 1})
    beats.append({"label": "opening books: $50k cash, 200 units, 2 invoices, 1 bill"})
    return {"keys": keys, "beats": beats}
