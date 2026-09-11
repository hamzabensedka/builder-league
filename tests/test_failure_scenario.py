"""The C8 failure test, end to end: simulation under-predicts a side
effect (TOCTOU on the shared budget) and the downstream safety net fires.

Sequence: simulate $900 vs $1000 limit (passes) → concurrent $200 hold
lands between simulate and execute → execute succeeds (decision is still
policy-valid) → post-execution invariant check catches 900+200 > 1000 →
escalated, rollback offered → rollback restores the invariant.
"""

from core.simcore.adapters.memory import (
    InMemoryLedgerStore,
    InMemorySimulationStore,
)
from core.simcore.application.services import SimService
from core.simcore.domain.ledger import invariant_violations
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


def _world():
    trust = TrustService(
        registry=InMemoryAgentRegistry(),
        credentials=InMemoryCredentialStore(),
        receipts=InMemoryReceiptLog(),
        clock=SystemClock(),
    )
    acme = KeyPair.generate()
    buyer = KeyPair.generate()
    vendor = KeyPair.generate()
    trust.register_agent(name="BuyerBot", public_key=buyer.public_key_b64, owner="Acme")
    trust.register_agent(name="VendorBot", public_key=vendor.public_key_b64, owner="Acme")
    grant = trust.issue_credential(
        issuer=acme,
        subject_key=buyer.public_key_b64,
        type=CredentialType.AUTHORITY_GRANT,
        claim={"action": "purchase", "max_amount": LIMIT},
        scope={"actions": ["purchase"], "max_amount": LIMIT},
    )
    # completion history so policy allows (authority + zero history = escalate)
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
    return sim, trust, ledger_store, buyer.public_key_b64, vendor.public_key_b64, grant


def test_simulation_passes_then_concurrent_hold_trips_postcheck():
    sim, trust, ledger_store, buyer_key, vendor_key, grant = _world()

    # 1. Simulate $900 against $1000 — no holds exist, passes.
    record = sim.simulate(requester_key=buyer_key, amount=900.0, description="bulk order")
    assert record["predicted_effects"]["decision"] == "allow"
    assert record["status"] == "pending"

    # 2. Between simulate and execute, a DIFFERENT actor places a real
    #    $200 hold through the real ledger. The simulation could not see it.
    sim.place_hold(agent_key=vendor_key, amount=200.0, reference="vendor-reservation")

    # 3. Human approves the (now stale) simulation. Execution succeeds —
    #    BuyerBot's authority genuinely covers $900.
    executed = sim.execute(record["id"])

    # 4. The post-execution invariant check catches the under-predicted
    #    side effect: 900 spent + 200 hold > 1000 limit.
    assert executed["status"] == "escalated"
    assert executed["post_check"]["ok"] is False
    violations = executed["post_check"]["violations"]
    assert violations[0]["excess"] == 100.0
    assert executed["rollback_preview"]["entries"], "rollback offered on escalation"

    # 5. Rollback: compensating refund + authority revocation, invariant restored.
    rolled = sim.rollback(record["id"])
    assert rolled["status"] == "rolled_back"
    ledger = ledger_store.get()
    assert invariant_violations(ledger, limit=LIMIT) == []
    # the authority that enabled the purchase was revoked through TrustCore
    revoked = trust.get_credential(grant.id)
    assert revoked is not None and revoked.revoked_at is not None

    # 6. Full forensic chain in the receipt log: simulate, execute, escalate,
    #    rollback — every step receipt-logged.
    refs = [r.inputs.get("simulation_id") for r in trust.list_receipts(limit=100)]
    assert record["id"] in refs
    events = [r.action for r in trust.list_receipts(limit=100)]
    assert "purchase" in events  # the real gated decision
    assert any("rollback" in a or "escalat" in a for a in events)


def test_postcheck_green_without_concurrent_hold():
    sim, _, ledger_store, buyer_key, _, _ = _world()
    record = sim.simulate(requester_key=buyer_key, amount=900.0, description="x")
    executed = sim.execute(record["id"])
    assert executed["status"] == "executed"
    assert executed["post_check"]["ok"] is True
