"""BudgetLedger — the real shared resource C8 gates.

Pure domain, zero I/O. Append-only: spend/hold/refund entries, never an
update or delete. Rollback is a compensating refund entry, so history is
never rewritten and the audit trail stays complete.

Invariant (the safety net): spent - refunded + active holds <= limit.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


class LedgerError(ValueError):
    """Raised on illegal ledger operations (bad amounts, unknown compensation targets)."""


@dataclass(frozen=True)
class LedgerEntry:
    id: str
    ts: datetime
    kind: str  # "hold" | "spend" | "refund"
    agent_key: str
    amount: float
    currency: str
    reference: str
    compensates: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "ts": self.ts.isoformat(),
            "kind": self.kind,
            "agent_key": self.agent_key,
            "amount": self.amount,
            "currency": self.currency,
            "reference": self.reference,
            "compensates": self.compensates,
        }


@dataclass
class BudgetLedger:
    """Append-only ledger. Deliberately exposes no update/delete."""

    entries: list[LedgerEntry] = field(default_factory=list)

    def _append(self, *, kind: str, agent_key: str, amount: float, reference: str,
                compensates: str | None = None) -> LedgerEntry:
        if amount <= 0:
            raise LedgerError(f"{kind} amount must be positive, got {amount}")
        entry = LedgerEntry(
            id=str(uuid.uuid4()),
            ts=datetime.now(UTC),
            kind=kind,
            agent_key=agent_key,
            amount=amount,
            currency="USD",
            reference=reference,
            compensates=compensates,
        )
        self.entries.append(entry)
        return entry

    def spend(self, *, agent_key: str, amount: float, reference: str) -> LedgerEntry:
        return self._append(kind="spend", agent_key=agent_key, amount=amount, reference=reference)

    def hold(self, *, agent_key: str, amount: float, reference: str) -> LedgerEntry:
        return self._append(kind="hold", agent_key=agent_key, amount=amount, reference=reference)

    def refund(self, *, compensates: str, agent_key: str, reference: str) -> LedgerEntry:
        """Compensating reversal of a prior spend/hold. Amount matches the
        compensated entry exactly — partial reversals are a new entry pair,
        not an edit."""
        target = next((e for e in self.entries if e.id == compensates), None)
        if target is None:
            raise LedgerError(f"cannot refund unknown entry {compensates}")
        if target.kind == "refund":
            raise LedgerError("cannot refund a refund")
        if any(e.kind == "refund" and e.compensates == compensates for e in self.entries):
            raise LedgerError(f"entry {compensates} already refunded")
        return self._append(
            kind="refund",
            agent_key=agent_key,
            amount=target.amount,
            reference=reference,
            compensates=compensates,
        )

    # --- derived totals (pure) -------------------------------------------

    def _refunded_ids(self) -> set[str]:
        return {e.compensates for e in self.entries if e.kind == "refund" and e.compensates}

    def spent_total(self) -> float:
        refunded = self._refunded_ids()
        return sum(
            e.amount for e in self.entries if e.kind == "spend" and e.id not in refunded
        )

    def active_holds_total(self) -> float:
        refunded = self._refunded_ids()
        return sum(e.amount for e in self.entries if e.kind == "hold" and e.id not in refunded)

    def projected_balance(self) -> float:
        """What will be committed if nothing changes: spent + active holds."""
        return self.spent_total() + self.active_holds_total()


def invariant_violations(ledger: BudgetLedger, *, limit: float) -> list[dict[str, Any]]:
    """The post-execution safety net. Pure function over live state:
    spent + active holds must not exceed the authority limit. Returns one
    violation record per breach (empty list = safe)."""
    spent = ledger.spent_total()
    holds = ledger.active_holds_total()
    if spent + holds <= limit:
        return []
    return [
        {
            "rule": "spent_plus_holds_within_limit",
            "spent": spent,
            "holds": holds,
            "limit": limit,
            "excess": round(spent + holds - limit, 2),
        }
    ]
