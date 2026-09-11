"""The fleet: three scripted agents doing real work through real cores.

Each agent is a step-at-a-time loop (one step per advance, like C3) so human
interventions land BETWEEN steps — pause/kill mid-flight is the whole point.
Every step checks the InterventionGate first (enforced, not advisory), calls
the REAL TrustCore/DecisionCore/SimCore surfaces, and appends typed events to
the shared stream. Nothing here is mocked: a denied deploy is a real TrustCore
refusal over real signed credentials.

- RestockBot (procurement): monitor stock -> size order -> purchase via
  TrustCore authority + SimCore simulate-before-write.
- RefundBot (finance): pop refund ticket -> DecisionCore decide; clean ones
  execute, risky ones (ASK/ESCALATE) park in the approval queue.
- DeployBot (releases): pick release -> verify change ticket -> deploy via
  DecisionCore + TrustCore. The rogue-scenario agent.
"""

from dataclasses import dataclass, field
from typing import Any

from core.towercore.domain.gate import InterventionGate


@dataclass
class AgentContext:
    """What one agent needs to take a step. Injected by TowerService so this
    module never imports adapters or the api layer."""

    agent_id: str
    agent_key: str  # TrustCore public key
    gate: InterventionGate
    emit: Any  # (kind, payload) -> dict  (service appends + costs + anomaly-checks)
    trust: Any  # AuthorityGate
    decision: Any  # DecisionEngine
    sim: Any  # SimulationGate
    world: dict[str, Any]  # mutable scenario state (stock, tickets, releases)
    rogue: bool = False  # corrupted objective (scenario injection)


@dataclass
class FleetAgent:
    agent_id: str
    name: str
    job: str  # procurement | finance | releases
    budget_usd: float
    steps: list[str] = field(default_factory=list)

    def cursor(self, world: dict[str, Any]) -> int:
        return world.setdefault("cursors", {}).setdefault(self.agent_id, 0)

    def advance_cursor(self, world: dict[str, Any]) -> None:
        world["cursors"][self.agent_id] = self.cursor(world) + 1


# ---------------------------------------------------------------- RestockBot

RESTOCK_STEPS = ["check_stock", "size_order", "purchase", "verify_delivery"]


def restock_step(ctx: AgentContext, world: dict[str, Any]) -> dict[str, Any]:
    agent = next(a for a in FLEET if a.agent_id == "restockbot")
    step = RESTOCK_STEPS[agent.cursor(world) % len(RESTOCK_STEPS)]
    ctx.gate.check(ctx.agent_id)
    ctx.emit("step_started", {"step": step, "job": "procurement"})

    if step == "check_stock":
        stock = world.setdefault("stock", {"widgets": 4, "gadgets": 9})
        low = [k for k, v in stock.items() if v < 5]
        ctx.emit("action_executed", {"action": "check_stock", "stock": dict(stock),
                                     "low": low})
        agent.advance_cursor(world)
        return {"kind": "action_executed", "payload": {"action": "check_stock"}}

    if step == "size_order":
        amount = 320.0  # fits the $500 purchase authority
        world["pending_order"] = {"item": "widgets", "qty": 20, "amount": amount}
        ctx.emit("action_executed", {"action": "size_order", "amount": amount})
        agent.advance_cursor(world)
        return {"kind": "action_executed", "payload": {"action": "size_order"}}

    if step == "purchase":
        order = world.get("pending_order") or {"item": "widgets", "qty": 20, "amount": 320.0}
        ctx.emit("decision_requested", {"domain": "purchase", "action": "purchase",
                                        "amount": order["amount"]})
        # simulate-before-write on the REAL ledger, then execute (C8 pipeline)
        sim_rec = ctx.sim.simulate(
            requester_key=ctx.agent_key, amount=order["amount"],
            description=f"restock {order['qty']} {order['item']}",
        )
        if sim_rec["predicted_effects"]["decision"] != "allow":
            ctx.emit("action_denied", {"action": "purchase",
                                       "reason": sim_rec["predicted_effects"]["reasoning"]})
            agent.advance_cursor(world)
            return {"kind": "action_denied", "payload": {"action": "purchase"}}
        ctx.sim.execute(sim_rec["id"])
        world["stock"]["widgets"] = world["stock"].get("widgets", 0) + order["qty"]
        world.pop("pending_order", None)
        payload = {"action": "purchase", "amount": order["amount"], "sim_id": sim_rec["id"]}
        ctx.emit("action_executed", payload)
        agent.advance_cursor(world)
        return {"kind": "action_executed", "payload": payload}

    # verify_delivery
    ctx.emit("action_executed", {"action": "verify_delivery",
                                 "stock": dict(world.get("stock", {}))})
    agent.advance_cursor(world)
    return {"kind": "action_executed", "payload": {"action": "verify_delivery"}}


# ----------------------------------------------------------------- RefundBot

REFUND_STEPS = ["pop_ticket", "decide_refund"]


def refund_step(ctx: AgentContext, world: dict[str, Any]) -> dict[str, Any]:
    agent = next(a for a in FLEET if a.agent_id == "refundbot")
    step = REFUND_STEPS[agent.cursor(world) % len(REFUND_STEPS)]
    ctx.gate.check(ctx.agent_id)
    ctx.emit("step_started", {"step": step, "job": "finance"})

    if step == "pop_ticket":
        queue = world.setdefault("refund_queue", [
            {"ticket": "T-101", "amount": 120.0, "invoice_id": "INV-101", "reason": "defective"},
            {"ticket": "T-102", "amount": 2400.0, "invoice_id": None, "reason": "charged twice"},
            {"ticket": "T-103", "amount": 85.0, "invoice_id": "INV-103", "reason": "returned"},
        ])
        if not queue:
            ctx.emit("blocker_raised", {"blocker": "refund queue empty"})
            return {"kind": "blocker_raised", "payload": {"blocker": "refund queue empty"}}
        ticket = queue.pop(0)
        world["current_ticket"] = ticket
        ctx.emit("action_executed", {"action": "pop_ticket", "ticket": ticket["ticket"],
                                     "amount": ticket["amount"]})
        agent.advance_cursor(world)
        return {"kind": "action_executed", "payload": {"action": "pop_ticket"}}

    # decide_refund — REAL DecisionCore call
    ticket = world.get("current_ticket")
    if ticket is None:
        agent.advance_cursor(world)
        return refund_step(ctx, world)  # no ticket staged: pop one instead
    ctx.emit("decision_requested", {"domain": "refund", "action": "issue_refund",
                                    "amount": ticket["amount"]})
    record = ctx.decision.decide(
        domain="refund", action="issue_refund", actor_key=ctx.agent_key,
        amount=ticket["amount"],
        context={"invoice_id": ticket.get("invoice_id"), "reason": ticket.get("reason")},
    )
    outcome = record["outcome"]
    if outcome == "execute":
        payload = {"action": "issue_refund", "ticket": ticket["ticket"],
                   "amount": ticket["amount"], "outcome": outcome,
                   "confidence": record["confidence"], "risk": record["risk"]}
        ctx.emit("action_executed", payload)
        world.pop("current_ticket", None)
        agent.advance_cursor(world)
        return {"kind": "action_executed", "payload": payload}
    if outcome in ("ask", "escalate"):
        # park in the approval queue — a human decides
        reason = f"{outcome}: {record['reasoning']}"
        ctx.emit("approval_requested", {"action": "issue_refund", "amount": ticket["amount"],
                                        "reason": reason, "ticket": ticket["ticket"]})
        ap = ctx.gate.request_approval(
            agent_id=ctx.agent_id, action="issue_refund", amount=ticket["amount"],
            reason=reason, payload={"ticket": ticket},
        )
        world["parked_ticket"] = ticket
        world.pop("current_ticket", None)
        agent.advance_cursor(world)
        return {"kind": "approval_requested", "payload": ap.as_dict()}
    # refuse/defer — denied by the engine
    ctx.emit("action_denied", {"action": "issue_refund", "ticket": ticket["ticket"],
                               "reason": record["reasoning"]})
    world.pop("current_ticket", None)
    agent.advance_cursor(world)
    return {"kind": "action_denied", "payload": {"action": "issue_refund",
                                                 "outcome": outcome}}


# ----------------------------------------------------------------- DeployBot

DEPLOY_STEPS = ["pick_release", "verify_ticket", "deploy"]


def deploy_step(ctx: AgentContext, world: dict[str, Any]) -> dict[str, Any]:
    agent = next(a for a in FLEET if a.agent_id == "deploybot")
    step = DEPLOY_STEPS[agent.cursor(world) % len(DEPLOY_STEPS)]
    ctx.gate.check(ctx.agent_id)
    ctx.emit("step_started", {"step": step, "job": "releases", "rogue": ctx.rogue})

    if step == "pick_release":
        releases = world.setdefault("releases", [
            {"version": "v12", "blast_radius": 1200.0, "tests_passing": True,
             "approvals": 2, "change_ticket": None},  # missing ticket → escalate
            {"version": "v13", "blast_radius": 400.0, "tests_passing": True,
             "approvals": 2, "change_ticket": "CHG-77"},
        ])
        if not releases:
            ctx.emit("blocker_raised", {"blocker": "no releases pending"})
            return {"kind": "blocker_raised", "payload": {"blocker": "no releases pending"}}
        world["current_release"] = releases.pop(0)
        rel = world["current_release"]
        ctx.emit("action_executed", {"action": "pick_release", "version": rel["version"]})
        agent.advance_cursor(world)
        return {"kind": "action_executed", "payload": {"action": "pick_release"}}

    if step == "verify_ticket":
        rel = world.get("current_release")
        if rel is None:
            agent.advance_cursor(world)
            return deploy_step(ctx, world)
        # Rogue objective: corrupted agent now deploys WITHOUT the change ticket
        # and claims absurd blast radius — enforcement (DecisionCore/TrustCore)
        # is what stops it, not the agent's own judgement.
        if ctx.rogue:
            rel = dict(rel, change_ticket=None, blast_radius=99999.0)
            world["current_release"] = rel
        ctx.emit("action_executed", {"action": "verify_ticket",
                                     "version": rel["version"],
                                     "change_ticket": rel.get("change_ticket")})
        agent.advance_cursor(world)
        return {"kind": "action_executed", "payload": {"action": "verify_ticket"}}

    # deploy — REAL DecisionCore call; over-authority in rogue mode also hits
    # TrustCore scope limits (amount far beyond any grant)
    rel = world.get("current_release")
    if rel is None:
        agent.advance_cursor(world)
        return deploy_step(ctx, world)
    ctx.emit("decision_requested", {"domain": "deploy", "action": "deploy_production",
                                    "amount": rel["blast_radius"]})
    record = ctx.decision.decide(
        domain="deploy", action="deploy_production", actor_key=ctx.agent_key,
        amount=rel["blast_radius"],
        context={"tests_passing": rel["tests_passing"], "approvals": rel["approvals"],
                 "change_ticket": rel.get("change_ticket")},
    )
    outcome = record["outcome"]
    world.pop("current_release", None)
    agent.advance_cursor(world)
    if outcome == "execute":
        payload = {"action": "deploy_production", "version": rel["version"],
                   "outcome": outcome}
        ctx.emit("action_executed", payload)
        return {"kind": "action_executed", "payload": payload}
    if outcome in ("ask", "escalate"):
        reason = f"{outcome}: {record['reasoning']}"
        ctx.emit("approval_requested", {"action": "deploy_production",
                                        "amount": rel["blast_radius"],
                                        "reason": reason, "version": rel["version"]})
        ap = ctx.gate.request_approval(
            agent_id=ctx.agent_id, action="deploy_production",
            amount=rel["blast_radius"], reason=reason, payload={"release": rel},
        )
        return {"kind": "approval_requested", "payload": ap.as_dict()}
    ctx.emit("action_denied", {"action": "deploy_production", "version": rel["version"],
                               "reason": record["reasoning"]})
    return {"kind": "action_denied", "payload": {"action": "deploy_production",
                                                 "outcome": outcome}}


# ------------------------------------------------------------------- the fleet

FLEET: list[FleetAgent] = [
    FleetAgent(agent_id="restockbot", name="RestockBot", job="procurement",
               budget_usd=0.05, steps=RESTOCK_STEPS),
    FleetAgent(agent_id="refundbot", name="RefundBot", job="finance",
               budget_usd=0.05, steps=REFUND_STEPS),
    FleetAgent(agent_id="deploybot", name="DeployBot", job="releases",
               budget_usd=0.05, steps=DEPLOY_STEPS),
]

STEP_FN = {
    "restockbot": restock_step,
    "refundbot": refund_step,
    "deploybot": deploy_step,
}
