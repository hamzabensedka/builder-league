"""Test harness: boot a TowerService over REAL TrustCore/DecisionCore/SimCore
instances, wired exactly like api/main.py's composition root. No mocks — the
tower's value is that the fleet acts on enforced state."""

from core.decisioncore.adapters.memory import InMemoryDecisionStore
from core.decisioncore.application.purchase_policy import PURCHASE
from core.decisioncore.application.services import DecisionService, make_authority_probe
from core.decisioncore.domain.policies import register_domain
from core.simcore.adapters.memory import InMemoryLedgerStore, InMemorySimulationStore
from core.simcore.application.services import SimService
from core.towercore.application.services import TowerService
from core.trustcore.adapters.memory import (
    InMemoryAgentRegistry,
    InMemoryCredentialStore,
    InMemoryReceiptLog,
    SystemClock,
)
from core.trustcore.application.services import TrustService


def boot_tower() -> tuple[TowerService, dict]:
    trust = TrustService(
        registry=InMemoryAgentRegistry(),
        credentials=InMemoryCredentialStore(),
        receipts=InMemoryReceiptLog(),
        clock=SystemClock(),
    )
    sim = SimService(
        trust=trust,
        ledger_store=InMemoryLedgerStore(),
        simulations=InMemorySimulationStore(),
        limit=1000.0,
    )

    def _trust_factory():
        return (
            InMemoryAgentRegistry(),
            InMemoryCredentialStore(),
            InMemoryReceiptLog(),
            SystemClock(),
        )

    import contextlib

    with contextlib.suppress(Exception):
        register_domain(PURCHASE)  # already registered by an earlier boot in-process

    decision = DecisionService(
        authority=trust,
        history=trust,
        decisions=InMemoryDecisionStore(),
        audit=trust,
        authority_probe=make_authority_probe(trust, _trust_factory),
    )

    tower = TowerService(trust=trust, decision=decision, sim=sim)
    return tower, {"trust": trust, "decision": decision, "sim": sim}
