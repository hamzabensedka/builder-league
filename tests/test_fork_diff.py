"""Fork isolation + diff correctness: the approval payload is a real
computed before/after diff of state, never a narration.
"""

from core.simcore.adapters.memory import InMemoryLedgerStore
from core.simcore.domain.diff import diff_snapshots
from core.simcore.domain.fork import snapshot_store
from core.simcore.domain.ledger import BudgetLedger
from core.trustcore.adapters.memory import (
    InMemoryAgentRegistry,
    InMemoryCredentialStore,
    InMemoryReceiptLog,
    SystemClock,
)
from core.trustcore.application.services import TrustService
from core.trustcore.domain.credentials import CredentialType
from core.trustcore.domain.crypto import KeyPair


def _seeded_trust() -> TrustService:
    svc = TrustService(
        registry=InMemoryAgentRegistry(),
        credentials=InMemoryCredentialStore(),
        receipts=InMemoryReceiptLog(),
        clock=SystemClock(),
    )
    acme = KeyPair.generate()
    buyer = KeyPair.generate()
    svc.register_agent(name="BuyerBot", public_key=buyer.public_key_b64, owner="Acme")
    svc.issue_credential(
        issuer=acme,
        subject_key=buyer.public_key_b64,
        type=CredentialType.AUTHORITY_GRANT,
        claim={"action": "purchase", "max_amount": 1000.0},
        scope={"actions": ["purchase"], "max_amount": 1000.0},
    )
    return svc


class TestForkIsolation:
    def test_snapshot_captures_state(self):
        svc = _seeded_trust()
        ledger_store = InMemoryLedgerStore(BudgetLedger())
        snap = snapshot_store(svc, ledger_store)
        assert len(snap["agents"]) == 1
        assert len(snap["credentials"]) == 1
        assert snap["ledger"]["entries"] == []
        assert snap["receipts"] == []

    def test_mutating_fork_leaves_live_untouched(self):
        svc = _seeded_trust()
        ledger_store = InMemoryLedgerStore(BudgetLedger())
        snap = snapshot_store(svc, ledger_store)
        # simulate a spend on the forked snapshot
        snap["ledger"]["entries"].append(
            {"id": "e1", "kind": "spend", "amount": 900.0, "agent_key": "buyer"}
        )
        snap["receipts"].append({"id": "r1"})
        # live state is unchanged
        live = snapshot_store(svc, ledger_store)
        assert live["ledger"]["entries"] == []
        assert live["receipts"] == []

    def test_deepcopy_not_reference(self):
        svc = _seeded_trust()
        ledger_store = InMemoryLedgerStore(BudgetLedger())
        snap = snapshot_store(svc, ledger_store)
        snap["agents"][0]["name"] = "MUTATED"
        assert svc.list_agents()[0]["name"] == "BuyerBot"


class TestDiff:
    def test_identical_snapshots_empty_diff(self):
        svc = _seeded_trust()
        ledger_store = InMemoryLedgerStore(BudgetLedger())
        a = snapshot_store(svc, ledger_store)
        b = snapshot_store(svc, ledger_store)
        assert diff_snapshots(a, b) == {}

    def test_diff_shows_new_ledger_entry(self):
        svc = _seeded_trust()
        ledger_store = InMemoryLedgerStore(BudgetLedger())
        before = snapshot_store(svc, ledger_store)
        after = snapshot_store(svc, ledger_store)
        after["ledger"]["entries"].append(
            {"id": "e1", "kind": "spend", "amount": 900.0, "agent_key": "buyer"}
        )
        diff = diff_snapshots(before, after)
        text = str(diff)
        assert "ledger" in text
        assert "e1" in text

    def test_diff_shows_new_receipt(self):
        svc = _seeded_trust()
        ledger_store = InMemoryLedgerStore(BudgetLedger())
        before = snapshot_store(svc, ledger_store)
        after = snapshot_store(svc, ledger_store)
        after["receipts"].append({"id": "rcpt-1", "decision": "allow"})
        diff = diff_snapshots(before, after)
        assert "rcpt-1" in str(diff)
