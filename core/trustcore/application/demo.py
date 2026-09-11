"""The one-click demo scenario, as an application service.

Runs the six beats from demo/script.md entirely through TrustService, so the
HTTP endpoint is a thin adapter and the same scenario is testable in-process.
Generates fresh keypairs per run — safe to click repeatedly.
"""

from dataclasses import replace
from typing import Any

from core.trustcore.application.services import TrustService
from core.trustcore.domain.credentials import CredentialType
from core.trustcore.domain.crypto import KeyPair, sign_payload


def run_demo_scenario(svc: TrustService) -> dict[str, Any]:
    """Execute the demo; return a narration of beats for the UI."""
    beats: list[dict[str, Any]] = []

    acme, buyer, vendor, spoofer = (
        KeyPair.generate(),
        KeyPair.generate(),
        KeyPair.generate(),
        KeyPair.generate(),
    )
    for name, kp, owner in [
        ("BuyerBot", buyer, "Acme"),
        ("VendorBot", vendor, "Vendor Inc"),
        ("SpooferBot", spoofer, "unknown"),
    ]:
        svc.register_agent(name=name, public_key=kp.public_key_b64, owner=owner)
    beats.append({"label": "Registered BuyerBot, VendorBot, SpooferBot (fresh keypairs)"})

    svc.issue_credential(
        issuer=acme,
        subject_key=buyer.public_key_b64,
        type=CredentialType.AUTHORITY_GRANT,
        claim={"action": "purchase", "max_amount": 1000},
        scope={"actions": ["purchase"], "max_amount": 1000},
    )
    for _ in range(2):
        svc.issue_credential(
            issuer=vendor,
            subject_key=buyer.public_key_b64,
            type=CredentialType.TASK_COMPLETION,
            claim={"task": "prior purchase", "outcome": "completed"},
            scope={"actions": ["purchase"]},
        )
    beats.append({"label": "Acme granted BuyerBot purchase authority (≤ $1000); two vendors vouched"})

    r1 = svc.decide(
        requester_key=buyer.public_key_b64,
        action="purchase",
        amount=800,
        description="100 units @ $8",
    )
    beats.append({"label": "BuyerBot requests $800 purchase", "decision": str(r1.decision)})

    svc.issue_credential(
        issuer=vendor,
        subject_key=buyer.public_key_b64,
        type=CredentialType.TASK_COMPLETION,
        claim={"task": "purchase 100 units", "outcome": "completed"},
        scope={"actions": ["purchase"]},
    )
    beats.append({"label": "Task completed; VendorBot signed a new completion credential"})

    # forgery: well-formed credential claiming Acme as issuer, signed by spoofer
    forged = svc.issue_credential(
        issuer=spoofer,
        subject_key=spoofer.public_key_b64,
        type=CredentialType.AUTHORITY_GRANT,
        claim={"action": "purchase", "max_amount": 999999},
        scope={"actions": ["purchase"], "max_amount": 999999},
    )
    forged_as_acme = replace(forged, issuer_key=acme.public_key_b64)
    # plant at store level, as an attacker with network access would
    svc._credentials.save(forged_as_acme)
    r2 = svc.decide(requester_key=spoofer.public_key_b64, action="purchase", amount=800)
    beats.append({"label": "SpooferBot forged an Acme grant, tried to buy", "decision": str(r2.decision)})

    # scope escape with a real $50 grant
    svc.issue_credential(
        issuer=acme,
        subject_key=spoofer.public_key_b64,
        type=CredentialType.AUTHORITY_GRANT,
        claim={"action": "purchase", "max_amount": 50},
        scope={"actions": ["purchase"], "max_amount": 50},
    )
    r3 = svc.decide(requester_key=spoofer.public_key_b64, action="purchase", amount=800)
    beats.append({"label": "SpooferBot used a real $50 grant for an $800 purchase", "decision": str(r3.decision)})

    # revocation: issuer re-signs so the revoked credential stays verifiable
    authority = [
        c
        for c in svc.trust_profile(subject_key=buyer.public_key_b64)["credentials"]
        if c["type"] == "AuthorityGrant"
    ][0]
    cred = svc.get_credential(authority["id"])
    now = svc._clock.now()
    revoked = replace(cred, revoked_at=now, revocation_reason="Acme revoked — demo")
    from core.trustcore.domain.credentials import sign_credential

    svc.revoke_credential(
        credential_id=cred.id, reason="Acme revoked — demo", resigned=sign_credential(acme, revoked)
    )
    r4 = svc.decide(requester_key=buyer.public_key_b64, action="purchase", amount=800)
    beats.append({"label": "Acme revoked BuyerBot's authority; BuyerBot retried", "decision": str(r4.decision)})

    return {
        "beats": beats,
        "buyer_key": buyer.public_key_b64,
        "spoofer_key": spoofer.public_key_b64,
    }
