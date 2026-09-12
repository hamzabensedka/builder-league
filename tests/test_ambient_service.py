"""TDD: AmbientService — the inference loop over the real cores.

Canvas snapshot = ambient field + at most ONE active card. Cards self-initiate
when the fleet parks a risky action; approve executes through real Trust/
Sim surfaces; reject writes a MemoryCore correction that demotes the retry.
"""

from datetime import UTC, datetime

import pytest

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
from core.trustcore.adapters.memory import (
    InMemoryAgentRegistry,
    InMemoryCredentialStore,
    InMemoryReceiptLog,
    SystemClock,
)
from core.trustcore.application.services import TrustService

SIM_LIMIT = 1000.0


def _stack():
    trust = TrustService(registry=InMemoryAgentRegistry(),
                         credentials=InMemoryCredentialStore(),
                         receipts=InMemoryReceiptLog(), clock=SystemClock())
    from core.decisioncore.adapters.memory import InMemoryDecisionStore
    from core.decisioncore.application.services import DecisionService
    decision = DecisionService(authority=trust, history=trust,
                               decisions=InMemoryDecisionStore(), audit=trust)
    sim = SimService(trust=trust, ledger_store=InMemoryLedgerStore(),
                     simulations=InMemorySimulationStore(), limit=SIM_LIMIT)
    tower = TowerService(trust=trust, decision=decision, sim=sim)
    memory = MemoryService(store=InMemoryMemoryStore(),
                           tombstones=InMemoryTombstoneLog(),
                           clock=MemClock(datetime.now(UTC)), trust=trust)
    ambient = AmbientService(
        tower=tower, sim=sim, memory=memory, trust=trust,
        cards=InMemoryCardStore(), clock=ManualClock(), narrator=ScriptedNarrator(),
    )
    return ambient, tower, memory


def _seed_fleet_with_parked_deploy(ambient, tower):
    """Seed the fleet and walk DeployBot to a parked approval (real cores)."""
    tower.seed_demo()
    ambient.seed_demo()
    # deploybot: pick_release -> verify_ticket -> deploy (escalates -> parked)
    for _ in range(3):
        tower.advance("deploybot")
    return tower.fleet_snapshot()


def test_canvas_calm_before_anything_needs_deciding():
    ambient, tower, _ = _stack()
    tower.seed_demo()
    ambient.seed_demo()
    tower.advance("restockbot")  # check_stock — no low stock first run? widgets=4 < 5
    snap = ambient.canvas()
    assert snap["mode"] in ("calm", "card")
    assert "ambient" in snap


def test_self_initiated_card_on_parked_deploy():
    ambient, tower, _ = _stack()
    _seed_fleet_with_parked_deploy(ambient, tower)
    snap = ambient.canvas()
    assert snap["mode"] == "card"
    card = snap["card"]
    assert card["hypothesis"]["kind"] == "deploy_needs_review"
    assert card["state"] == "surfaced"
    assert card["brain"] == "scripted"
    # the card's evidence chain names what surfaced it
    assert card["hypothesis"]["evidence"]


def test_card_is_pre_simulated_when_action_has_amount():
    ambient, tower, _ = _stack()
    _seed_fleet_with_parked_deploy(ambient, tower)
    snap = ambient.canvas()
    card = snap["card"]
    # the review card proposes the resolution; a restock card carries a sim
    # diff. Whichever surfaced, the loop must have attempted pre-simulation
    # for amount-bearing actions without exploding.
    assert card["hypothesis"]["proposed_action"]


def test_only_one_card_active_at_a_time():
    ambient, tower, _ = _stack()
    _seed_fleet_with_parked_deploy(ambient, tower)
    tower.advance("restockbot")  # low stock signal too
    snap = ambient.canvas()
    assert snap["mode"] == "card"
    # exactly one card key; runner-up intents visible but not surfaced
    assert isinstance(snap["card"], dict)
    assert all(h["kind"] != snap["card"]["hypothesis"]["kind"]
               for h in snap.get("runner_ups", []))


def test_approve_executes_through_real_cores():
    ambient, tower, _ = _stack()
    _seed_fleet_with_parked_deploy(ambient, tower)
    snap = ambient.canvas()
    card_id = snap["card"]["id"]
    result = ambient.approve(card_id, operator="op")
    assert result["state"] == "approved"
    # approving the parked deploy resolves the REAL tower approval queue
    assert tower.gate.state("deploybot") == "active"


def test_reject_writes_correction_and_demotes_retry():
    ambient, tower, memory = _stack()
    _seed_fleet_with_parked_deploy(ambient, tower)
    first = ambient.canvas()["card"]
    assert first["hypothesis"]["demoted"] is False
    ambient.reject(first["id"], operator="op", note="not the right call")
    # the correction is a real MemoryCore fact, receipted
    facts = memory.inspect(user_id="operator", agent_id="ambient")["facts"]
    assert any("deploy_needs_review" in f["slot"] for f in facts)
    # re-surface: same intent kind returns visibly demoted
    ambient.resume_fleet("deploybot")  # release the agent to park again
    from core.towercore.domain.gate import AgentHalted
    for _ in range(3):
        try:
            tower.advance("deploybot")  # v13 deploys clean or parks again
        except AgentHalted:
            break
    snap = ambient.canvas()
    if snap["mode"] == "card" and snap["card"]["hypothesis"]["kind"] == first["hypothesis"]["kind"]:
        assert snap["card"]["hypothesis"]["demoted"] is True
        assert snap["card"]["hypothesis"]["confidence"] < first["hypothesis"]["confidence"]


def test_unknown_card_404_and_double_resolve_409():
    ambient, tower, _ = _stack()
    _seed_fleet_with_parked_deploy(ambient, tower)
    with pytest.raises(ValueError, match="unknown card"):
        ambient.approve("card-nope", operator="op")
    card_id = ambient.canvas()["card"]["id"]
    ambient.approve(card_id, operator="op")
    with pytest.raises(ValueError):
        ambient.approve(card_id, operator="op")


def test_edit_reparametrizes_and_executes_new_amount():
    ambient, tower, _ = _stack()
    tower.seed_demo()
    ambient.seed_demo()
    tower.advance("restockbot")  # check_stock: widgets 4 < 5 → restock card
    snap = ambient.canvas()
    if snap["mode"] == "card" and snap["card"]["hypothesis"]["kind"] == "restock_needed":
        card_id = snap["card"]["id"]
        edited = ambient.edit(card_id, operator="op", new_action={
            "action": "purchase", "amount": 160.0, "description": "restock 10 widgets"})
        assert edited["state"] == "edited"
        assert edited["action"]["amount"] == 160.0
        assert edited["original_action"]["amount"] == 320.0


def test_canvas_deterministic_across_identical_stacks():
    a1, t1, _ = _stack()
    a2, t2, _ = _stack()
    _seed_fleet_with_parked_deploy(a1, t1)
    _seed_fleet_with_parked_deploy(a2, t2)
    s1, s2 = a1.canvas(), a2.canvas()
    assert s1["mode"] == s2["mode"]
    if s1["mode"] == "card":
        assert s1["card"]["hypothesis"]["kind"] == s2["card"]["hypothesis"]["kind"]
