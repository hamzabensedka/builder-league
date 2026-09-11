"""A5: AdaptiveService end-to-end — the plan/observe/revise loop, persisted,
composing real TrustCore/DecisionCore/SimCore surfaces."""

import pytest

from core.adaptivecore.adapters.memory import (
    DecisionStepGate,
    InMemoryEventStream,
    InMemoryPlanStore,
    InMemoryRevisionStore,
    InMemoryRunStore,
    InMemoryWorldStore,
    SimBudgetPort,
    SimStepPreview,
    TrustAuthorityPort,
)
from core.adaptivecore.application.services import AdaptiveService
from core.decisioncore.adapters.memory import InMemoryDecisionStore
from core.decisioncore.application.purchase_policy import PURCHASE
from core.decisioncore.application.services import DecisionService, make_authority_probe
from core.decisioncore.domain.policies import register_domain
from core.simcore.adapters.memory import InMemoryLedgerStore, InMemorySimulationStore
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

register_domain(PURCHASE)


def _trust_factory():
    return (
        InMemoryAgentRegistry(),
        InMemoryCredentialStore(),
        InMemoryReceiptLog(),
        SystemClock(),
    )


@pytest.fixture()
def stack():
    trust = TrustService(registry=InMemoryAgentRegistry(),
                         credentials=InMemoryCredentialStore(),
                         receipts=InMemoryReceiptLog(), clock=SystemClock())
    sim = SimService(trust=trust, ledger_store=InMemoryLedgerStore(),
                     simulations=InMemorySimulationStore(), limit=1000.0)
    decision = DecisionService(
        authority=trust, history=trust, decisions=InMemoryDecisionStore(),
        audit=trust, authority_probe=make_authority_probe(trust, _trust_factory),
    )

    acme = KeyPair.generate()
    bot = KeyPair.generate()
    trust.register_agent(name="RestockBot", public_key=bot.public_key_b64, owner="Acme Ops")
    trust.issue_credential(
        issuer=acme, subject_key=bot.public_key_b64,
        type=CredentialType.AUTHORITY_GRANT,
        claim={"action": "purchase", "max_amount": 1000},
        scope={"actions": ["purchase"], "max_amount": 1000},
    )
    for _ in range(4):
        trust.issue_credential(
            issuer=acme, subject_key=bot.public_key_b64,
            type=CredentialType.TASK_COMPLETION,
            claim={"task": "prior restock", "outcome": "completed"},
            scope={"actions": ["purchase"]},
        )

    svc = AdaptiveService(
        runs=InMemoryRunStore(), plans=InMemoryPlanStore(),
        events=InMemoryEventStream(), world=InMemoryWorldStore(),
        revisions=InMemoryRevisionStore(),
        budget=SimBudgetPort(sim), authority=TrustAuthorityPort(trust),
        gate=DecisionStepGate(decision), preview=SimStepPreview(sim),
        audit=trust, agent_key=bot.public_key_b64,
    )
    return svc, trust, sim, bot


def test_scenarios_listed(stack):
    svc, *_ = stack
    ids = {s["id"] for s in svc.list_scenarios()}
    assert ids == {"price_spike", "budget_squeeze", "flapping_price"}


def test_unknown_scenario_and_mode_rejected(stack):
    svc, *_ = stack
    with pytest.raises(ValueError):
        svc.start_run(scenario="nonsense", mode="adaptive")
    with pytest.raises(ValueError):
        svc.start_run(scenario="price_spike", mode="yolo")


def test_clean_run_completes_with_real_effects(stack):
    svc, trust, sim, bot = stack
    run = svc.start_run(scenario="price_spike", mode="adaptive")
    assert run["status"] == "running"
    assert run["plan"]["version"] == 1

    run = svc.run_to_end(run["id"])
    assert run["status"] == "completed"
    actions = [e["action"] for e in run["step_log"]]
    assert actions == ["verify_price", "verify_authority", "place_order",
                       "schedule_delivery", "confirm_restock"]
    # real spend on the shared ledger: 100 units × $7.50
    assert run["budget"]["committed"] == 750.0
    order = next(e for e in run["step_log"] if e["action"] == "place_order")
    assert order["gate_outcome"] == "execute"
    assert order["post_check"]["ok"] is True
    # receipted: run_started + run_completed + trust decision receipt
    actions_receipted = [r.action for r in trust.list_receipts(limit=100)]
    assert "run_started" in actions_receipted and "run_completed" in actions_receipted
    assert "purchase" in actions_receipted


def test_price_spike_contradiction_fires_replan_mid_run(stack):
    svc, trust, _, _ = stack
    run = svc.start_run(scenario="price_spike", mode="adaptive")
    # step 1 executes (verify_price ✓ at $7.50) — THEN the world changes
    run = svc.advance(run["id"])
    assert [e["action"] for e in run["step_log"]] == ["verify_price"]
    svc.inject_event(run_id=run["id"], kind="price_changed",
                     payload={"supplier": "NorthParts", "new_price": 14.0})
    run = svc.advance(run["id"])  # observe: contradiction → re-plan (no step)
    run = svc.run_to_end(run["id"])

    assert run["status"] == "completed"
    assert len(run["revisions"]) == 1
    rev = run["revisions"][0]

    # the "I changed my mind because…" trace is complete and machine-readable
    assert rev["from_version"] == 1 and rev["to_version"] == 2
    assert rev["contradictions"][0]["assumption_kind"] == "price_at_most"
    assert "14.00" in rev["contradictions"][0]["observed"]
    assert rev["triggering_events"][0]["kind"] == "price_changed"
    assert "I changed my mind because" in rev["rationale"]
    assert "SouthSupply" in rev["rationale"]
    assert rev["damping_verdict"] == "allowed"
    assert rev["receipt_id"] is not None

    # plan diff shows the supplier switch on the steps ahead
    supplier_changes = [c for c in rev["plan_diff"]["changed"]
                        if c["field"] == "supplier"]
    assert any(c["before"] == "NorthParts" and c["after"] == "SouthSupply"
               for c in supplier_changes)

    # revised place_order was gated + previewed before activation
    assert rev["gates"] and rev["gates"][0]["outcome"] == "execute"
    assert rev["sim_preview"]["predicted_effects"]["balance_after"] == 780.0

    # executed the REVISED plan: 100 × $7.80 from SouthSupply
    order = next(e for e in run["step_log"] if e["action"] == "place_order")
    assert order["params"]["supplier"] == "SouthSupply"
    assert run["budget"]["committed"] == 780.0

    # receipt resolves to a real entry in the append-only log
    receipt_ids = {r.id for r in trust.list_receipts(limit=200)}
    assert rev["receipt_id"] in receipt_ids


def test_no_event_no_revision(stack):
    """Identical advance without new events → zero revisions (no timer)."""
    svc, *_ = stack
    run = svc.start_run(scenario="price_spike", mode="adaptive")
    svc.run_to_end(run["id"])
    run = svc.get_run(run["id"])
    assert run["revisions"] == []
    assert len(run["plan_history"]) == 1


def test_irrelevant_event_no_revision(stack):
    """Change-blind: an event touching no active assumption must not re-plan."""
    svc, *_ = stack
    run = svc.start_run(scenario="price_spike", mode="adaptive")
    svc.inject_event(run_id=run["id"], kind="delivery_delayed",
                     payload={"supplier": "SouthSupply", "days": 9})
    run = svc.run_to_end(run["id"])
    assert run["status"] == "completed"
    assert run["revisions"] == []
    assert len(run["plan_history"]) == 1


def test_state_persisted_across_calls(stack):
    svc, *_ = stack
    run = svc.start_run(scenario="price_spike", mode="adaptive")
    svc.inject_event(run_id=run["id"], kind="price_changed",
                     payload={"supplier": "NorthParts", "new_price": 14.0})
    svc.run_to_end(run["id"])
    # re-read from the store — state is persisted, not recomputed
    fetched = svc.get_run(run["id"])
    assert fetched["status"] == "completed"
    assert len(fetched["plan_history"]) == 2
    assert fetched["plan_history"][0]["version"] == 1
    assert fetched["plan_history"][1]["version"] == 2
    assert fetched["event_cursor"] == 1


def test_determinism_identical_event_sequences(stack):
    """Two independent stacks, same scenario + same events → same revision
    content (ids/timestamps aside). Deterministic, not prompt-driven."""
    svc1, *_ = stack
    # build a second fully independent stack via the same fixture body
    svc2, *_ = _make_stack()

    def drive(svc):
        run = svc.start_run(scenario="price_spike", mode="adaptive")
        svc.inject_event(run_id=run["id"], kind="price_changed",
                         payload={"supplier": "NorthParts", "new_price": 14.0})
        return svc.run_to_end(run["id"])

    r1, r2 = drive(svc1), drive(svc2)
    assert r1["revisions"][0]["rationale"] == r2["revisions"][0]["rationale"]
    assert r1["revisions"][0]["plan_diff"]["summary"] == r2["revisions"][0]["plan_diff"]["summary"]
    assert r1["budget"]["committed"] == r2["budget"]["committed"]


def _make_stack():
    trust = TrustService(registry=InMemoryAgentRegistry(),
                         credentials=InMemoryCredentialStore(),
                         receipts=InMemoryReceiptLog(), clock=SystemClock())
    sim = SimService(trust=trust, ledger_store=InMemoryLedgerStore(),
                     simulations=InMemorySimulationStore(), limit=1000.0)
    decision = DecisionService(
        authority=trust, history=trust, decisions=InMemoryDecisionStore(),
        audit=trust, authority_probe=make_authority_probe(trust, _trust_factory),
    )
    acme, bot = KeyPair.generate(), KeyPair.generate()
    trust.register_agent(name="RestockBot", public_key=bot.public_key_b64, owner="Acme Ops")
    trust.issue_credential(
        issuer=acme, subject_key=bot.public_key_b64,
        type=CredentialType.AUTHORITY_GRANT,
        claim={"action": "purchase", "max_amount": 1000},
        scope={"actions": ["purchase"], "max_amount": 1000},
    )
    for _ in range(4):
        trust.issue_credential(
            issuer=acme, subject_key=bot.public_key_b64,
            type=CredentialType.TASK_COMPLETION,
            claim={"task": "prior restock", "outcome": "completed"},
            scope={"actions": ["purchase"]},
        )
    svc = AdaptiveService(
        runs=InMemoryRunStore(), plans=InMemoryPlanStore(),
        events=InMemoryEventStream(), world=InMemoryWorldStore(),
        revisions=InMemoryRevisionStore(),
        budget=SimBudgetPort(sim), authority=TrustAuthorityPort(trust),
        gate=DecisionStepGate(decision), preview=SimStepPreview(sim),
        audit=trust, agent_key=bot.public_key_b64,
    )
    return svc, trust, sim, bot


def test_authority_revocation_mid_run_blocks_replan(stack):
    """A re-plan can never self-authorize: revoke purchase authority mid-run
    and the revised plan's place_order gates to refuse/escalate → human."""
    svc, trust, _, bot = stack
    run = svc.start_run(scenario="price_spike", mode="adaptive")
    # revoke for real through TrustCore, then break the price assumption
    svc.inject_event(run_id=run["id"], kind="authority_revoked",
                     payload={"action": "purchase"})
    svc.inject_event(run_id=run["id"], kind="price_changed",
                     payload={"supplier": "NorthParts", "new_price": 14.0})
    run = svc.run_to_end(run["id"])
    assert run["status"] in ("awaiting_human", "escalated")
    rev = run["revisions"][0]
    if rev["gates"]:
        assert rev["gates"][0]["outcome"] in ("refuse", "escalate")
    # and nothing was spent
    assert run["budget"]["committed"] == 0.0


def test_hold_placed_event_writes_real_ledger_entry(stack):
    svc, _, sim, _ = stack
    run = svc.start_run(scenario="budget_squeeze", mode="adaptive")
    event = svc.inject_event(run_id=run["id"], kind="hold_placed",
                             payload={"amount": 600.0, "agent": "OtherTeamBot"})
    assert any("real write" in e for e in event["applied_effects"])
    # stale snapshot from before the event; re-read shows the real write
    assert svc.get_run(run["id"])["budget"]["committed"] == 600.0


def test_budget_squeeze_replans_to_partial_order(stack):
    svc, *_ = stack
    run = svc.start_run(scenario="budget_squeeze", mode="adaptive")
    svc.inject_event(run_id=run["id"], kind="hold_placed",
                     payload={"amount": 600.0, "agent": "OtherTeamBot"})
    run = svc.run_to_end(run["id"])
    assert run["status"] == "completed"
    rev = run["revisions"][0]
    assert rev["contradictions"][0]["assumption_kind"] == "budget_headroom_at_least"
    order = next(e for e in run["step_log"] if e["action"] == "place_order")
    assert order["params"]["qty"] == 53  # $400 headroom // $7.50
    # ledger: $600 hold + $397.50 spend = $997.50 ≤ $1000 — invariant holds
    assert run["budget"]["committed"] == 997.5
    assert order["post_check"]["ok"] is True


def test_unknown_run_raises(stack):
    svc, *_ = stack
    with pytest.raises(ValueError):
        svc.get_run("nope")
