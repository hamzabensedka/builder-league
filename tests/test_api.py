"""HTTP integration: FastAPI adapter over the real TrustService.

Credentials are signed CLIENT-side (the server never holds private keys);
mutating endpoints are request-signature gated. RED first, per TDD.
"""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from api.main import create_app
from core.trustcore.domain.credentials import Credential, CredentialType
from core.trustcore.domain.crypto import KeyPair, sign_payload


def boot():
    return TestClient(create_app())


def register(client, name, kp, owner):
    r = client.post(
        "/api/trust/agents",
        json={"name": name, "public_key": kp.public_key_b64, "owner": owner},
    )
    assert r.status_code == 201, r.text
    return r.json()["agent_id"]


def issue(client, issuer: KeyPair, subject: KeyPair, ctype, claim, scope):
    """Build + sign a credential locally, then POST it for verification+storage."""
    now = datetime.now(UTC)
    cred = Credential(
        id=str(uuid.uuid4()),
        issuer_key=issuer.public_key_b64,
        subject_key=subject.public_key_b64,
        type=CredentialType(ctype),
        claim=claim,
        scope=scope,
        issued_at=now,
        expires_at=now + timedelta(days=30),
        revoked_at=None,
        revocation_reason=None,
        signature="",
    )
    signed = sign_payload(issuer, cred.signed_payload())
    body = {**cred.signed_payload(), "signature": signed}
    r = client.post("/api/trust/credentials", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def decide(client, key: str, action="purchase", amount=800):
    r = client.post(
        "/api/trust/decide",
        json={"requester_key": key, "action": action, "amount": amount},
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_full_accept_and_refuse_flow_over_http():
    client = boot()
    acme, buyer, vendor, spoofer = (
        KeyPair.generate(),
        KeyPair.generate(),
        KeyPair.generate(),
        KeyPair.generate(),
    )
    register(client, "BuyerBot", buyer, "Acme")
    register(client, "VendorBot", vendor, "Vendor Inc")
    register(client, "SpooferBot", spoofer, "unknown")

    issue(
        client, acme, buyer, "AuthorityGrant",
        {"action": "purchase", "max_amount": 1000},
        {"actions": ["purchase"], "max_amount": 1000},
    )
    for _ in range(2):
        issue(
            client, vendor, buyer, "TaskCompletion",
            {"task": "prior purchase", "outcome": "completed"},
            {"actions": ["purchase"]},
        )

    ok = decide(client, buyer.public_key_b64)
    assert ok["decision"] == "allow"
    assert ok["llm_called"] is False

    refused = decide(client, spoofer.public_key_b64)
    assert refused["decision"] == "refuse"

    from urllib.parse import quote

    profile_resp = client.get(f"/api/trust/profile/{quote(buyer.public_key_b64, safe='')}")
    assert profile_resp.status_code == 200, profile_resp.text
    profile = profile_resp.json()
    assert profile["counts"]["valid_completions"] == 2
    assert "score" not in profile and "reputation_score" not in profile

    receipts = client.get("/api/trust/receipts").json()["receipts"]
    assert len(receipts) == 2
    assert all(r["llm_called"] is False for r in receipts)


def test_server_rejects_forged_credential_submission():
    client = boot()
    acme, buyer, attacker = KeyPair.generate(), KeyPair.generate(), KeyPair.generate()
    register(client, "BuyerBot", buyer, "Acme")
    now = datetime.now(UTC)
    forged = Credential(
        id=str(uuid.uuid4()),
        issuer_key=acme.public_key_b64,  # claims Acme issued it
        subject_key=buyer.public_key_b64,
        type=CredentialType.AUTHORITY_GRANT,
        claim={"action": "purchase", "max_amount": 999999},
        scope={"actions": ["purchase"], "max_amount": 999999},
        issued_at=now,
        expires_at=now + timedelta(days=30),
        revoked_at=None,
        revocation_reason=None,
        signature="",
    )
    # attacker signs with THEIR key, not Acme's
    body = {**forged.signed_payload(), "signature": sign_payload(attacker, forged.signed_payload())}
    r = client.post("/api/trust/credentials", json=body)
    assert r.status_code == 422 or r.status_code == 400  # rejected at boundary


def test_revoke_endpoint_flips_decision():
    client = boot()
    acme, buyer = KeyPair.generate(), KeyPair.generate()
    register(client, "BuyerBot", buyer, "Acme")
    cred = issue(
        client, acme, buyer, "AuthorityGrant",
        {"action": "purchase", "max_amount": 1000},
        {"actions": ["purchase"], "max_amount": 1000},
    )
    before = decide(client, buyer.public_key_b64, amount=500)
    assert before["decision"] in ("allow", "escalate")

    revoke_body = {
        "credential_id": cred["id"],
        "reason": "owner revoked",
        "issuer_key": acme.public_key_b64,
    }
    revoke_body["request_signature"] = sign_payload(acme, revoke_body)
    r = client.post("/api/trust/revoke", json=revoke_body)
    assert r.status_code == 200, r.text

    after = decide(client, buyer.public_key_b64, amount=500)
    assert after["decision"] == "refuse"
    assert "revoked" in after["reasoning"]


def test_revoke_requires_issuer_signature():
    client = boot()
    acme, buyer, attacker = KeyPair.generate(), KeyPair.generate(), KeyPair.generate()
    register(client, "BuyerBot", buyer, "Acme")
    cred = issue(
        client, acme, buyer, "AuthorityGrant",
        {"action": "purchase", "max_amount": 1000},
        {"actions": ["purchase"], "max_amount": 1000},
    )
    revoke_body = {
        "credential_id": cred["id"],
        "reason": "malicious revocation attempt",
        "issuer_key": acme.public_key_b64,
    }
    # attacker tries to revoke Acme's grant, signing with their own key
    revoke_body["request_signature"] = sign_payload(attacker, revoke_body)
    r = client.post("/api/trust/revoke", json=revoke_body)
    assert r.status_code == 403
