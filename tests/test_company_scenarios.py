from datetime import UTC, datetime

from core.companycore.adapters.memory import InMemoryEventStore, ManualClock, ScriptedLLM
from core.companycore.application.services import CompanyService
from core.decisioncore.adapters.memory import InMemoryDecisionStore
from core.decisioncore.application.services import DecisionService
from core.memorycore.adapters.memory import InMemoryMemoryStore, InMemoryTombstoneLog
from core.memorycore.adapters.memory import ManualClock as MemClock
from core.memorycore.application.services import MemoryService
from core.trustcore.adapters.memory import (
    InMemoryAgentRegistry,
    InMemoryCredentialStore,
    InMemoryReceiptLog,
    SystemClock,
)
from core.trustcore.application.services import TrustService


def _svc():
    trust = TrustService(registry=InMemoryAgentRegistry(), credentials=InMemoryCredentialStore(),
                         receipts=InMemoryReceiptLog(), clock=SystemClock())
    decision = DecisionService(authority=trust, history=trust,
                               decisions=InMemoryDecisionStore(), audit=trust)
    memory = MemoryService(store=InMemoryMemoryStore(), tombstones=InMemoryTombstoneLog(),
                           clock=MemClock(datetime.now(UTC)), trust=trust)
    return CompanyService(events=InMemoryEventStore(), clock=ManualClock(),
                          llm=ScriptedLLM(), trust=trust, decision=decision, memory=memory)


def test_cash_crunch_self_corrects_without_human():
    svc = _svc()
    svc.seed_demo("cash_crunch")
    svc.advance_day(); svc.advance_day()  # day 2: churn + early bill
    svc.advance_day(); svc.advance_day()
    after = svc.kpis()
    kinds = [e["kind"] for e in svc.events()]
    assert "spend_frozen" in kinds
    assert after["runway_days"] is not None  # books stayed consistent


def test_rogue_sales_is_contained():
    svc = _svc()
    svc.seed_demo("normal")
    svc.inject_rogue_sales()
    for _ in range(4):
        svc.advance_day()
    kinds = [e["kind"] for e in svc.events()]
    assert "role_paused" in kinds  # sales auto-paused after refusal streak
    st = svc.state()
    assert "salesbot" in st["roles_paused"]


def test_over_scope_action_never_applies():
    svc = _svc()
    svc.seed_demo("normal")
    svc.inject_rogue_sales()
    svc.advance_day()
    # every won deal stayed within scope — rogue quotes were gated by trust
    for e in svc.events():
        if e["kind"] == "deal_won":
            assert e["payload"]["amount"] <= 15000
