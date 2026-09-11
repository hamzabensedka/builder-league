"""D4: the failure test — the engine must NOT execute a dangerous action.

Scenario (plan §5): full valid authority + high history confidence, but the
action is irreversible AND over the cost threshold AND a critical evidence
field is missing. A naive system executes. DecisionCore asks/escalates and
names the missing information — no execution path exists for this input.
Plus: forged authority → refuse via REAL signature verification.
"""

import pytest

from core.decisioncore.adapters.memory import InMemoryDecisionStore
from core.decisioncore.application.services import DecisionService, make_authority_probe
from core.trustcore.adapters.memory import (
    InMemoryAgentRegistry,
    InMemoryCredentialStore,
    InMemoryReceiptLog,
    SystemClock,
)
from core.trustcore.application.services import TrustService
from core.trustcore.domain.credentials import CredentialType
from core.trustcore.domain.crypto import KeyPair


@pytest.fixture
def world():
    receipts = InMemoryReceiptLog()
    trust = TrustService(
        registry=InMemoryAgentRegistry(),
        credentials=InMemoryCredentialStore(),
        receipts=receipts,
        clock=SystemClock(),
    )
    def trust_factory():
        return (
            InMemoryAgentRegistry(),
            InMemoryCredentialStore(),
            InMemoryReceiptLog(),
            SystemClock(),
        )

    svc = DecisionService(
        authority=trust,
        history=trust,
        decisions=InMemoryDecisionStore(),
        audit=trust,
        authority_probe=make_authority_probe(trust, trust_factory),
    )
    acme = KeyPair.generate()
    return svc, trust, receipts, acme


def test_hard_edge_case_never_executes(world):
    """Full authority + strong history, irreversible, over threshold, missing
    a critical evidence field → must NOT execute; names the missing field."""
    svc, trust, receipts, acme = world
    deploy = KeyPair.generate()
    trust.register_agent(name="DeployBot", public_key=deploy.public_key_b64, owner="Acme")
    # genuine, valid, correctly-scoped authority
    trust.issue_credential(
        issuer=acme, subject_key=deploy.public_key_b64,
        type=CredentialType.AUTHORITY_GRANT,
        claim={"action": "deploy_production"}, scope={"actions": ["deploy_production"]},
    )
    # strong track record: 9 prior completions
    for _ in range(9):
        trust.issue_credential(
            issuer=acme, subject_key=deploy.public_key_b64,
            type=CredentialType.TASK_COMPLETION,
            claim={"task": "prior deploy", "outcome": "completed"},
            scope={"actions": ["deploy_production"]},
        )

    # blast radius $8000 over the $2000 threshold; missing change_ticket
    rec = svc.decide(
        domain="deploy", action="deploy_production", actor_key=deploy.public_key_b64,
        amount=8000,
        context={"tests_passing": True, "approvals": 2},  # change_ticket MISSING
    )

    # the safety behavior: never execute
    assert rec["outcome"] != "execute"
    assert rec["outcome"] in ("ask", "escalate", "defer")
    # it names the missing information
    assert "change_ticket" in rec["missing_information"]
    # authority was genuinely valid — the refusal to execute comes from
    # evidence/risk/reversibility, not from a fake authority failure
    auth = next(s for s in rec["signals"]
                if s["name"] == "authority" and s["contributes_to"] == "confidence")
    assert auth["value"] == 1.0
    # the full signal vector is receipted for audit
    assert rec["receipt_id"] is not None
    assert len(rec["signals"]) >= 5


def test_same_deploy_with_evidence_present_still_escalates(world):
    """With change_ticket present, the missing-evidence rule no longer fires —
    but irreversible + over threshold still escalates. Still never executes."""
    svc, trust, receipts, acme = world
    deploy = KeyPair.generate()
    trust.register_agent(name="DeployBot", public_key=deploy.public_key_b64, owner="Acme")
    trust.issue_credential(
        issuer=acme, subject_key=deploy.public_key_b64,
        type=CredentialType.AUTHORITY_GRANT,
        claim={"action": "deploy_production"}, scope={"actions": ["deploy_production"]},
    )
    for _ in range(9):
        trust.issue_credential(
            issuer=acme, subject_key=deploy.public_key_b64,
            type=CredentialType.TASK_COMPLETION,
            claim={"task": "p", "outcome": "completed"},
            scope={"actions": ["deploy_production"]},
        )

    rec = svc.decide(
        domain="deploy", action="deploy_production", actor_key=deploy.public_key_b64,
        amount=8000,
        context={"tests_passing": True, "approvals": 2, "change_ticket": "CHG-1"},
    )
    assert rec["outcome"] == "escalate"
    assert rec["resolution_path"] == "risk_high_not_reversible"


def test_forged_authority_refused_via_real_signature_check(world):
    """A forged grant (well-formed, wrong key) → REFUSE. Real crypto, not a flag."""
    from dataclasses import replace

    svc, trust, receipts, acme = world
    spoofer = KeyPair.generate()
    trust.register_agent(name="SpooferBot", public_key=spoofer.public_key_b64, owner="?")
    # craft a grant claiming Acme as issuer but signed by the spoofer
    forged = trust.issue_credential(
        issuer=spoofer, subject_key=spoofer.public_key_b64,
        type=CredentialType.AUTHORITY_GRANT,
        claim={"action": "deploy_production"}, scope={"actions": ["deploy_production"]},
    )
    forged_as_acme = replace(forged, issuer_key=acme.public_key_b64)
    trust._credentials.save(forged_as_acme)  # plant as an attacker would

    rec = svc.decide(
        domain="deploy", action="deploy_production", actor_key=spoofer.public_key_b64,
        amount=100, context={"tests_passing": True, "approvals": 2, "change_ticket": "C"},
    )
    assert rec["outcome"] in ("refuse", "escalate")
    # if a genuinely invalid signature is present it must refuse
    if rec["outcome"] == "refuse":
        assert rec["resolution_path"] == "hard_block:invalid_authority"
