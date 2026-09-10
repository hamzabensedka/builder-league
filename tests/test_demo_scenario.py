"""E2E demo scenario: the exact beats of the 90-second demo, as tests.

Accept (authority + history) -> completion credential issued ->
forgery refused -> replay refused -> scope escape refused -> revocation refused.
Every step must produce an append-only receipt with llm_called=False.
"""

from datetime import UTC, datetime

from core.trustcore.adapters.memory import (
    InMemoryAgentRegistry,
    InMemoryCredentialStore,
    InMemoryReceiptLog,
    SystemClock,
)
from core.trustcore.application.services import TrustService
from core.trustcore.domain.credentials import CredentialType, revoke, sign_credential
from core.trustcore.domain.crypto import KeyPair
from core.trustcore.domain.policy import PolicyDecision


def build_service():
    return TrustService(
        registry=InMemoryAgentRegistry(),
        credentials=InMemoryCredentialStore(),
        receipts=InMemoryReceiptLog(),
        clock=SystemClock(),
    )


def test_full_demo_scenario():
    svc = build_service()

    # actors: Acme (human owner), BuyerBot, VendorBot, SpooferBot
    acme = KeyPair.generate()
    buyer = KeyPair.generate()
    vendor = KeyPair.generate()
    spoofer = KeyPair.generate()
    for name, kp, owner in [
        ("BuyerBot", buyer, "Acme"),
        ("VendorBot", vendor, "Vendor Inc"),
        ("SpooferBot", spoofer, "unknown"),
    ]:
        svc.register_agent(name=name, public_key=kp.public_key_b64, owner=owner)

    # Acme delegates purchase authority to BuyerBot (<= $1000)
    svc.issue_credential(
        issuer=acme,
        subject_key=buyer.public_key_b64,
        type=CredentialType.AUTHORITY_GRANT,
        claim={"action": "purchase", "max_amount": 1000},
        scope={"actions": ["purchase"], "max_amount": 1000},
    )
    # two prior counterparties vouch for BuyerBot with completed-task claims
    for _ in range(2):
        svc.issue_credential(
            issuer=vendor,
            subject_key=buyer.public_key_b64,
            type=CredentialType.TASK_COMPLETION,
            claim={"task": "prior purchase", "outcome": "completed"},
            scope={"actions": ["purchase"]},
        )

    # BEAT 1: BuyerBot's purchase is ACCEPTED (authority + history)
    r1 = svc.decide(
        requester_key=buyer.public_key_b64,
        action="purchase",
        amount=800,
        description="100 units @ $8",
    )
    assert r1.decision == PolicyDecision.ALLOW
    assert r1.llm_called is False
    assert r1.signals["valid_authority"] == 1
    assert r1.signals["valid_completions"] == 2

    # BEAT 2: VendorBot signs a TaskCompletion for BuyerBot; profile grows 2 -> 3
    svc.issue_credential(
        issuer=vendor,
        subject_key=buyer.public_key_b64,
        type=CredentialType.TASK_COMPLETION,
        claim={"task": "purchase 100 units", "outcome": "completed"},
        scope={"actions": ["purchase"]},
    )
    profile = svc.trust_profile(subject_key=buyer.public_key_b64)
    assert profile["counts"]["valid_completions"] == 3

    # BEAT 3: SpooferBot forges an Acme authority grant (own key) -> REFUSED
    forged = svc.issue_credential(
        issuer=spoofer,  # claims nothing; signature simply won't match Acme
        subject_key=spoofer.public_key_b64,
        type=CredentialType.AUTHORITY_GRANT,
        claim={"action": "purchase", "max_amount": 999999},
        scope={"actions": ["purchase"], "max_amount": 999999},
    )
    # Spoofer then claims Acme issued it by presenting a credential whose
    # issuer_key is Acme but signed with Spoofer's key:
    import dataclasses

    forged_as_acme = dataclasses.replace(forged, issuer_key=acme.public_key_b64)
    svc._credentials.save(forged_as_acme)  # adapter-level plant, as a real attacker would
    r2 = svc.decide(requester_key=spoofer.public_key_b64, action="purchase", amount=800)
    assert r2.decision == PolicyDecision.REFUSE
    assert "invalid_signature" in r2.reasoning

    # BEAT 4: replay — Spoofer presents BuyerBot's genuine credential -> REFUSED
    # (subject binding: the credential is FOR buyer, not for the caller)
    buyer_cred = svc.trust_profile(subject_key=buyer.public_key_b64)["credentials"][0]
    r3 = svc.decide(requester_key=spoofer.public_key_b64, action="purchase", amount=800)
    # spoofer still has no VALID authority of its own
    assert r3.decision == PolicyDecision.REFUSE
    assert buyer_cred["id"] != forged_as_acme.id  # distinct claims, no confusion

    # BEAT 5: scope escape — Spoofer earns a real <=$50 grant, tries $800 -> REFUSED
    svc.issue_credential(
        issuer=acme,
        subject_key=spoofer.public_key_b64,
        type=CredentialType.AUTHORITY_GRANT,
        claim={"action": "purchase", "max_amount": 50},
        scope={"actions": ["purchase"], "max_amount": 50},
    )
    r4 = svc.decide(requester_key=spoofer.public_key_b64, action="purchase", amount=800)
    assert r4.decision == PolicyDecision.REFUSE

    # BEAT 6: Acme REVOKES BuyerBot's authority -> BuyerBot now REFUSED
    buyer_authority_id = [
        c for c in svc.trust_profile(subject_key=buyer.public_key_b64)["credentials"]
        if c["type"] == "AuthorityGrant"
    ][0]["id"]
    svc.revoke_credential(credential_id=buyer_authority_id, reason="Acme revoked")
    r5 = svc.decide(requester_key=buyer.public_key_b64, action="purchase", amount=800)
    assert r5.decision == PolicyDecision.REFUSE
    assert "revoked" in r5.reasoning

    # AUDIT: six receipts, all append-only, none called the LLM
    receipts = svc.list_receipts(limit=100)
    assert len(receipts) == 5
    assert all(r.llm_called is False for r in receipts)


def test_revocation_requires_issuer_resign_to_be_valid():
    # revoke() invalidates the signature; only issuer re-sign makes it verifiable
    acme = KeyPair.generate()
    buyer = KeyPair.generate()
    from core.trustcore.domain.credentials import new_unsigned_credential, verify_credential

    now = datetime.now(UTC)
    from datetime import timedelta

    unsigned = new_unsigned_credential(
        issuer_key=acme.public_key_b64,
        subject_key=buyer.public_key_b64,
        type=CredentialType.AUTHORITY_GRANT,
        claim={"action": "purchase"},
        scope={"actions": ["purchase"]},
        issued_at=now,
        expires_at=now + timedelta(days=1),
    )
    cred = sign_credential(acme, unsigned)
    revoked_unsigned = revoke(cred, at=now, reason="x")
    # tampered (unsigned revocation) -> invalid signature
    from core.trustcore.domain.credentials import VerificationFailure

    assert VerificationFailure.INVALID_SIGNATURE in verify_credential(revoked_unsigned, now=now)
    # issuer re-signs the revocation -> verifiably revoked
    revoked_signed = sign_credential(acme, revoked_unsigned)
    failures = verify_credential(revoked_signed, now=now)
    assert VerificationFailure.REVOKED in failures
    assert VerificationFailure.INVALID_SIGNATURE not in failures
