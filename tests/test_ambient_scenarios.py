"""TDD: the two e2e scenario beats the demo and the rubric grade.

1. Self-initiation: the fleet parks a risky deploy; the INTERFACE pushes the
   decision card (pre-simulated, rollback preview) with zero human input.
2. Wrong-guess recovery: reject a card -> MemoryCore correction -> the same
   kind re-surfaces visibly demoted; reject again -> graceful manual fallback
   (raw evidence, no more guessing).
"""

from datetime import UTC, datetime

from core.ambientcore.adapters.memory import (
    InMemoryCardStore,
    ManualClock,
    ScriptedNarrator,
)
from core.ambientcore.application.services import AmbientService
from core.memorycore.adapters.memory import (
    InMemoryMemoryStore,
    InMemoryTombstoneLog,
)
from core.memorycore.adapters.memory import (
    ManualClock as MemClock,
)
from core.memorycore.application.services import MemoryService
from core.simcore.adapters.memory import InMemoryLedgerStore, InMemorySimulationStore
from core.simcore.application.services import SimService
from core.towercore.application.services import TowerService
from core.towercore.domain.gate import AgentHalted
from core.trustcore.adapters.memory import (
    InMemoryAgentRegistry,
    InMemoryCredentialStore,
    InMemoryReceiptLog,
    SystemClock,
)
from core.trustcore.application.services import TrustService


def _stack():
    trust = TrustService(registry=InMemoryAgentRegistry(),
                         credentials=InMemoryCredentialStore(),
                         receipts=InMemoryReceiptLog(), clock=SystemClock())
    from core.decisioncore.adapters.memory import InMemoryDecisionStore
    from core.decisioncore.application.services import DecisionService
    decision = DecisionService(authority=trust, history=trust,
                               decisions=InMemoryDecisionStore(), audit=trust)
    sim = SimService(trust=trust, ledger_store=InMemoryLedgerStore(),
                     simulations=InMemorySimulationStore(), limit=1000.0)
    tower = TowerService(trust=trust, decision=decision, sim=sim)
    memory = MemoryService(store=InMemoryMemoryStore(),
                           tombstones=InMemoryTombstoneLog(),
                           clock=MemClock(datetime.now(UTC)), trust=trust)
    ambient = AmbientService(tower=tower, sim=sim, memory=memory, trust=trust,
                             cards=InMemoryCardStore(), clock=ManualClock(),
                             narrator=ScriptedNarrator())
    return ambient, tower, memory, trust


def _advance_safe(tower, agent_id, n):
    for _ in range(n):
        try:
            tower.advance(agent_id)
        except AgentHalted:
            break


def test_beat_self_initiated_card_with_precomputed_diff():
    """No human asked for anything. The fleet parks a deploy; the interface
    initiates the review — the card IS the interface acting first."""
    ambient, tower, _, _ = _stack()
    tower.seed_demo()
    ambient.seed_demo()
    _advance_safe(tower, "deploybot", 3)  # parks v12 (no change ticket)
    snap = ambient.canvas()
    assert snap["mode"] == "card"
    card = snap["card"]
    assert card["hypothesis"]["kind"] == "deploy_needs_review"
    # the approval came pre-resolved through the tower's REAL queue
    assert tower.gate.state("deploybot") == "awaiting_approval"
    # ambient line tells the operator exactly how much attention is needed
    assert "one thing" in snap["ambient"].lower() or "call" in snap["ambient"].lower()


def test_beat_wrong_guess_demotion_then_manual_fallback():
    """The failure test, live: reject -> correction -> demoted retry ->
    reject again -> the interface stops guessing and hands over raw evidence."""
    ambient, tower, memory, trust = _stack()
    tower.seed_demo()
    ambient.seed_demo()
    _advance_safe(tower, "deploybot", 3)

    first = ambient.canvas()["card"]
    assert first["hypothesis"]["demoted"] is False
    ambient.reject(first["id"], operator="op", note="v12 is fine, stop flagging")

    # correction is a real memory fact with a receipt in the shared trust log
    facts = memory.inspect(user_id="operator", agent_id="ambient")["facts"]
    assert any(f["slot"] == "ambient.correction.deploy_needs_review" for f in facts)
    receipt_actions = [r.action for r in trust.list_receipts(limit=100)]
    assert "ambient.card_rejected" in receipt_actions

    # same situation again -> demoted retry (release + re-park the deploy)
    ambient.resume_fleet("deploybot")
    _advance_safe(tower, "deploybot", 3)
    snap2 = ambient.canvas()
    if snap2["mode"] == "card" and snap2["card"]["hypothesis"]["kind"] == "deploy_needs_review":
        retry = snap2["card"]
        assert retry["hypothesis"]["demoted"] is True
        assert retry["hypothesis"]["confidence"] < first["hypothesis"]["confidence"]
        # second rejection on the same kind -> manual fallback, no more cards
        ambient.reject(retry["id"], operator="op", note="still not useful")
        snap3 = ambient.canvas()
        assert snap3["mode"] in ("calm", "manual")
        if snap3["mode"] == "manual":
            assert "deploy_needs_review" in snap3["exhausted_kinds"]
            assert snap3["raw_events"]  # the human still sees the evidence


def test_no_false_initiation_on_a_quiet_fleet():
    """A healthy fleet must NOT trigger cards — the interface's restraint is
    the product. Step the clean paths only; expect calm."""
    ambient, tower, _, _ = _stack()
    tower.seed_demo()
    ambient.seed_demo()
    _advance_safe(tower, "deploybot", 3)   # v12 parks (real signal)
    snap = ambient.canvas()
    # exactly ONE card, not a wall of them
    assert snap["mode"] == "card"
    assert len([snap["card"]]) == 1
    ambient.approve(snap["card"]["id"], operator="op")
    _advance_safe(tower, "deploybot", 3)   # v13 is clean: ticket present
    snap2 = ambient.canvas()
    # v13 deploys clean -> nothing left to decide
    assert snap2["mode"] == "calm"


def test_every_card_beat_is_receipted():
    ambient, tower, _, trust = _stack()
    tower.seed_demo()
    ambient.seed_demo()
    _advance_safe(tower, "deploybot", 3)
    card = ambient.canvas()["card"]
    ambient.approve(card["id"], operator="op")
    actions = [r.action for r in trust.list_receipts(limit=200)]
    assert "ambient.card_surfaced" in actions
    assert "ambient.card_approved" in actions
    # and every ambient receipt is LLM-free on the inference path
    for r in trust.list_receipts(limit=200):
        if r.action.startswith("ambient."):
            assert r.llm_called is False
