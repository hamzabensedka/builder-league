"""FastAPI adapter for TrustCore. Thin layer: Pydantic validation at the
boundary, signature-gated mutations, then straight into TrustService.

Key custody: the server NEVER holds private keys. Issuers sign credential
payloads client-side; this adapter verifies signatures only.

Mounts under /api/trust so later challenges get sibling routers
(/api/decisions, /api/memory, ...) on the same app — one deployment.
"""

from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from core.trustcore.adapters.memory import (
    InMemoryAgentRegistry,
    InMemoryCredentialStore,
    InMemoryReceiptLog,
    SystemClock,
)
from core.trustcore.application.services import TrustService
from core.trustcore.domain.credentials import Credential, CredentialType
from core.trustcore.domain.crypto import verify_payload

# ---------------------------------------------------------------- schemas


class RegisterAgentIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    public_key: str
    owner: str = Field(min_length=1, max_length=100)


class IssueCredentialIn(BaseModel):
    """A fully-formed, issuer-signed credential. The server verifies and stores it."""

    id: str
    issuer_key: str
    subject_key: str
    type: Literal["TaskCompletion", "AuthorityGrant", "CapabilityAttestation", "Vouch"]
    claim: dict[str, Any]
    scope: dict[str, Any]
    issued_at: str
    expires_at: str
    signature: str


class RevokeIn(BaseModel):
    credential_id: str
    reason: str = Field(min_length=1, max_length=500)
    issuer_key: str
    revoked_at: str  # ISO timestamp the issuer commits to (part of re-signed payload)
    request_signature: str
    # Issuer's signature over the revoked credential payload (optional but
    # keeps the revoked credential independently verifiable — clean receipts).
    resigned_credential_signature: str | None = None


class DecideIn(BaseModel):
    requester_key: str
    action: str = Field(min_length=1, max_length=100)
    amount: float | None = Field(default=None, ge=0)
    description: str = Field(default="", max_length=1000)


# ---------------------------------------------------------------- helpers


def _require_request_signature(issuer_key: str, body: dict[str, Any], signature: str) -> None:
    """Mutating endpoints are credential-gated: the caller must sign the
    request body (canonical JSON of all fields except request_signature).
    None-valued optionals are dropped so clients signing without them verify."""
    payload = {
        k: v for k, v in body.items() if k != "request_signature" and v is not None
    }
    if not verify_payload(issuer_key, payload, signature):
        raise HTTPException(status_code=403, detail="invalid request signature")




# ---------------------------------------------------------------- app


def create_app(service: TrustService | None = None) -> FastAPI:
    svc = service or TrustService(
        registry=InMemoryAgentRegistry(),
        credentials=InMemoryCredentialStore(),
        receipts=InMemoryReceiptLog(),
        clock=SystemClock(),
    )

    app = FastAPI(title="Builder League — TrustCore", version="0.1.0")
    app.state.service = svc

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/trust/agents", status_code=201)
    def register_agent(body: RegisterAgentIn) -> dict[str, str]:
        agent_id = svc.register_agent(
            name=body.name, public_key=body.public_key, owner=body.owner
        )
        return {"agent_id": agent_id}

    @app.get("/api/trust/agents")
    def list_agents() -> dict[str, Any]:
        return {"agents": svc.list_agents()}

    @app.post("/api/trust/credentials", status_code=201)
    def issue_credential(body: IssueCredentialIn) -> dict[str, Any]:
        from datetime import datetime

        cred = Credential(
            id=body.id,
            issuer_key=body.issuer_key,
            subject_key=body.subject_key,
            type=CredentialType(body.type),
            claim=body.claim,
            scope=body.scope,
            issued_at=datetime.fromisoformat(body.issued_at),
            expires_at=datetime.fromisoformat(body.expires_at),
            revoked_at=None,
            revocation_reason=None,
            signature=body.signature,
        )
        try:
            stored = svc.register_signed_credential(cred)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"id": stored.id, "type": str(stored.type), "issuer_key": stored.issuer_key}

    @app.post("/api/trust/revoke")
    def revoke_credential(body: RevokeIn) -> dict[str, str]:
        _require_request_signature(body.issuer_key, body.model_dump(), body.request_signature)
        cred = svc.get_credential(body.credential_id)
        if cred is None:
            raise HTTPException(status_code=404, detail="unknown credential")
        if cred.issuer_key != body.issuer_key:
            raise HTTPException(status_code=403, detail="only the issuer may revoke")
        if body.resigned_credential_signature:
            from dataclasses import replace
            from datetime import datetime

            revoked = replace(
                cred,
                revoked_at=datetime.fromisoformat(body.revoked_at),
                revocation_reason=body.reason,
                signature=body.resigned_credential_signature,
            )
            if not verify_payload(
                body.issuer_key, revoked.signed_payload(), body.resigned_credential_signature
            ):
                raise HTTPException(status_code=400, detail="resigned credential signature invalid")
            svc.revoke_credential(
                credential_id=body.credential_id, reason=body.reason, resigned=revoked
            )
        else:
            svc.revoke_credential(credential_id=body.credential_id, reason=body.reason)
        return {"status": "revoked", "credential_id": body.credential_id}

    @app.post("/api/trust/decide")
    def decide(body: DecideIn) -> dict[str, Any]:
        receipt = svc.decide(
            requester_key=body.requester_key,
            action=body.action,
            amount=body.amount,
            description=body.description,
        )
        return {
            "id": receipt.id,
            "decision": str(receipt.decision),
            "reasoning": receipt.reasoning,
            "signals": receipt.signals,
            "llm_called": receipt.llm_called,
        }

    @app.get("/api/trust/profile")
    def profile(subject_key: str) -> dict[str, Any]:
        # query param: base64 keys contain '/' and '+', unsafe in path segments
        return svc.trust_profile(subject_key=subject_key)

    @app.get("/api/trust/receipts")
    def receipts(limit: int = 50) -> dict[str, Any]:
        return {
            "receipts": [
                {
                    "id": r.id,
                    "ts": r.ts.isoformat(),
                    "agent_id": r.agent_id,
                    "action": r.action,
                    "decision": str(r.decision),
                    "reasoning": r.reasoning,
                    "signals": r.signals,
                    "llm_called": r.llm_called,
                }
                for r in svc.list_receipts(limit=limit)
            ]
        }

    return app
