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

from core.simcore.adapters.memory import InMemoryLedgerStore, InMemorySimulationStore
from core.simcore.application.services import SimService
from core.trustcore.adapters.memory import (
    InMemoryAgentRegistry,
    InMemoryCredentialStore,
    InMemoryReceiptLog,
    SystemClock,
)
from core.trustcore.application.services import TrustService
from core.trustcore.domain.credentials import Credential, CredentialType
from core.trustcore.domain.crypto import verify_payload

SIM_LIMIT = 1000.0

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
    # C8 SimCore shares the same TrustService instance: simulation forks and
    # execution both act on the REAL trust state, never a mock.
    sim_svc = SimService(
        trust=svc,
        ledger_store=InMemoryLedgerStore(),
        simulations=InMemorySimulationStore(),
        limit=SIM_LIMIT,
    )
    app.state.sim_service = sim_svc

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    # Serve the built inspector UI at / when available; fall back to the static
    # landing page for API-only deploys.
    from pathlib import Path

    from fastapi.responses import FileResponse, HTMLResponse
    from fastapi.staticfiles import StaticFiles

    ui_dist = Path(__file__).resolve().parent.parent / "ui" / "dist"
    if (ui_dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=ui_dist / "assets"), name="assets")

    @app.get("/", include_in_schema=False)
    def root() -> Any:
        index = ui_dist / "index.html"
        if index.is_file():
            return FileResponse(index)
        landing = Path(__file__).with_name("landing.html")
        return HTMLResponse(landing.read_text(encoding="utf-8"))

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

    @app.post("/api/trust/demo")
    def run_demo() -> dict[str, Any]:
        """One-click demo for visitors with no codebase access: runs the full
        six-beat scenario server-side and narrates it for the UI."""
        from core.trustcore.application.demo import run_demo_scenario

        return run_demo_scenario(svc)

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

    # ---------------------------------------------------------------- C8 SimCore
    # The approval payload IS the computed before/after diff — no confirm dialog.

    class SimulateIn(BaseModel):
        requester_key: str
        amount: float = Field(gt=0)
        description: str = Field(default="", max_length=1000)

    class HoldIn(BaseModel):
        agent_key: str = Field(min_length=1)
        amount: float = Field(gt=0)

    @app.post("/api/sim/demo")
    def sim_demo() -> dict[str, Any]:
        """One-click C8 demo seed: funded buyer with signed authority + history."""
        from core.simcore.application.demo import run_sim_demo

        return run_sim_demo(sim_svc)

    @app.post("/api/sim/simulate", status_code=201)
    def sim_simulate(body: SimulateIn) -> dict[str, Any]:
        return sim_svc.simulate(
            requester_key=body.requester_key,
            amount=body.amount,
            description=body.description,
        )

    @app.get("/api/sim/simulations")
    def sim_list(limit: int = 50) -> dict[str, Any]:
        return {"simulations": sim_svc.list(limit=limit)}

    @app.get("/api/sim/{sim_id}")
    def sim_get(sim_id: str) -> dict[str, Any]:
        record = sim_svc.get(sim_id)
        if record is None:
            raise HTTPException(status_code=404, detail="unknown simulation")
        return record

    @app.post("/api/sim/{sim_id}/execute")
    def sim_execute(sim_id: str) -> dict[str, Any]:
        try:
            return sim_svc.execute(sim_id)
        except ValueError as exc:
            status = 404 if "unknown" in str(exc) else 409
            raise HTTPException(status_code=status, detail=str(exc)) from exc

    @app.post("/api/sim/{sim_id}/reject")
    def sim_reject(sim_id: str) -> dict[str, Any]:
        try:
            return sim_svc.reject(sim_id)
        except ValueError as exc:
            status = 404 if "unknown" in str(exc) else 409
            raise HTTPException(status_code=status, detail=str(exc)) from exc

    @app.post("/api/sim/{sim_id}/rollback")
    def sim_rollback(sim_id: str) -> dict[str, Any]:
        try:
            return sim_svc.rollback(sim_id)
        except ValueError as exc:
            status = 404 if "unknown" in str(exc) else 409
            raise HTTPException(status_code=status, detail=str(exc)) from exc

    @app.post("/api/sim/hold", status_code=201)
    def sim_hold(body: HoldIn) -> dict[str, Any]:
        """A real concurrent hold by a separate actor — the failure-test lever."""
        return sim_svc.place_hold(
            agent_key=body.agent_key, amount=body.amount, reference="ui-hold"
        )

    @app.get("/api/sim/ledger/state")
    def sim_ledger() -> dict[str, Any]:
        ledger = sim_svc._ledger_store.get()  # demo read surface
        return {
            "entries": [e.as_dict() for e in ledger.entries],
            "spent_total": ledger.spent_total(),
            "active_holds": ledger.active_holds_total(),
            "projected_balance": ledger.projected_balance(),
            "limit": SIM_LIMIT,
        }

    return app
