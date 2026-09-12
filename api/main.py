"""FastAPI adapter for TrustCore. Thin layer: Pydantic validation at the
boundary, signature-gated mutations, then straight into TrustService.

Key custody: the server NEVER holds private keys. Issuers sign credential
payloads client-side; this adapter verifies signatures only.

Mounts under /api/trust so later challenges get sibling routers
(/api/decisions, /api/memory, ...) on the same app — one deployment.
"""

from datetime import UTC
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

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
from core.decisioncore.application.services import DecisionService, make_authority_probe
from core.decisioncore.domain.policies import register_domain
from core.memorycore.adapters.memory import (
    InMemoryMemoryStore,
    InMemoryTombstoneLog,
)
from core.memorycore.adapters.memory import (
    ManualClock as MemoryClock,
)
from core.memorycore.application.services import MemoryService
from core.simcore.adapters.memory import InMemoryLedgerStore, InMemorySimulationStore
from core.simcore.application.services import SimService
from core.towercore.adapters.memory import InMemoryNotifier, attach_notifier
from core.towercore.application.services import TowerService
from core.towercore.domain.gate import AgentHalted
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

    # C2 DecisionCore shares the same TrustService: authority evidence is the
    # REAL signature/scope verification, and the audit trail is the SAME
    # append-only receipt log. The authority probe forks trust state (C8
    # pattern) so a decision's authority check never pollutes live history.
    def _trust_factory():
        return (
            InMemoryAgentRegistry(),
            InMemoryCredentialStore(),
            InMemoryReceiptLog(),
            SystemClock(),
        )

    decision_svc = DecisionService(
        authority=svc,
        history=svc,
        decisions=InMemoryDecisionStore(),
        audit=svc,
        authority_probe=make_authority_probe(svc, _trust_factory),
    )
    app.state.decision_service = decision_svc

    # C3 AdaptiveCore composes the three modules through their public
    # application surfaces: TrustCore for authority + receipts, DecisionCore
    # for per-step gating, SimCore for budget effects + pre-commit previews.
    # The purchase gate policy lives in DecisionCore; AdaptiveCore calls it
    # by domain name like any other consumer.
    from core.decisioncore.application.purchase_policy import PURCHASE

    register_domain(PURCHASE)
    adaptive_svc = AdaptiveService(
        runs=InMemoryRunStore(),
        plans=InMemoryPlanStore(),
        events=InMemoryEventStream(),
        world=InMemoryWorldStore(),
        revisions=InMemoryRevisionStore(),
        budget=SimBudgetPort(sim_svc),
        authority=TrustAuthorityPort(svc),
        gate=DecisionStepGate(decision_svc),
        preview=SimStepPreview(sim_svc),
        audit=svc,
    )
    app.state.adaptive_service = adaptive_svc

    # C5 TowerCore: the SRE layer over the fleet. Composes the SAME trust,
    # decision, and sim service instances — the agents act on enforced state,
    # and every intervention lands on the tower's append-only event stream.
    tower_svc = TowerService(trust=svc, decision=decision_svc, sim=sim_svc)
    tower_notifier = InMemoryNotifier()
    attach_notifier(tower_svc.stream, tower_notifier)
    app.state.tower_service = tower_svc
    app.state.tower_notifier = tower_notifier

    # C4 MemoryCore: the self-doubting memory layer. Composes the SAME
    # TrustService — revocations are signature-verified and every learn /
    # recall / forget lands in the SAME append-only receipt log. The demo
    # clock is manual: staleness is a deliberate scenario beat, not a race.
    from datetime import datetime

    memory_clock = MemoryClock(datetime.now(UTC))
    memory_svc = MemoryService(
        store=InMemoryMemoryStore(),
        tombstones=InMemoryTombstoneLog(),
        clock=memory_clock,
        trust=svc,
    )
    app.state.memory_service = memory_svc
    app.state.memory_clock = memory_clock
    # per-demo user keypair, created by /api/memory/demo; the private half
    # stays server-side ONLY so the demo can sign the revocation beat — it is
    # never returned by any endpoint
    app.state.memory_demo_keys = {}

    # C6 CompanyCore: the autonomous company. Four roles act on ONE shared
    # event-sourced record; every action is gated by the SAME TrustService and
    # DecisionService instances the other cores use. The ChiefOfStaff is the
    # only LLM-touched role — propose-only, parsed by deterministic domain
    # code, with a scripted fallback so clean clones run offline.
    from core.companycore.adapters.llm import OpenRouterChief
    from core.companycore.adapters.memory import (
        InMemoryEventStore,
        ManualClock as CompanyClock,
        ScriptedLLM,
    )
    from core.companycore.application.services import CompanyService

    company_svc = CompanyService(
        events=InMemoryEventStore(),
        clock=CompanyClock(),
        llm=OpenRouterChief(fallback=ScriptedLLM()),
        trust=svc,
        decision=decision_svc,
        memory=memory_svc,
    )
    app.state.company_service = company_svc

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

    # ------------------------------------------------------------ C2 DecisionCore
    # The decision is computed from signals — no prompt box, no LLM.

    class DecideActionIn(BaseModel):
        domain: str = Field(min_length=1, max_length=50)
        action: str = Field(min_length=1, max_length=100)
        actor_key: str = Field(min_length=1)
        amount: float | None = Field(default=None, ge=0)
        context: dict[str, Any] = Field(default_factory=dict)

    @app.post("/api/decision/demo")
    def decision_demo() -> dict[str, Any]:
        """One-click C2 demo seed: three agents with real signed authority +
        history across the refund/deploy/moderation domains."""
        from core.decisioncore.application.demo import run_decision_demo

        return run_decision_demo(svc)

    @app.get("/api/decision/domains")
    def decision_domains() -> dict[str, Any]:
        return {"domains": decision_svc.list_domains()}

    @app.post("/api/decision/decide")
    def decision_decide(body: DecideActionIn) -> dict[str, Any]:
        try:
            return decision_svc.decide(
                domain=body.domain,
                action=body.action,
                actor_key=body.actor_key,
                amount=body.amount,
                context=body.context,
            )
        except KeyError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/decision/decisions")
    def decision_list(limit: int = 50) -> dict[str, Any]:
        return {"decisions": decision_svc.list(limit=limit)}

    @app.get("/api/decision/{decision_id}")
    def decision_get(decision_id: str) -> dict[str, Any]:
        record = decision_svc.get(decision_id)
        if record is None:
            raise HTTPException(status_code=404, detail="unknown decision")
        return record

    # ------------------------------------------------------------ C3 AdaptiveCore
    # Runs execute one step per advance; world changes arrive as events with
    # real side effects. No prompt box — the loop is deterministic.

    class StartRunIn(BaseModel):
        scenario: str = Field(min_length=1, max_length=50)
        mode: Literal["adaptive", "baseline"]

    class InjectEventIn(BaseModel):
        kind: str = Field(min_length=1, max_length=50)
        payload: dict[str, Any] = Field(default_factory=dict)

    @app.post("/api/adaptive/demo")
    def adaptive_demo() -> dict[str, Any]:
        """One-click C3 demo seed: RestockBot with signed purchase authority."""
        from core.adaptivecore.application.demo import run_adaptive_demo

        result = run_adaptive_demo(svc)
        adaptive_svc.bind_agent(result["agent_key"])
        return result

    @app.get("/api/adaptive/scenarios")
    def adaptive_scenarios() -> dict[str, Any]:
        return {"scenarios": adaptive_svc.list_scenarios()}

    @app.post("/api/adaptive/runs", status_code=201)
    def adaptive_start(body: StartRunIn) -> dict[str, Any]:
        try:
            return adaptive_svc.start_run(scenario=body.scenario, mode=body.mode)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/adaptive/runs/{run_id}/events", status_code=201)
    def adaptive_inject(run_id: str, body: InjectEventIn) -> dict[str, Any]:
        try:
            return adaptive_svc.inject_event(run_id=run_id, kind=body.kind,
                                             payload=body.payload)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/adaptive/runs/{run_id}/advance")
    def adaptive_advance(run_id: str) -> dict[str, Any]:
        try:
            return adaptive_svc.advance(run_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/adaptive/runs/{run_id}/run-to-end")
    def adaptive_run_to_end(run_id: str) -> dict[str, Any]:
        try:
            return adaptive_svc.run_to_end(run_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/adaptive/runs/{run_id}")
    def adaptive_get(run_id: str) -> dict[str, Any]:
        try:
            return adaptive_svc.get_run(run_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/adaptive/runs")
    def adaptive_list(limit: int = 50) -> dict[str, Any]:
        return {"runs": adaptive_svc.list_runs(limit=limit)}

    # ---------------------------------------------------------------- C5 TowerCore
    # The control surface: observe the fleet, approve risky actions, intervene.
    # Telemetry pushes over SSE; interventions are REST (request + receipt).

    class OperatorIn(BaseModel):
        operator: str = Field(default="operator", min_length=1, max_length=100)

    class RogueIn(BaseModel):
        agent_id: str = Field(default="deploybot", min_length=1, max_length=50)

    @app.post("/api/tower/demo")
    def tower_demo() -> dict[str, Any]:
        """One-click C5 seed: enroll the fleet with real signed authority."""
        return tower_svc.seed_demo()

    @app.get("/api/tower/fleet")
    def tower_fleet() -> dict[str, Any]:
        return {"agents": tower_svc.fleet_snapshot()}

    @app.get("/api/tower/stream")
    def tower_stream() -> Any:
        """SSE fan-out from the event stream. One queue per client; the stream
        stays authoritative — a dropped push is recovered by the next poll."""
        import asyncio
        import json

        from fastapi.responses import StreamingResponse

        q = tower_notifier.subscribe()

        async def gen():
            try:
                while True:
                    try:
                        event = await asyncio.to_thread(q.get, True, 15.0)
                        yield f"data: {json.dumps(event)}\n\n"
                    except Exception:
                        yield ": keepalive\n\n"  # comment frame keeps proxies open
            finally:
                tower_notifier.unsubscribe(q)

        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/tower/approvals")
    def tower_approvals() -> dict[str, Any]:
        return {"approvals": [a.as_dict() for a in tower_svc.pending_approvals()]}

    @app.post("/api/tower/approvals/{approval_id}/approve")
    def tower_approve(approval_id: str, body: OperatorIn) -> dict[str, Any]:
        try:
            return tower_svc.approve(approval_id, operator=body.operator)
        except ValueError as exc:
            status = 404 if "unknown" in str(exc) else 409
            raise HTTPException(status_code=status, detail=str(exc)) from exc

    @app.post("/api/tower/approvals/{approval_id}/deny")
    def tower_deny(approval_id: str, body: OperatorIn) -> dict[str, Any]:
        try:
            return tower_svc.deny(approval_id, operator=body.operator)
        except ValueError as exc:
            status = 404 if "unknown" in str(exc) else 409
            raise HTTPException(status_code=status, detail=str(exc)) from exc

    def _intervene(agent_id: str, body: OperatorIn, verb: str) -> dict[str, Any]:
        try:
            if verb == "pause":
                return tower_svc.pause(agent_id, operator=body.operator)
            if verb == "resume":
                return tower_svc.resume(agent_id, operator=body.operator)
            return tower_svc.kill(agent_id, operator=body.operator)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/tower/agents/{agent_id}/pause")
    def tower_pause(agent_id: str, body: OperatorIn) -> dict[str, Any]:
        return _intervene(agent_id, body, "pause")

    @app.post("/api/tower/agents/{agent_id}/resume")
    def tower_resume(agent_id: str, body: OperatorIn) -> dict[str, Any]:
        return _intervene(agent_id, body, "resume")

    @app.post("/api/tower/agents/{agent_id}/kill")
    def tower_kill(agent_id: str, body: OperatorIn) -> dict[str, Any]:
        return _intervene(agent_id, body, "kill")

    @app.post("/api/tower/agents/{agent_id}/advance")
    def tower_advance(agent_id: str) -> dict[str, Any]:
        try:
            return tower_svc.advance(agent_id)
        except AgentHalted as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            status = 404 if "unknown" in str(exc) else 409
            raise HTTPException(status_code=status, detail=str(exc)) from exc

    @app.get("/api/tower/agents/{agent_id}/replay")
    def tower_replay(agent_id: str, n: int = 20) -> dict[str, Any]:
        return {"agent_id": agent_id, "trace": tower_svc.replay(agent_id, n)}

    @app.post("/api/tower/scenario/rogue")
    def tower_rogue(body: RogueIn) -> dict[str, Any]:
        try:
            return tower_svc.inject_rogue(body.agent_id)
        except ValueError as exc:
            status = 404 if "unknown" in str(exc) else 409
            raise HTTPException(status_code=status, detail=str(exc)) from exc

    @app.get("/api/tower/audit")
    def tower_audit() -> dict[str, Any]:
        """Exportable audit log (bonus: compliance). Canonical events, append
        order — the full forensic trail from enrollment to containment."""
        return {"events": tower_svc.export_audit()}

    # ---------------------------------------------------------------- C4 MemoryCore
    # The memory that knows it might be wrong: tagged writes, reliance-receipt
    # recalls, explicit + receipted forgetting. Revocation is signature-gated
    # (fail-closed); the demo signs beats with its server-held demo key.

    class LearnIn(BaseModel):
        slot: str = Field(min_length=1, max_length=100)
        value: str = Field(min_length=1, max_length=500)
        source: str = Field(min_length=1, max_length=100)
        kind: Literal["user_stated", "observed", "inferred", "imported"]
        extraction_confidence: float = Field(gt=0, le=1)
        user_id: str = Field(min_length=1, max_length=100)
        agent_id: str = Field(default="maya", min_length=1, max_length=100)
        task_id: str | None = Field(default=None, max_length=100)
        ttl_days: int | None = Field(default=None, gt=0)

    class RecallIn(BaseModel):
        query: str = Field(min_length=1, max_length=500)
        user_id: str = Field(min_length=1, max_length=100)
        agent_id: str = Field(default="maya", min_length=1, max_length=100)
        task_id: str | None = Field(default=None, max_length=100)

    class ForgetIn(BaseModel):
        fact_id: str = Field(min_length=1)
        user_key: str = Field(min_length=1)
        signature: str = Field(min_length=1)
        reason: str = Field(default="user revoked", min_length=1, max_length=500)

    @app.post("/api/memory/demo")
    def memory_demo() -> dict[str, Any]:
        """One-click C4 seed: Maya learns three differently-tagged facts."""
        from core.memorycore.application.demo import seed_demo
        from core.trustcore.domain.crypto import KeyPair

        user_key = KeyPair.generate()
        app.state.memory_demo_keys["demo-user"] = user_key
        return seed_demo(memory_svc, user_key=user_key)

    @app.post("/api/memory/demo/unsure")
    def memory_demo_unsure() -> dict[str, Any]:
        """Beat 2: trip-planning recall — the 'I might be wrong' moment."""
        from core.memorycore.application.demo import beat_unsure

        return beat_unsure(memory_svc)

    @app.post("/api/memory/demo/correct")
    def memory_demo_correct() -> dict[str, Any]:
        """Beat 3: user correction supersedes the weak inference."""
        from core.memorycore.application.demo import beat_correct

        return beat_correct(memory_svc)

    @app.post("/api/memory/demo/age")
    def memory_demo_age() -> dict[str, Any]:
        """Beat 4: time passes; the imported fact goes stale and is swept."""
        from core.memorycore.application.demo import beat_age

        return beat_age(memory_svc, memory_clock)

    @app.post("/api/memory/demo/revoke")
    def memory_demo_revoke() -> dict[str, Any]:
        """Beat 5: the user SIGNS 'forget my location' — real revocation."""
        from core.memorycore.application.demo import beat_revoke

        user_key = app.state.memory_demo_keys.get("demo-user")
        if user_key is None:
            raise HTTPException(status_code=409, detail="run /api/memory/demo first")
        try:
            return beat_revoke(memory_svc, user_key=user_key)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/memory/learn", status_code=201)
    def memory_learn(body: LearnIn) -> dict[str, Any]:
        try:
            return memory_svc.learn(
                slot=body.slot,
                value=body.value,
                source=body.source,
                kind=body.kind,
                extraction_confidence=body.extraction_confidence,
                user_id=body.user_id,
                agent_id=body.agent_id,
                task_id=body.task_id,
                ttl_days=body.ttl_days,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/memory/recall")
    def memory_recall(body: RecallIn) -> dict[str, Any]:
        return memory_svc.recall(
            query=body.query,
            user_id=body.user_id,
            agent_id=body.agent_id,
            task_id=body.task_id,
        )

    @app.post("/api/memory/forget")
    def memory_forget(body: ForgetIn) -> dict[str, Any]:
        try:
            return memory_svc.forget(
                fact_id=body.fact_id,
                user_key=body.user_key,
                signature=body.signature,
                reason=body.reason,
            )
        except ValueError as exc:
            status = 403 if "signature" in str(exc) else 404
            raise HTTPException(status_code=status, detail=str(exc)) from exc

    @app.post("/api/memory/sweep")
    def memory_sweep() -> dict[str, Any]:
        return memory_svc.sweep()

    @app.get("/api/memory/inspect")
    def memory_inspect(user_id: str, agent_id: str = "maya") -> dict[str, Any]:
        return memory_svc.inspect(user_id=user_id, agent_id=agent_id)

    @app.get("/api/memory/events")
    def memory_events(limit: int = 100) -> dict[str, Any]:
        return memory_svc.list_events(limit=limit)

    # ------------------------------------------------------------- C6 CompanyCore
    # The run-the-week loop. Roles propose on one shared record; cores enforce;
    # the human inbox catches what shouldn't auto-execute.

    class CompanyDemoIn(BaseModel):
        scenario: Literal["normal", "cash_crunch"] = "normal"

    class ResolveIn(BaseModel):
        resolution: str = Field(min_length=1, max_length=500)

    @app.post("/api/company/demo")
    def company_demo(body: CompanyDemoIn) -> dict[str, Any]:
        """One-click C6 seed: Northwind Components, four roles, opening books."""
        return company_svc.seed_demo(body.scenario)

    @app.post("/api/company/advance")
    def company_advance() -> dict[str, Any]:
        try:
            return company_svc.advance_day()
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/company/state")
    def company_state() -> dict[str, Any]:
        return company_svc.state()

    @app.get("/api/company/kpis")
    def company_kpis() -> dict[str, Any]:
        return company_svc.kpis()

    @app.get("/api/company/inbox")
    def company_inbox() -> dict[str, Any]:
        return {"inbox": company_svc.inbox()}

    @app.post("/api/company/inbox/{escalation_id}/resolve")
    def company_resolve(escalation_id: str, body: ResolveIn) -> dict[str, Any]:
        try:
            return company_svc.resolve_inbox(escalation_id, body.resolution)
        except ValueError as exc:
            status = 404 if "unknown" in str(exc) else 409
            raise HTTPException(status_code=status, detail=str(exc)) from exc

    @app.get("/api/company/replay")
    def company_replay(day: int = 0) -> dict[str, Any]:
        return company_svc.replay(day)

    @app.get("/api/company/events")
    def company_events() -> dict[str, Any]:
        return {"events": company_svc.events()}

    @app.post("/api/company/scenario/cash-crunch")
    def company_cash_crunch() -> dict[str, Any]:
        return company_svc.run_cash_crunch()

    @app.post("/api/company/scenario/rogue-sales")
    def company_rogue_sales() -> dict[str, Any]:
        return company_svc.inject_rogue_sales()

    return app
