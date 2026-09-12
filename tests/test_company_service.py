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


def _stack():
    trust = TrustService(registry=InMemoryAgentRegistry(), credentials=InMemoryCredentialStore(),
                         receipts=InMemoryReceiptLog(), clock=SystemClock())
    decision = DecisionService(authority=trust, history=trust,
                               decisions=InMemoryDecisionStore(), audit=trust)
    memory = MemoryService(store=InMemoryMemoryStore(), tombstones=InMemoryTombstoneLog(),
                           clock=MemClock(datetime.now(UTC)), trust=trust)
    svc = CompanyService(events=InMemoryEventStore(), clock=ManualClock(),
                         llm=ScriptedLLM(), trust=trust, decision=decision, memory=memory)
    return svc


def test_seed_demo_creates_roles_and_opening_state():
    svc = _stack()
    result = svc.seed_demo("normal")
    assert set(result["keys"]) >= {"salesbot", "opsbot", "financebot", "chiefofstaff"}
    st = svc.state()
    assert st["cash"] == 50000
    assert st["inventory"] == 200


def test_advance_day_moves_numbers():
    svc = _stack()
    svc.seed_demo("normal")
    before = svc.kpis()
    svc.advance_day()
    after = svc.kpis()
    assert after["day"] == before["day"] + 1
    assert after["revenue"] >= before["revenue"]


def test_replay_day_returns_earlier_state():
    svc = _stack()
    svc.seed_demo("normal")
    svc.advance_day(); svc.advance_day()
    day1 = svc.replay(1)
    day2 = svc.replay(2)
    assert day1["cash"] != day2["cash"] or day1["inventory"] != day2["inventory"]


def test_inbox_roundtrip():
    svc = _stack()
    svc.seed_demo("normal")
    svc.advance_day()
    box = svc.inbox()
    if box:
        res = svc.resolve_inbox(box[0]["id"], "approved")
        assert res["resolved"] is True


def test_chief_of_staff_brain_label():
    svc = _stack()
    svc.seed_demo("normal")
    out = svc.advance_day()
    assert out["chief_brain"] in ("llm", "scripted")
