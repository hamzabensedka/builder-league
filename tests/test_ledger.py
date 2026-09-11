"""BudgetLedger domain: append-only money state with invariants.

The ledger is the real shared resource C8 gates. spend/hold/refund entries,
totals derived by pure functions, and the invariant that the post-execution
safety net enforces: spent + active holds <= limit.
"""

import pytest

from core.simcore.domain.ledger import (
    BudgetLedger,
    LedgerError,
    invariant_violations,
)


def _ledger() -> BudgetLedger:
    return BudgetLedger()


class TestEntries:
    def test_spend_appends_entry(self):
        ledger = _ledger()
        entry = ledger.spend(agent_key="buyer", amount=900.0, reference="sim-1")
        assert entry.kind == "spend"
        assert entry.amount == 900.0
        assert entry.reference == "sim-1"
        assert len(ledger.entries) == 1

    def test_hold_appends_active_hold(self):
        ledger = _ledger()
        ledger.hold(agent_key="vendor", amount=200.0, reference="sim-2")
        assert ledger.active_holds_total() == 200.0

    def test_refund_compensates_a_spend(self):
        ledger = _ledger()
        spend = ledger.spend(agent_key="buyer", amount=900.0, reference="sim-1")
        refund = ledger.refund(compensates=spend.id, agent_key="buyer", reference="rb-1")
        assert refund.kind == "refund"
        assert refund.compensates == spend.id
        assert refund.amount == spend.amount

    def test_refund_unknown_target_rejected(self):
        ledger = _ledger()
        with pytest.raises(LedgerError):
            ledger.refund(compensates="no-such-entry", agent_key="buyer", reference="rb-x")

    def test_refund_of_refund_rejected(self):
        ledger = _ledger()
        spend = ledger.spend(agent_key="buyer", amount=10.0, reference="s")
        refund = ledger.refund(compensates=spend.id, agent_key="buyer", reference="r1")
        with pytest.raises(LedgerError):
            ledger.refund(compensates=refund.id, agent_key="buyer", reference="r2")

    def test_negative_amounts_rejected(self):
        ledger = _ledger()
        with pytest.raises(LedgerError):
            ledger.spend(agent_key="buyer", amount=-5.0, reference="s")
        with pytest.raises(LedgerError):
            ledger.hold(agent_key="vendor", amount=0.0, reference="h")

    def test_append_only_no_update_or_delete(self):
        assert not hasattr(BudgetLedger, "update")
        assert not hasattr(BudgetLedger, "delete")
        assert not hasattr(BudgetLedger, "remove")


class TestTotals:
    def test_spent_minus_refunds(self):
        ledger = _ledger()
        spend = ledger.spend(agent_key="buyer", amount=900.0, reference="s1")
        ledger.refund(compensates=spend.id, agent_key="buyer", reference="rb")
        assert ledger.spent_total() == 0.0

    def test_projected_balance(self):
        ledger = _ledger()
        ledger.spend(agent_key="buyer", amount=300.0, reference="s1")
        ledger.hold(agent_key="vendor", amount=100.0, reference="h1")
        assert ledger.projected_balance() == 400.0


class TestInvariant:
    def test_no_violation_within_limit(self):
        ledger = _ledger()
        ledger.spend(agent_key="buyer", amount=900.0, reference="s1")
        assert invariant_violations(ledger, limit=1000.0) == []

    def test_violation_when_holds_push_over(self):
        """The C8 failure scenario: $900 spend was simulated fine, then a
        concurrent $200 hold pushed spent+holds over the $1000 limit."""
        ledger = _ledger()
        ledger.spend(agent_key="buyer", amount=900.0, reference="s1")
        ledger.hold(agent_key="vendor", amount=200.0, reference="h1")
        violations = invariant_violations(ledger, limit=1000.0)
        assert len(violations) == 1
        v = violations[0]
        assert v["spent"] == 900.0
        assert v["holds"] == 200.0
        assert v["limit"] == 1000.0
        assert v["excess"] == 100.0

    def test_violation_cleared_by_refund(self):
        ledger = _ledger()
        spend = ledger.spend(agent_key="buyer", amount=900.0, reference="s1")
        ledger.hold(agent_key="vendor", amount=200.0, reference="h1")
        assert invariant_violations(ledger, limit=1000.0)
        ledger.refund(compensates=spend.id, agent_key="buyer", reference="rb")
        assert invariant_violations(ledger, limit=1000.0) == []
