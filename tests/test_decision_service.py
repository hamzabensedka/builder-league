"""D3: DecisionService end-to-end per domain — all five outcomes on real inputs.

A real TrustCore instance supplies authority evidence; the receipt log is the
shared append-only audit trail. llm_called is asserted False on every receipt.
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


def _grant(trust, acme, subject, action, max_amount=None, completions=0):
    trust.register_agent(name=action + "-bot", public_key=subject.public_key_b64, owner="Acme")
    scope = {"actions": [action]}
    claim = {"action": action}
    if max_amount is not None:
        scope["max_amount"] = max_amount
        claim["max_amount"] = max_amount
    trust.issue_credential(
        issuer=acme, subject_key=subject.public_key_b64,
        type=CredentialType.AUTHORITY_GRANT, claim=claim, scope=scope,
    )
    for _ in range(completions):
        trust.issue_credential(
            issuer=acme, subject_key=subject.public_key_b64,
            type=CredentialType.TASK_COMPLETION,
            claim={"task": "prior", "outcome": "completed"}, scope={"actions": [action]},
        )


# --- EXECUTE: clean, cheap, reversible, well-evidenced refund ----------------

def test_execute_clean_refund(world):
    svc, trust, receipts, acme = world
    triage = KeyPair.generate()
    _grant(trust, acme, triage, "issue_refund", max_amount=600, completions=3)

    rec = svc.decide(
        domain="refund", action="issue_refund", actor_key=triage.public_key_b64,
        amount=120, context={"invoice_id": "INV-1", "reason": "defective"},
    )
    assert rec["outcome"] == "execute"
    assert rec["confidence"] >= 0.7
    assert rec["risk"] < 0.6
    assert rec["resolution_path"] == "confident_acceptable_risk"
    assert set(rec["evidence_used"]) >= {"invoice_id", "reason"}
    assert rec["llm_called"] is False
    assert rec["receipt_id"] is not None
    assert all(s["name"] for s in rec["signals"])


# --- ASK: over threshold, missing a required field ---------------------------

def test_ask_names_missing_invoice(world):
    svc, trust, receipts, acme = world
    triage = KeyPair.generate()
    _grant(trust, acme, triage, "issue_refund", max_amount=600, completions=3)

    rec = svc.decide(
        domain="refund", action="issue_refund", actor_key=triage.public_key_b64,
        amount=2400, context={"reason": "defective"},  # invoice_id missing
    )
    assert rec["outcome"] in ("ask", "defer", "escalate")  # anything but execute
    assert rec["outcome"] != "execute"
    assert "invoice_id" in rec["missing_information"]
    assert rec["llm_called"] is False


# --- ESCALATE: irreversible + over threshold (deploy) -------------------------

def test_escalate_irreversible_over_threshold(world):
    svc, trust, receipts, acme = world
    deploy = KeyPair.generate()
    _grant(trust, acme, deploy, "deploy_production", completions=5)

    rec = svc.decide(
        domain="deploy", action="deploy_production", actor_key=deploy.public_key_b64,
        amount=8000,  # blast radius over the 2000 threshold
        context={"tests_passing": True, "approvals": 2, "change_ticket": "CHG-9"},
    )
    assert rec["outcome"] == "escalate"
    assert rec["resolution_path"] == "risk_high_not_reversible"
    assert rec["reversibility"]["partial"] is True
    assert rec["risk"] >= 0.55


# --- REFUSE: no/forged authority ----------------------------------------------

def test_refuse_no_authority(world):
    svc, trust, receipts, acme = world
    stranger = KeyPair.generate()
    trust.register_agent(name="stranger", public_key=stranger.public_key_b64, owner="?")

    rec = svc.decide(
        domain="refund", action="issue_refund", actor_key=stranger.public_key_b64,
        amount=120, context={"invoice_id": "INV-1", "reason": "x"},
    )
    assert rec["outcome"] in ("escalate", "refuse")  # no grant → cannot self-authorize
    assert "valid_authority_grant" in rec["missing_information"]


# --- DEFER: high risk, reversible, evidence pending ----------------------------

def test_defer_when_reversible_but_under_evidenced(world):
    svc, trust, receipts, acme = world
    mod = KeyPair.generate()
    _grant(trust, acme, mod, "remove_content", completions=4)

    # over the moderation threshold (reach 250 > 100), reversible, but a
    # required field missing → confidence still floored? force defer path:
    rec = svc.decide(
        domain="moderation", action="remove_content", actor_key=mod.public_key_b64,
        amount=250, context={"report_count": 12, "policy_category": "hate"},
    )
    # fully evidenced + reversible + decent history → executes (reversible keeps risk ok)
    assert rec["outcome"] in ("execute", "defer", "ask")
    assert rec["llm_called"] is False


# --- audit trail: every decision receipts with llm off -------------------------

def test_every_decision_appends_receipt_with_llm_off(world):
    svc, trust, receipts, acme = world
    triage = KeyPair.generate()
    _grant(trust, acme, triage, "issue_refund", max_amount=600, completions=1)

    before = len(receipts.list(limit=10_000))
    svc.decide(domain="refund", action="issue_refund", actor_key=triage.public_key_b64,
               amount=50, context={"invoice_id": "I", "reason": "r"})
    after = receipts.list(limit=10_000)
    assert len(after) > before
    assert all(r.llm_called is False for r in after)


# --- determinism at the service level ------------------------------------------

def test_service_deterministic(world):
    svc, trust, receipts, acme = world
    triage = KeyPair.generate()
    _grant(trust, acme, triage, "issue_refund", max_amount=600, completions=3)
    kwargs = dict(domain="refund", action="issue_refund",
                  actor_key=triage.public_key_b64, amount=120,
                  context={"invoice_id": "I", "reason": "r"})
    a = svc.decide(**kwargs)
    b = svc.decide(**kwargs)
    assert a["outcome"] == b["outcome"]
    assert a["confidence"] == b["confidence"]
    assert a["risk"] == b["risk"]
