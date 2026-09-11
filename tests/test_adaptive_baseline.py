"""A6: non-adaptive baseline — same world, same events, adaptation OFF.

The baseline is not a scripted animation: it runs the same steps against the
same real shared state. Where the adaptive run re-plans and recovers, the
baseline fails against state enforced by other modules (SimCore's budget
invariant, TrustCore's authority) — the before/after the rubric asks for.
"""

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
    return (InMemoryAgentRegistry(), InMemoryCredentialStore(),
            InMemoryReceiptLog(), SystemClock())


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
    acme, bot = KeyPair.generate(), KeyPair.generate()
    trust.register_agent(name="RestockBot", public_key=bot.public_key_b64, owner="Acme Ops")
    trust.issue_credential(
        issuer=acme, subject_key=bot.public_key_b64, type=CredentialType.AUTHORITY_GRANT,
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
    return svc


def _run_pair(svc, scenario, event_kind, event_payload):
    """One adaptive + one baseline run over the same scenario and event."""
    adaptive = svc.start_run(scenario=scenario, mode="adaptive")
    svc.inject_event(run_id=adaptive["id"], kind=event_kind, payload=event_payload)
    adaptive = svc.run_to_end(adaptive["id"])

    baseline = svc.start_run(scenario=scenario, mode="baseline")
    svc.inject_event(run_id=baseline["id"], kind=event_kind, payload=event_payload)
    baseline = svc.run_to_end(baseline["id"])
    return adaptive, baseline


def test_price_spike_adaptive_recovers_baseline_fails_silently(stack):
    adaptive, baseline = _run_pair(
        stack, "price_spike", "price_changed",
        {"supplier": "NorthParts", "new_price": 14.0},
    )
    # adaptive: re-planned to SouthSupply, completed within budget
    assert adaptive["status"] == "completed"
    assert len(adaptive["revisions"]) == 1

    # baseline: blind order at $14 — $1,400 against the $1,000 budget
    assert baseline["status"] == "escalated"
    assert baseline["revisions"] == []
    order = next(e for e in baseline["step_log"] if e["action"] == "place_order")
    assert order["post_check"]["ok"] is False
    assert order["post_check"]["violations"][0]["excess"] > 0
    assert "silent failure" in order["result"]
    # the breach was caught by SimCore's invariant math, not by AdaptiveCore
    assert order["post_check"]["violations"][0]["rule"] == "spent_plus_holds_within_limit"


def test_budget_squeeze_adaptive_partial_baseline_breaches(stack):
    adaptive, baseline = _run_pair(
        stack, "budget_squeeze", "hold_placed",
        {"amount": 600.0, "agent": "OtherTeamBot"},
    )
    # adaptive: re-sized to 53 units, completed — invariant holds
    assert adaptive["status"] == "completed"
    order_a = next(e for e in adaptive["step_log"] if e["action"] == "place_order")
    assert order_a["params"]["qty"] == 53
    assert order_a["post_check"]["ok"] is True

    # baseline: full 100 units at $7.50 on top of the $600 hold → breach
    assert baseline["status"] == "escalated"
    order_b = next(e for e in baseline["step_log"] if e["action"] == "place_order")
    assert order_b["params"]["qty"] == 100
    assert order_b["post_check"]["ok"] is False


def test_baseline_still_succeeds_when_nothing_changes(stack):
    """Honest control: with no contradiction, baseline and adaptive agree.
    The adaptive run's spend is compensated first so both runs face the same
    budget — the comparison is about adaptation, not accumulated state."""
    svc = stack
    adaptive = svc.start_run(scenario="price_spike", mode="adaptive")
    adaptive = svc.run_to_end(adaptive["id"])
    assert adaptive["status"] == "completed"
    # compensate the adaptive spend so the baseline gets the same budget
    spend_id = next(e["ledger_entry"] for e in adaptive["step_log"]
                    if e["action"] == "place_order" and e.get("ledger_entry"))
    svc._budget.refund(compensates=spend_id, agent_key=adaptive["agent_key"],
                       reference="control: reset budget for baseline comparison")
    baseline = svc.start_run(scenario="price_spike", mode="baseline")
    baseline = svc.run_to_end(baseline["id"])
    assert baseline["status"] == "completed"
    assert baseline["revisions"] == []


def test_baseline_supplier_gone_fails_at_execution(stack):
    svc = stack
    adaptive = svc.start_run(scenario="price_spike", mode="adaptive")
    svc.inject_event(run_id=adaptive["id"], kind="supplier_unavailable",
                     payload={"supplier": "NorthParts"})
    adaptive = svc.run_to_end(adaptive["id"])
    assert adaptive["status"] == "completed"  # re-planned to SouthSupply

    baseline = svc.start_run(scenario="price_spike", mode="baseline")
    svc.inject_event(run_id=baseline["id"], kind="supplier_unavailable",
                     payload={"supplier": "NorthParts"})
    baseline = svc.run_to_end(baseline["id"])
    assert baseline["status"] == "failed"
    order = next(e for e in baseline["step_log"] if e["action"] == "place_order")
    assert "supplier unavailable" in order["result"]
