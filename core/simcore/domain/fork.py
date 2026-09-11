"""Fork: deep-copy the live stores into a plain-data snapshot.

The snapshot is the simulation sandbox: pure JSON-shaped data, no live
references. Mutating it can never touch live state — isolation is by
construction (deepcopy) and asserted in tests.
"""

import copy
from typing import Any, Protocol

from core.simcore.domain.ledger import BudgetLedger


class _LedgerSource(Protocol):
    def get(self) -> BudgetLedger: ...


def snapshot_store(trust_service: Any, ledger_store: _LedgerSource) -> dict[str, Any]:
    """Serialize live TrustCore + ledger state to a deep-copied snapshot.

    Reads through the services' public read surface — no private access,
    no I/O beyond what the in-memory adapters already do.
    """
    agents = trust_service.list_agents()
    credentials = [c.signed_payload() | {"signature": c.signature}
                   for c in trust_service.list_credentials()]
    return snapshot_parts(
        agents=agents,
        credentials=credentials,
        ledger_entries=[e.as_dict() for e in ledger_store.get().entries],
        receipts=trust_service.list_receipts(limit=10_000),
    )


def snapshot_parts(
    *,
    agents: list[dict[str, Any]],
    credentials: list[dict[str, Any]],
    ledger_entries: list[dict[str, Any]],
    receipts: list[Any],
) -> dict[str, Any]:
    """Assemble a snapshot from raw parts. Used by snapshot_store (live) and
    by SimService (forked stores) so both paths serialize identically."""
    receipt_dicts = [
        {
            "id": r.id,
            "ts": r.ts.isoformat(),
            "agent_id": r.agent_id,
            "action": r.action,
            "inputs": copy.deepcopy(r.inputs),
            "signals": copy.deepcopy(r.signals),
            "decision": str(r.decision),
            "reasoning": r.reasoning,
        }
        for r in receipts
    ]
    return copy.deepcopy(
        {
            "agents": agents,
            "credentials": credentials,
            "ledger": {"entries": ledger_entries},
            "receipts": receipt_dicts,
        }
    )
