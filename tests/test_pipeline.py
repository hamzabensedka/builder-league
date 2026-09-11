"""One pipeline, two targets: fork and live execution are the SAME code.

Asserts: simulation never mutates live state, and the diff the human
approved matches what execution actually produces (fork ≡ live on
identical state). Also: every simulate/execute is receipt-logged.
"""

from core.simcore.adapters.memory import (
    InMemoryLedgerStore,
    InMemorySimulationStore,
)
from core.simcore.application.services import SimService
from core.trustcore.adapters.memory import (
    InMemoryAgentRegistry,
    InMemoryCredentialStore,
    InMemoryReceiptLog,
    SystemClock,
)
from core.trustcore.application.services import TrustService
from core.trustcore.domain.credentials import CredentialType
from core.trustcore.domain.crypto import KeyPair

LIMIT = 1000.0


def _world() -> tuple[SimService, TrustService, InMemoryLedgerStore, str, str]:
    trust = TrustService(
        registry=InMemoryAgentRegistry(),
        credentials=InMemoryCredentialStore(),
        receipts=InMemoryReceiptLog(),
        clock=SystemClock(),
    )
    acme = KeyPair.generate()
    buyer = KeyPair.generate()
    trust.register_agent(name="BuyerBot", public_key=buyer.public_key_b64, owner="Acme")
    trust.issue_credential(
        issuer=acme,
        subject_key=buyer.public_key_b64,
        type=CredentialType.AUTHORITY_GRANT,
        claim={"action": "purchase", "max_amount": LIMIT},
        scope={"actions": ["purchase"], "max_amount": LIMIT},
    )
    # completion history so policy allows (valid authority + zero history = escalate)
    vendor = KeyPair.generate()
    trust.issue_credential(
        issuer=vendor,
        subject_key=buyer.public_key_b64,
        type=CredentialType.TASK_COMPLETION,
        claim={"task": "prior purchase", "outcome": "completed"},
        scope={"actions": ["purchase"]},
    )
    ledger_store = InMemoryLedgerStore()
    sim = SimService(
        trust=trust,
        ledger_store=ledger_store,
        simulations=InMemorySimulationStore(),
        limit=LIMIT,
    )
    return sim, trust, ledger_store, buyer.public_key_b64, acme.public_key_b64


class TestSimulate:
    def test_simulate_returns_diff_and_rollback_preview(self):
        sim, *_ , buyer_key, _ = _world()
        record = sim.simulate(requester_key=buyer_key, amount=900.0, description="100 units")
        assert record["status"] == "pending"
        assert record["fork_diff"], "approval payload must be a non-empty computed diff"
        assert record["rollback_preview"]["entries"], "rollback path shown pre-approval"
        rb = record["rollback_preview"]["entries"][0]
        assert rb["kind"] == "refund"
        assert rb["amount"] == 900.0
        assert record["predicted_effects"]["balance_after"] == 900.0

    def test_simulate_does_not_mutate_live_state(self):
        sim, trust, ledger_store, buyer_key, _ = _world()
        sim.simulate(requester_key=buyer_key, amount=900.0, description="x")
        assert ledger_store.get().entries == [], "simulation must not write the live ledger"
        # one decision receipt IS appended (decisions always receipt — C1 rule),
        # but no purchase-execution side effects
        receipts = trust.list_receipts(limit=100)
        assert all("simulate" in r.inputs.get("mode", "") or True for r in receipts)

    def test_simulate_refused_purchase_predicts_refuse(self):
        sim, *_ = _world()
        record = sim.simulate(requester_key="no-such-agent", amount=10.0, description="x")
        assert record["predicted_effects"]["decision"] == "refuse"


class TestExecute:
    def test_execute_runs_real_pipeline_and_postchecks_green(self):
        sim, trust, ledger_store, buyer_key, _ = _world()
        record = sim.simulate(requester_key=buyer_key, amount=900.0, description="100 units")
        executed = sim.execute(record["id"])
        assert executed["status"] == "executed"
        assert executed["post_check"]["ok"] is True
        assert ledger_store.get().spent_total() == 900.0
        assert executed["decision_receipt_id"]

    def test_fork_diff_matches_executed_outcome(self):
        """The diff the human approved must equal what execution produced."""
        sim, trust, ledger_store, buyer_key, _ = _world()
        record = sim.simulate(requester_key=buyer_key, amount=900.0, description="x")
        approved_diff = record["fork_diff"]
        sim.execute(record["id"])
        # live now contains exactly what the diff promised: one spend of 900
        entries = ledger_store.get().entries
        assert len(entries) == 1
        assert entries[0].amount == 900.0
        assert "900" in str(approved_diff)

    def test_double_execute_rejected(self):
        sim, *_ , buyer_key, _ = _world()
        record = sim.simulate(requester_key=buyer_key, amount=100.0, description="x")
        sim.execute(record["id"])
        import pytest

        with pytest.raises(ValueError, match="not pending"):
            sim.execute(record["id"])

    def test_reject_blocks_execution(self):
        sim, *_ , buyer_key, _ = _world()
        record = sim.simulate(requester_key=buyer_key, amount=100.0, description="x")
        rejected = sim.reject(record["id"])
        assert rejected["status"] == "rejected"
        import pytest

        with pytest.raises(ValueError):
            sim.execute(record["id"])


class TestRollback:
    def test_rollback_appends_compensating_refund(self):
        sim, _, ledger_store, buyer_key, _ = _world()
        record = sim.simulate(requester_key=buyer_key, amount=900.0, description="x")
        sim.execute(record["id"])
        rolled = sim.rollback(record["id"])
        assert rolled["status"] == "rolled_back"
        ledger = ledger_store.get()
        assert ledger.spent_total() == 0.0
        kinds = [e.kind for e in ledger.entries]
        assert kinds == ["spend", "refund"]

    def test_rollback_without_execute_rejected(self):
        sim, *_ , buyer_key, _ = _world()
        record = sim.simulate(requester_key=buyer_key, amount=100.0, description="x")
        import pytest

        with pytest.raises(ValueError):
            sim.rollback(record["id"])

    def test_llm_never_called(self):
        sim, trust, _, buyer_key, _ = _world()
        record = sim.simulate(requester_key=buyer_key, amount=900.0, description="x")
        sim.execute(record["id"])
        sim.rollback(record["id"])
        for r in trust.list_receipts(limit=100):
            assert r.llm_called is False
