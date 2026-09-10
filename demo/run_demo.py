"""Runs the 90-second demo against a live TrustCore server (default localhost).

Spins up three agent "processes" (async tasks with independent keypairs and
HTTP clients — each is a separate actor, not one agent pretending) and walks
the demo beats from demo/script.md, printing receipts as they land.

Usage:
    .venv/Scripts/python.exe -m uvicorn api.main:create_app --factory &
    .venv/Scripts/python.exe demo/run_demo.py [--base http://localhost:8000]
"""

import argparse
import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import httpx

from core.trustcore.domain.credentials import Credential, CredentialType
from core.trustcore.domain.crypto import KeyPair, sign_payload


def signed_credential_body(issuer: KeyPair, subject: KeyPair, ctype, claim, scope) -> dict:
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
    return {**cred.signed_payload(), "signature": sign_payload(issuer, cred.signed_payload())}


async def main(base: str) -> None:
    acme, buyer, vendor, spoofer = (
        KeyPair.generate(), KeyPair.generate(), KeyPair.generate(), KeyPair.generate(),
    )

    async with httpx.AsyncClient(base_url=base, timeout=30) as client:
        print("\n[0:00] Registering agents: BuyerBot (Acme), VendorBot, SpooferBot")
        for name, kp, owner in [
            ("BuyerBot", buyer, "Acme"),
            ("VendorBot", vendor, "Vendor Inc"),
            ("SpooferBot", spoofer, "unknown"),
        ]:
            await client.post(
                "/api/trust/agents",
                json={"name": name, "public_key": kp.public_key_b64, "owner": owner},
            )

        print("[0:10] Acme delegates purchase authority (<= $1000) to BuyerBot")
        await client.post("/api/trust/credentials", json=signed_credential_body(
            acme, buyer, "AuthorityGrant",
            {"action": "purchase", "max_amount": 1000},
            {"actions": ["purchase"], "max_amount": 1000},
        ))
        print("[0:15] Two prior vendors vouch: TaskCompletion credentials for BuyerBot")
        for _ in range(2):
            await client.post("/api/trust/credentials", json=signed_credential_body(
                vendor, buyer, "TaskCompletion",
                {"task": "prior purchase", "outcome": "completed"},
                {"actions": ["purchase"]},
            ))

        print("\n[0:25] BEAT 1 — BuyerBot requests purchase 100 units @ $8 ($800)...")
        r = (await client.post("/api/trust/decide", json={
            "requester_key": buyer.public_key_b64, "action": "purchase", "amount": 800,
            "description": "100 units @ $8",
        })).json()
        print(f"       DECISION: {r['decision'].upper()} — {r['reasoning']}  [llm_called={r['llm_called']}]")

        print("\n[0:40] BEAT 2 — Task completes; VendorBot issues TaskCompletion credential")
        await client.post("/api/trust/credentials", json=signed_credential_body(
            vendor, buyer, "TaskCompletion",
            {"task": "purchase 100 units", "outcome": "completed"},
            {"actions": ["purchase"]},
        ))
        profile = (await client.get(
            "/api/trust/profile", params={"subject_key": buyer.public_key_b64}
        )).json()
        print(f"       BuyerBot valid completions: {profile['counts']['valid_completions']}")

        print("\n[0:50] BEAT 3 — SpooferBot FORGES an Acme authority grant (own key)...")
        forged = signed_credential_body(
            spoofer, spoofer, "AuthorityGrant",
            {"action": "purchase", "max_amount": 999999},
            {"actions": ["purchase"], "max_amount": 999999},
        )
        forged["issuer_key"] = acme.public_key_b64  # claims Acme issued it
        resp = await client.post("/api/trust/credentials", json=forged)
        print(f"       Forge submission -> HTTP {resp.status_code} ({resp.json().get('detail', '')})")

        print("\n[0:55] BEAT 4 — SpooferBot tries the purchase anyway...")
        r = (await client.post("/api/trust/decide", json={
            "requester_key": spoofer.public_key_b64, "action": "purchase", "amount": 800,
        })).json()
        print(f"       DECISION: {r['decision'].upper()} — {r['reasoning']}")

        print("\n[1:05] BEAT 5 — Spoofer earns a REAL $50 grant, tries $800 (scope escape)...")
        await client.post("/api/trust/credentials", json=signed_credential_body(
            acme, spoofer, "AuthorityGrant",
            {"action": "purchase", "max_amount": 50},
            {"actions": ["purchase"], "max_amount": 50},
        ))
        r = (await client.post("/api/trust/decide", json={
            "requester_key": spoofer.public_key_b64, "action": "purchase", "amount": 800,
        })).json()
        print(f"       DECISION: {r['decision'].upper()} — {r['reasoning']}")

        print("\n[1:15] BEAT 6 — Acme REVOKES BuyerBot's authority; BuyerBot retries...")
        creds = (await client.get(
            "/api/trust/profile", params={"subject_key": buyer.public_key_b64}
        )).json()["credentials"]
        target = [c for c in creds if c["type"] == "AuthorityGrant"][0]
        authority_id = target["id"]
        # issuer re-signs the revoked credential so it stays verifiable
        now = datetime.now(UTC)
        revoked_payload = {
            "id": target["id"],
            "issuer_key": target["issuer_key"],
            "subject_key": buyer.public_key_b64,
            "type": target["type"],
            "claim": target["claim"],
            "scope": target["scope"],
            "issued_at": target["issued_at"],
            "expires_at": target["expires_at"],
            "revoked_at": now.isoformat(),
            "revocation_reason": "Acme revoked — demo",
        }
        revoke_body = {
            "credential_id": authority_id,
            "reason": "Acme revoked — demo",
            "issuer_key": acme.public_key_b64,
            "revoked_at": now.isoformat(),
            "resigned_credential_signature": sign_payload(acme, revoked_payload),
        }
        revoke_body["request_signature"] = sign_payload(
            acme, {k: v for k, v in revoke_body.items() if k != "request_signature"}
        )
        await client.post("/api/trust/revoke", json=revoke_body)
        r = (await client.post("/api/trust/decide", json={
            "requester_key": buyer.public_key_b64, "action": "purchase", "amount": 800,
        })).json()
        print(f"       DECISION: {r['decision'].upper()} — {r['reasoning']}")

        print("\n[1:25] RECEIPT LOG (append-only, machine-readable):")
        receipts = (await client.get("/api/trust/receipts")).json()["receipts"]
        for rec in receipts:
            print(f"       {rec['ts'][:19]}  {rec['decision']:8s}  {rec['action']:10s}  "
                  f"llm={rec['llm_called']}  {rec['reasoning'][:60]}")
        print("\nDone. Every decision above was enforced by crypto + policy only.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://localhost:8000")
    args = parser.parse_args()
    asyncio.run(main(args.base))
