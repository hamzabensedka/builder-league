"""TowerService — the control plane's application surface.

Owns the EventStream (spine), the InterventionGate (teeth), the CostMeter and
the fleet's world state. Every intervention and every agent step is appended
to the same append-only log the operator UI reads — one forensic trail.

No LLM anywhere on this path: agents are scripted loops over deterministic
cores; drift detection is pure rules; costs are metered estimates.
"""

from datetime import UTC, datetime
from typing import Any

from core.towercore.application.agents import FLEET, STEP_FN, AgentContext
from core.towercore.application.ports import AuthorityGate, DecisionEngine, SimulationGate
from core.towercore.domain.anomaly import detect_drift
from core.towercore.domain.cost import CostMeter
from core.towercore.domain.events import make_event
from core.towercore.domain.gate import InterventionGate
from core.towercore.domain.registry import fleet_view
from core.towercore.domain.replay import replay as replay_domain
from core.towercore.domain.stream import EventStream

# Simulated metering rates (labeled metered_estimate everywhere they surface)
INPUT_PRICE_PER_1K = 0.003
OUTPUT_PRICE_PER_1K = 0.015


class TowerService:
    def __init__(
        self, *, trust: AuthorityGate, decision: DecisionEngine, sim: SimulationGate,
    ) -> None:
        self._trust = trust
        self._decision = decision
        self._sim = sim
        self.stream = EventStream()
        self.gate = InterventionGate()
        self._cost = CostMeter(input_price_per_1k=INPUT_PRICE_PER_1K,
                               output_price_per_1k=OUTPUT_PRICE_PER_1K)
        self._world: dict[str, Any] = {}
        self._keys: dict[str, str] = {}  # agent_id -> TrustCore public key
        self._rogue: set[str] = set()
        self._budgets = {a.agent_id: a.budget_usd for a in FLEET}
        self._seeded = False

    # --- demo seed -----------------------------------------------------------

    def seed_demo(self) -> dict[str, Any]:
        """Register the fleet with real signed credentials (C1) so every agent
        action is checked against enforced authority. Safe to re-click: fresh
        keypairs each run, and a FULL reset of gate/stream/cost so a previously
        killed or paused fleet comes back clean."""
        from core.towercore.application.demo import seed_fleet

        self.reset()
        result = seed_fleet(self._trust)
        self._keys = result["keys"]
        self._world = {"cursors": {}}
        self._rogue = set()
        self._seeded = True
        for agent in FLEET:
            self._emit(agent.agent_id, "intervention_applied",
                       {"intervention": "enrolled", "operator": "system",
                        "job": agent.job})
        return {"fleet": [{"agent_id": a.agent_id, "name": a.name, "job": a.job,
                           "budget_usd": a.budget_usd} for a in FLEET],
                "beats": result["beats"]}

    def reset(self) -> dict[str, Any]:
        """Reset the whole control plane: control states (killed/paused), the
        event stream, and metered costs. Lets a visitor re-run the demo after
        killing the fleet. Agents must be re-enrolled (seed_demo) afterwards."""
        self.gate.reset()
        self.stream.reset()
        self._cost.reset()
        self._world = {"cursors": {}}
        self._rogue = set()
        self._seeded = False
        return {"status": "reset"}

    # --- the step loop ---------------------------------------------------------

    def advance(self, agent_id: str) -> dict[str, Any]:
        """Advance one agent one step. The gate check inside the step is the
        enforcement point; this wrapper only narrates the outcome."""
        self._require_seeded_agent(agent_id)
        ctx = AgentContext(
            agent_id=agent_id, agent_key=self._keys[agent_id], gate=self.gate,
            emit=lambda kind, payload: self._emit(agent_id, kind, payload),
            trust=self._trust, decision=self._decision, sim=self._sim,
            world=self._world, rogue=agent_id in self._rogue,
        )
        result = STEP_FN[agent_id](ctx, self._world)
        self._after_step(agent_id)
        return result

    def _after_step(self, agent_id: str) -> None:
        """Drift check after every step: a flag auto-pauses the agent through
        the gate and is receipted — containment without human latency. Killed
        agents are left killed; the check re-pauses an agent that was released
        back into the same rogue pattern."""
        if self.gate.state(agent_id) == "killed":
            return
        flags = detect_drift(self.stream, agent_id,
                             budget_usd=self._budgets.get(agent_id, 0.0))
        if flags and self.gate.state(agent_id) in ("active", "awaiting_approval"):
            for f in flags:
                self._emit(agent_id, "drift_flagged",
                           {"kind": f.kind, "summary": f.summary, "detail": f.detail})
            # direct state set: pause() refuses from awaiting_approval, but
            # containment must win over a parked queue entry
            self.gate.force_pause(agent_id)
            self._emit(agent_id, "intervention_applied",
                       {"intervention": "auto_pause", "operator": "tower:anomaly",
                        "reason": flags[0].summary})

    # --- interventions (human in the loop) --------------------------------------

    def pause(self, agent_id: str, *, operator: str) -> dict[str, Any]:
        state = self.gate.pause(agent_id)
        self._emit(agent_id, "intervention_applied",
                   {"intervention": "pause", "operator": operator})
        return {"agent_id": agent_id, "status": state}

    def resume(self, agent_id: str, *, operator: str) -> dict[str, Any]:
        state = self.gate.resume(agent_id)
        self._emit(agent_id, "intervention_applied",
                   {"intervention": "resume", "operator": operator})
        return {"agent_id": agent_id, "status": state}

    def kill(self, agent_id: str, *, operator: str) -> dict[str, Any]:
        state = self.gate.kill(agent_id)
        self._emit(agent_id, "intervention_applied",
                   {"intervention": "kill", "operator": operator})
        return {"agent_id": agent_id, "status": state}

    def approve(self, approval_id: str, *, operator: str) -> dict[str, Any]:
        ap = self.gate.approve(approval_id, operator=operator)
        self._emit(ap.agent_id, "approval_resolved",
                   {"approval_id": ap.id, "status": "approved", "operator": operator,
                    "action": ap.action})
        return ap.as_dict()

    def deny(self, approval_id: str, *, operator: str) -> dict[str, Any]:
        ap = self.gate.deny(approval_id, operator=operator)
        self._emit(ap.agent_id, "approval_resolved",
                   {"approval_id": ap.id, "status": "denied", "operator": operator,
                    "action": ap.action, "skipped": True})
        return ap.as_dict() | {"skipped": True}

    # --- the rogue scenario (failure test lever) ---------------------------------

    def inject_rogue(self, agent_id: str = "deploybot") -> dict[str, Any]:
        """Corrupt an agent's objective mid-run. The tower does not stop this
        directly — enforcement (TrustCore refusals) and drift detection do,
        which is the honest demonstration."""
        self._require_seeded_agent(agent_id)
        self._rogue.add(agent_id)
        self._emit(agent_id, "blocker_raised",
                   {"blocker": "objective corrupted by external injection",
                    "injection": "rogue"})
        return {"agent_id": agent_id, "rogue": True}

    # --- read side ----------------------------------------------------------------

    def fleet_snapshot(self) -> dict[str, dict[str, Any]]:
        return fleet_view(self.stream, self.gate, budgets=self._budgets)

    def pending_approvals(self) -> list[Any]:
        return self.gate.pending_approvals()

    def replay(self, agent_id: str, n: int = 20) -> list[dict[str, Any]]:
        return replay_domain(self.stream, agent_id, n)

    def cost_snapshot(self) -> dict[str, Any]:
        return self._cost.fleet_snapshot()

    def export_audit(self) -> list[dict[str, Any]]:
        """The full stream in canonical form — the compliance export."""
        return self.stream.export()

    # --- internals -------------------------------------------------------------------

    def _emit(self, agent_id: str, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        ev = make_event(
            agent_id=agent_id, run_id="run-1", seq=self.stream.next_seq(agent_id),
            ts=datetime.now(UTC).isoformat(), kind=kind, payload=payload,
        )
        self.stream.append(ev)
        # meter every real core call as a cost event (labeled estimate)
        if kind in ("decision_requested",):
            costed = self._cost.record(agent_id=agent_id, task=ev.run_id,
                                       action_type="decide")
            self._append_cost(agent_id, costed)
        elif kind == "action_executed":
            costed = self._cost.record(agent_id=agent_id, task=ev.run_id,
                                       action_type="execute")
            self._append_cost(agent_id, costed)
        return ev.as_dict()

    def _append_cost(self, agent_id: str, costed: dict[str, Any]) -> None:
        ev = make_event(
            agent_id=agent_id, run_id="run-1", seq=self.stream.next_seq(agent_id),
            ts=datetime.now(UTC).isoformat(), kind="cost_recorded",
            payload={"task": costed["task"], "cost_usd": round(costed["cost_usd"], 6),
                     "tokens": costed["input_tokens"] + costed["output_tokens"],
                     "basis": "metered_estimate"},
        )
        self.stream.append(ev)

    def _require_seeded_agent(self, agent_id: str) -> None:
        if agent_id not in {a.agent_id for a in FLEET}:
            raise ValueError(f"unknown fleet agent {agent_id!r}")
        if not self._seeded:
            raise ValueError("fleet not seeded — call seed_demo first")
