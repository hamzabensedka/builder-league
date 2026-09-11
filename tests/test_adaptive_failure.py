"""A7: the failure test — adaptation goes WRONG (oscillation), contained.

NorthParts flaps $7.90 ↔ $8.10 around the plan's $8.00 assumption. A naive
adaptive agent would re-plan endlessly. AdaptiveCore contains it with
deterministic damping: min-delta hysteresis absorbs sub-margin flaps, the
revision budget caps re-plans, A→B→A oscillation detection escalates to a
human — every damping decision receipted and visible.
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
    return svc, trust


def _flap(svc, run_id, price):
    """Inject one price event, then observe (one advance). The run may also
    execute a step — steps still pending keep status 'running'."""
    svc.inject_event(run_id=run_id, kind="price_changed",
                     payload={"supplier": "NorthParts", "new_price": price})
    return svc.advance(run_id)


def test_flapping_price_oscillation_escalates_to_human(stack):
    """The core failure: NorthParts flaps across the $8 cap while SouthSupply
    sits at $7.60. Flap up → price contradiction → re-plan to SouthSupply;
    flap down → better-alternative signal → re-plan back to NorthParts. The
    third flap would re-select SouthSupply — the exact choice made two
    revisions ago (A→B→A) — so damping escalates to a human instead of
    flip-flopping forever."""
    svc, trust = stack
    run = svc.start_run(scenario="flapping_price", mode="adaptive")

    # flap up: 7.90 → 8.10 crosses the $8.00 cap — first real contradiction
    run = _flap(svc, run["id"], 8.1)
    revs = run["revisions"]
    assert run["status"] == "running"
    assert len(revs) == 1 and revs[0]["damping_verdict"] == "allowed"
    assert run["damping"]["revision_count"] == 1
    assert "SouthSupply" in revs[0]["rationale"]

    # flap down: 8.10 → 7.40 — NorthParts is now the better alternative;
    # the world IMPROVED, a signal pure contradiction-detection cannot see
    run = _flap(svc, run["id"], 7.4)
    assert run["status"] == "running"
    assert len(run["revisions"]) == 2
    assert run["revisions"][1]["damping_verdict"] == "allowed"
    assert run["revisions"][1]["contradictions"][0]["assumption_kind"] == "better_alternative"
    assert run["damping"]["revision_count"] == 2

    # flap up again: 7.40 → 8.10 — candidate re-plan reproduces the choice
    # from two revisions back: A→B→A → ESCALATE, do not flip a third time
    run = _flap(svc, run["id"], 8.1)
    assert run["status"] == "escalated"
    assert run["revisions"][-1]["damping_verdict"] == "escalate_oscillation"
    assert "A→B→A" in run["revisions"][-1]["damping_reason"]
    assert run["damping"]["revision_count"] == 2  # the flap was NOT re-planned

    # stability after escalation: more flaps change nothing
    run = _flap(svc, run["id"], 7.4)
    run = _flap(svc, run["id"], 8.1)
    assert run["status"] == "escalated"
    assert len(run["plan_history"]) == 3  # v1 + 2 allowed revisions, then frozen
    assert run["damping"]["revision_count"] == 2

    # the escalation and its reason are in the append-only receipt log
    escalations = [r for r in trust.list_receipts(limit=300) if r.action == "run_escalated"]
    assert escalations and "oscillation" in escalations[-1].reasoning


def test_hysteresis_absorbs_sub_margin_flap(stack):
    """Second containment: a price move below the min-delta threshold does not
    re-plan. SouthSupply flapping $7.60 → $7.70 (+1.3% < 2% margin) is noise;
    the agent stays put and the absorption is receipted."""
    svc, trust = stack
    run = svc.start_run(scenario="price_spike", mode="adaptive")
    # re-plan once to SouthSupply (real contradiction)
    svc.inject_event(run_id=run["id"], kind="price_changed",
                     payload={"supplier": "NorthParts", "new_price": 14.0})
    run = svc.advance(run["id"])
    assert run["revisions"][-1]["damping_verdict"] == "allowed"
    plan_versions = len(run["plan_history"])

    # SouthSupply price creeps up sub-margin; still within cap — but a repeat
    # boundary reading must not churn the plan
    svc.inject_event(run_id=run["id"], kind="price_changed",
                     payload={"supplier": "SouthSupply", "new_price": 7.7})
    run = svc.advance(run["id"])
    # no new plan version from a sub-margin move
    assert len(run["plan_history"]) == plan_versions
    assert run["status"] == "running"


def test_revision_budget_caps_replans(stack):
    """Third containment: the revision budget caps re-plans even for genuinely
    distinct contradictions; exceeding it escalates instead of churning."""
    svc, trust = stack
    run = svc.start_run(scenario="budget_squeeze", mode="adaptive")

    # three successive real holds: 600, then more — each shrinks headroom and
    # triggers an allowed revision with a different (smaller) order
    svc.inject_event(run_id=run["id"], kind="hold_placed",
                     payload={"amount": 400.0, "agent": "OtherTeamBot"})
    run = svc.advance(run["id"])
    assert run["revisions"][-1]["damping_verdict"] == "allowed"

    svc.inject_event(run_id=run["id"], kind="hold_placed",
                     payload={"amount": 300.0, "agent": "OtherTeamBot"})
    run = svc.advance(run["id"])
    assert run["revisions"][-1]["damping_verdict"] == "allowed"

    svc.inject_event(run_id=run["id"], kind="hold_placed",
                     payload={"amount": 200.0, "agent": "OtherTeamBot"})
    run = svc.advance(run["id"])
    assert run["revisions"][-1]["damping_verdict"] == "allowed"
    assert run["damping"]["revision_count"] == 3

    # the 4th contradiction exhausts the budget → escalate to a human
    svc.inject_event(run_id=run["id"], kind="hold_placed",
                     payload={"amount": 50.0, "agent": "OtherTeamBot"})
    run = svc.advance(run["id"])
    assert run["status"] == "escalated"
    assert run["revisions"][-1]["damping_verdict"] == "escalate_budget"
    assert "3/3" in run["revisions"][-1]["damping_reason"]

    notes = [r.reasoning for r in trust.list_receipts(limit=300)]
    assert any("budget" in n and "human" in n for n in notes)

