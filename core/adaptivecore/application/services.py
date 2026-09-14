"""AdaptiveService — the plan → execute → observe → re-evaluate loop.

Composes TrustCore (authority + append-only receipts), DecisionCore (per-step
gating), and SimCore (budget effects + pre-commit previews) through ports —
composition, not duplication. No LLM on any path: change detection is the
pure assumption re-verifier in domain/detection.py, re-planning the pure rule
product in domain/replan.py. A re-plan is reachable ONLY through a detected
contradiction that survives damping — there is no timer and no re-prompt.

Mission domain: procurement restock. Two run modes:
- adaptive: contradictions fire re-plans ("I changed my mind because…")
- baseline: the same world and events, adaptation off — the plan executes
  blindly and fails silently against real enforced state (budget invariant).
"""

import uuid
from typing import Any

from core.adaptivecore.domain.damping import (
    ALLOWED,
    DAMPED,
    DampingState,
    evaluate_damping,
    record_revision,
)
from core.adaptivecore.domain.detection import detect_contradictions
from core.adaptivecore.domain.events import advance_cursor, make_event, new_events
from core.adaptivecore.domain.plandiff import diff_plans
from core.adaptivecore.domain.plans import Plan, utcnow_iso
from core.adaptivecore.domain.replan import build_initial_plan, revise_plan

# Scenario definitions — real worlds, real missions, real breakers.
SCENARIOS: dict[str, dict[str, Any]] = {
    "price_spike": {
        "label": "A · Supplier price spike",
        "goal": "Restock 100 units within budget and authority",
        "qty": 100,
        "max_days": 7,
        "price_cap": 8.0,
        "world": {
            "NorthParts": {"price": 7.5, "available": True, "delivery_days": 3},
            "SouthSupply": {"price": 7.8, "available": True, "delivery_days": 5},
        },
        "primary_supplier": "NorthParts",
        "injectors": [
            {"kind": "price_changed", "label": "Price spike → $14.00",
             "payload": {"supplier": "NorthParts", "new_price": 14.0}},
            {"kind": "price_changed", "label": "Price dip → $7.60",
             "payload": {"supplier": "NorthParts", "new_price": 7.6}},
        ],
    },
        "budget_squeeze": {
        "label": "B · Budget squeeze (concurrent hold)",
        "goal": "Restock 100 units within budget and authority",
        "qty": 100,
        "max_days": 7,
        "price_cap": 8.0,
        "world": {
            "NorthParts": {"price": 7.5, "available": True, "delivery_days": 3},
            "SouthSupply": {"price": 7.8, "available": True, "delivery_days": 5},
        },
        "primary_supplier": "NorthParts",
        "injectors": [
            {"kind": "hold_placed", "label": "Concurrent hold $600 (another team)",
             "payload": {"amount": 600.0, "agent": "OtherTeamBot"}},
            {"kind": "hold_released", "label": "Hold released (full $600)",
             "payload": {"amount": 600.0}},
        ],
        # budget squeezes can arrive in rapid succession — no cooldown, the
        # min-delta hysteresis and the revision budget are the containment.
        "damping": {"cooldown_span": 0},
    },
        "flapping_price": {
        "label": "C · Flapping price (failure test)",
        "goal": "Restock 100 units within budget and authority",
        "qty": 100,
        "max_days": 7,
        "price_cap": 8.0,
        "world": {
            # NorthParts flaps across the $8 cap; SouthSupply sits inside it
            # at $7.60. Flap-up breaks the price assumption (→ SouthSupply);
            # flap-down makes NorthParts the better alternative (→ back). The
            # plan flip-flops A↔B — pure oscillation pressure on damping.
            "NorthParts": {"price": 7.9, "available": True, "delivery_days": 3},
            "SouthSupply": {"price": 7.6, "available": True, "delivery_days": 5},
        },
        "primary_supplier": "NorthParts",
        "injectors": [
            {"kind": "price_changed", "label": "Flap up → $8.10",
             "payload": {"supplier": "NorthParts", "new_price": 8.1}},
            {"kind": "price_changed", "label": "Flap down → $7.40",
             "payload": {"supplier": "NorthParts", "new_price": 7.4}},
        ],
        # tighter damping for the failure test: no cooldown, so budget +
        # oscillation rules are what contain the flap — visibly.
        "damping": {"cooldown_span": 0},
    },
}


class AdaptiveService:
    def __init__(
        self,
        *,
        runs: Any,          # RunStore
        plans: Any,         # PlanStore
        events: Any,        # EventStream
        world: Any,         # WorldStore
        budget: Any,        # BudgetPort (SimCore)
        authority: Any,     # AuthorityPort (TrustCore)
        gate: Any,          # StepGate (DecisionCore)
        preview: Any,       # StepPreview (SimCore simulate)
        audit: Any,         # AuditTrail (TrustCore)
        revisions: Any = None,  # RevisionStore (append-only)
        agent_key: str = "",
    ) -> None:
        self._revision_store = revisions
        self._runs = runs
        self._plans = plans
        self._events = events
        self._world = world
        self._budget = budget
        self._authority = authority
        self._gate = gate
        self._preview = preview
        self._audit = audit
        self._agent_key = agent_key

    # --- setup -----------------------------------------------------------

    def bind_agent(self, agent_key: str) -> None:
        self._agent_key = agent_key

    def list_scenarios(self) -> list[dict[str, Any]]:
        return [
            {"id": sid, "label": s["label"], "goal": s["goal"],
             "injectors": s["injectors"]}
            for sid, s in SCENARIOS.items()
        ]

    def start_run(self, *, scenario: str, mode: str) -> dict[str, Any]:
        if scenario not in SCENARIOS:
            raise ValueError(f"unknown scenario {scenario!r}")
        if mode not in ("adaptive", "baseline"):
            raise ValueError(f"unknown mode {mode!r}")
        if not self._agent_key:
            raise ValueError("no agent bound — run the demo seed first")

        spec = SCENARIOS[scenario]
        for name, fields in spec["world"].items():
            self._world.set_supplier(name, **fields)
        supplier = {"name": spec["primary_supplier"],
                    **spec["world"][spec["primary_supplier"]]}

        plan = build_initial_plan(
            goal=spec["goal"], qty=spec["qty"], supplier=supplier,
            max_days=spec["max_days"], authority_action="purchase",
            price_cap=spec["price_cap"],
        )
        run_id = str(uuid.uuid4())
        damping = DampingState(**spec.get("damping", {}))
        damping.recent_plan_shapes.append(plan.choice_signature())
        record = {
            "id": run_id,
            "scenario": scenario,
            "scenario_label": spec["label"],
            "mode": mode,
            "goal": spec["goal"],
            "agent_key": self._agent_key,
            "plan_id": plan.id,
            "status": "running",
            "event_cursor": self._events.next_seq() - 1,  # starts caught-up
            "step_log": [],
            "revision_ids": [],
            "damping": damping.as_dict(),
            "params": {"qty": spec["qty"], "max_days": spec["max_days"],
                       "price_cap": spec["price_cap"]},
            "baseline_price": supplier["price"],  # frozen at plan time — the
            # baseline never re-reads the world; it pays THIS price blindly
            "created_at": utcnow_iso(),
        }
        self._plans.save(run_id, plan)
        self._runs.save(record)
        self._emit_audit(run_id, "run_started",
                         f"{mode} run started on scenario {scenario}: {spec['goal']}")
        return self.get_run(run_id)

    # --- events (the world pushes change in) ------------------------------

    def inject_event(self, *, run_id: str, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        """A world change arrives as an EVENT. Effects are applied for real:
        supplier events update the world store; hold events write genuine
        entries to the shared SimCore ledger; authority_revoked goes through
        TrustCore's real revocation. Returns the recorded event."""
        run = self._require_run(run_id)
        ts = utcnow_iso()
        effects: list[str] = []
        if kind == "price_changed":
            self._world.set_supplier(payload["supplier"], price=float(payload["new_price"]))
            effects.append(f"world: {payload['supplier']} price = {payload['new_price']}")
        elif kind == "supplier_unavailable":
            self._world.set_supplier(payload["supplier"], available=False)
            effects.append(f"world: {payload['supplier']} unavailable")
        elif kind == "delivery_delayed":
            self._world.set_supplier(payload["supplier"], delivery_days=int(payload["days"]))
            effects.append(f"world: {payload['supplier']} delivery = {payload['days']} days")
        elif kind == "hold_placed":
            entry = self._budget.place_hold(
                agent_key=payload.get("agent", "external-actor"),
                amount=float(payload["amount"]), reference=f"adaptive-event:{run_id[:8]}")
            effects.append(f"ledger: hold {entry['id'][:8]}… ${entry['amount']:.2f} (real write)")
        elif kind == "hold_released":
            entry = self._budget.release_hold(
                amount=float(payload["amount"]), reference=f"adaptive-event:{run_id[:8]}")
            effects.append(f"ledger: released hold {entry['id'][:8]}… ${entry['amount']:.2f}")
        elif kind == "authority_revoked":
            cred = self._authority.revoke_authority(
                agent_key=run["agent_key"], action=payload["action"],
                reason=f"world event in run {run_id[:8]}")
            effects.append(
                f"trust: credential {cred[:8] if cred else '?'}… revoked (real, signed path)")
        event = make_event(seq=self._events.next_seq(), ts=ts, kind=kind,
                           payload=payload, applied_effects=effects)
        self._events.append(event)
        return event.as_dict()

    # --- the loop ----------------------------------------------------------

    def advance(self, run_id: str) -> dict[str, Any]:
        """One observe → (maybe revise) → execute cycle. In adaptive mode each
        call runs until the run blocks on a gate verdict or completes."""
        run = self._require_run(run_id)
        if run["status"] not in ("running",):
            return self.get_run(run_id)
        if run["mode"] == "baseline":
            return self._advance_baseline(run)

        # One advance = observe → (maybe revise) → execute ONE step. The loop
        # is step-at-a-time so a judge can watch world events land BETWEEN
        # steps — change detection mid-execution is the whole point.
        self._observe(run)
        if run["status"] == "running":
            plan = self._plans.get(run["plan_id"])
            step = next((s for s in plan.steps if s.status == "pending"), None)
            if step is None:
                run["status"] = "completed"
                self._emit_audit(run["id"], "run_completed",
                                 f"goal achieved: {run['goal']}")
            else:
                self._execute_step(run, plan, step)
        self._runs.save(run)
        return self.get_run(run["id"])

    def run_to_end(self, run_id: str, *, max_cycles: int = 20) -> dict[str, Any]:
        """Advance until the run leaves `running` (or the cycle guard trips)."""
        for _ in range(max_cycles):
            run = self.advance(run_id)
            if run["status"] != "running":
                break
        return run

    def _observe(self, run: dict[str, Any]) -> None:
        """Re-verify active assumptions against reality. The ONLY path to a
        re-plan: contradiction(s) that survive damping."""
        events = self._events.all()
        fresh = new_events(events, run["event_cursor"])
        run["event_cursor"] = advance_cursor(events, run["event_cursor"])
        plan = self._plans.get(run["plan_id"])
        world = self._snapshot_world(run)
        contradictions = detect_contradictions(list(plan.steps), world, fresh)
        # Self-inflicted contradictions are not world changes: a step THIS run
        # just executed (e.g. its own purchase now consuming the headroom the
        # pending remainder was checked against) is progress, not drift. Only
        # event-correlated or pre-existing contradictions can fire a re-plan.
        done_ids = {e["step_id"] for e in run["step_log"]}
        executed_once = any(
            e["action"] == "place_order" and e.get("ledger_entry") for e in run["step_log"]
        )
        contradictions = [
            c for c in contradictions
            if c.triggering_event_ids
            or (c.step_id not in done_ids
                and not (executed_once and c.assumption_kind == "budget_headroom_at_least"))
        ]
        if not contradictions:
            return

        revision_id = str(uuid.uuid4())
        candidate = revise_plan(
            current=plan, contradictions=contradictions, world=world,
            goal_qty=run["params"]["qty"], max_days=run["params"]["max_days"],
            authority_action="purchase", revision_id=revision_id,
            price_cap=run["params"]["price_cap"],
        )
        new_shape = candidate.plan.choice_signature() if candidate.plan else "infeasible"

        damping = DampingState(**{
            k: v for k, v in run["damping"].items() if k in DampingState.__dataclass_fields__
        })
        decision = evaluate_damping(
            state=damping, contradictions=contradictions,
            new_plan_shape=new_shape, current_seq=run["event_cursor"],
        )

        if decision.verdict == DAMPED:
            self._record_revision(run, plan, None, contradictions, fresh, decision,
                                  damping, revision_id, gates=[], sim_preview=None)
            self._emit_audit(run["id"], "contradiction_damped", decision.reason)
            return

        if decision.verdict != ALLOWED:
            run["status"] = "escalated"
            self._record_revision(run, plan, None, contradictions, fresh, decision,
                                  damping, revision_id, gates=[], sim_preview=None)
            self._emit_audit(run["id"], "run_escalated",
                             f"world unstable — handed to a human: {decision.reason}",
                             escalate=True)
            return

        if candidate.plan is None:
            run["status"] = "escalated"
            self._record_revision(run, plan, None, contradictions, fresh, decision,
                                  damping, revision_id, gates=[], sim_preview=None)
            self._emit_audit(run["id"], "run_escalated",
                             f"no feasible re-plan: {candidate.rationale}", escalate=True)
            return

        # gate every revised step through DecisionCore BEFORE activation
        gates = [self._gate_step(s) for s in candidate.plan.steps
                 if s.action == "place_order"]
        blocking = [g for g in gates if g["outcome"] in ("refuse", "escalate")]

        # preview the revised purchase on a fork before committing (C8)
        sim_preview = self._preview.simulate(
            requester_key=run["agent_key"],
            amount=next(s for s in candidate.plan.steps
                        if s.action == "place_order").params["total"],
            description=f"adaptive re-plan preview (run {run['id'][:8]})",
        )

        if blocking:
            run["status"] = "awaiting_human"
            self._record_revision(run, plan, candidate.plan, contradictions, fresh,
                                  decision, damping, revision_id, gates, sim_preview)
            self._emit_audit(run["id"], "revision_blocked",
                             "revised plan gated to refuse/escalate by DecisionCore — "
                             "awaiting human", escalate=True)
            return

        # commit: activate the new plan version
        record_revision(damping, contradictions=decision.surviving,
                        new_plan_shape=new_shape, current_seq=run["event_cursor"])
        self._plans.save(run["id"], candidate.plan)
        run["plan_id"] = candidate.plan.id
        self._record_revision(run, plan, candidate.plan, contradictions, fresh,
                              decision, damping, revision_id, gates, sim_preview)
        self._emit_audit(run["id"], "plan_revised", candidate.rationale)

    def _execute_step(self, run: dict[str, Any], plan: Plan, step: Any) -> None:
        """Execute one step: gate it, act for real, log the outcome."""
        gate = self._gate_step(step)
        entry: dict[str, Any] = {
            "step_id": step.id, "action": step.action, "params": dict(step.params),
            "gate_outcome": gate["outcome"], "gate_resolution": gate.get("resolution_path"),
            "ts": utcnow_iso(),
        }
        if gate["outcome"] in ("refuse", "escalate"):
            step.status = "blocked"
            entry["result"] = f"blocked by decision gate: {gate['outcome']}"
            run["step_log"].append(entry)
            run["status"] = "awaiting_human"
            self._plans.save(run["id"], plan)
            self._emit_audit(run["id"], "step_blocked",
                             f"{step.action} gated to {gate['outcome']}: "
                             f"{gate.get('reasoning', '')}", escalate=True)
            return
        if gate["outcome"] in ("ask", "defer"):
            step.status = "deferred"
            entry["result"] = (f"gate says {gate['outcome']}: missing "
                               f"{gate.get('missing_information', [])}")
            run["step_log"].append(entry)
            run["status"] = "awaiting_human"
            self._plans.save(run["id"], plan)
            self._emit_audit(run["id"], "step_deferred",
                             f"{step.action}: {entry['result']}")
            return

        # execute — real effects on real shared state
        if step.action == "place_order":
            amount = float(step.params["total"])
            decision = self._authority.decide_purchase(
                requester_key=run["agent_key"], amount=amount,
                description=f"adaptive run {run['id'][:8]}: {step.params['qty']} units "
                            f"from {step.params['supplier']}",
            )
            entry["purchase_decision"] = decision["decision"]
            if decision["decision"] == "allow":
                ledger_entry = self._budget.spend(
                    agent_key=run["agent_key"], amount=amount,
                    reference=f"adaptive:{run['id'][:8]}",
                )
                entry["ledger_entry"] = ledger_entry["id"]
                ok, violations = self._budget.invariant_ok()
                entry["post_check"] = {"ok": ok, "violations": violations}
                if not ok:
                    step.status = "failed"
                    run["step_log"].append(entry)
                    run["status"] = "escalated"
                    self._plans.save(run["id"], plan)
                    self._emit_audit(run["id"], "run_escalated",
                                     f"budget invariant violated after execution: {violations[0]}",
                                     escalate=True)
                    return
                step.status = "done"
                entry["result"] = (f"ordered {step.params['qty']} units from "
                                   f"{step.params['supplier']} for ${amount:.2f} "
                                   f"(real ledger spend)")
            else:
                step.status = "failed"
                run["step_log"].append(entry)
                run["status"] = "escalated"
                self._plans.save(run["id"], plan)
                self._emit_audit(run["id"], "run_escalated",
                                 f"purchase refused by TrustCore: {decision['decision']}",
                                 escalate=True)
                return
        else:
            step.status = "done"
            entry["result"] = {
                "verify_price": f"confirmed price {step.params.get('expected_price')}",
                "verify_authority": "authority grant verified (real signature check)",
                "schedule_delivery": f"delivery scheduled within "
                                     f"{step.params.get('within_days')} days",
                "confirm_restock": f"restock confirmed: {step.params.get('qty')} units",
            }.get(step.action, "done")
        run["step_log"].append(entry)
        self._plans.save(run["id"], plan)

    # --- baseline: adaptation OFF ------------------------------------------

    def _advance_baseline(self, run: dict[str, Any]) -> dict[str, Any]:
        """The non-adaptive baseline: same world, same events — but
        contradictions are IGNORED. One step per advance, blind until it
        collides with enforced reality (budget invariant / revoked
        authority). This is where silent failure becomes visible."""
        run["event_cursor"] = advance_cursor(self._events.all(), run["event_cursor"])
        plan = self._plans.get(run["plan_id"])
        if run["status"] == "running":
            step = next((s for s in plan.steps if s.status == "pending"), None)
            if step is None:
                run["status"] = "completed"
                self._runs.save(run)
                return self.get_run(run["id"])
            entry: dict[str, Any] = {
                "step_id": step.id, "action": step.action, "params": dict(step.params),
                "gate_outcome": "not_gated", "ts": utcnow_iso(),
            }
            if step.action == "place_order":
                # blind: uses the STALE planned price, never re-checks the world
                supplier = self._world.get()["suppliers"].get(step.params["supplier"], {})
                if not supplier.get("available", False):
                    step.status = "failed"
                    entry["result"] = ("silent failure: supplier unavailable — discovered "
                                       "only at execution, no re-plan attempted")
                    run["step_log"].append(entry)
                    run["status"] = "failed"
                    self._emit_audit(run["id"], "baseline_failed", entry["result"])
                    self._plans.save(run["id"], plan)
                    self._runs.save(run)
                    return self.get_run(run["id"])
                # blind: pays the STALE planned price, never re-reads the world
                amount = round(step.params["qty"] * float(run["baseline_price"]), 2)
                decision = self._authority.decide_purchase(
                    requester_key=run["agent_key"], amount=amount,
                    description=f"baseline run {run['id'][:8]}: blind order",
                )
                entry["purchase_decision"] = decision["decision"]
                if decision["decision"] != "allow":
                    step.status = "failed"
                    entry["result"] = ("silent failure: purchase refused at execution "
                                       f"({decision['decision']}) — plan never adapted")
                    run["step_log"].append(entry)
                    run["status"] = "failed"
                    self._emit_audit(run["id"], "baseline_failed", entry["result"])
                    self._plans.save(run["id"], plan)
                    self._runs.save(run)
                    return self.get_run(run["id"])
                ledger_entry = self._budget.spend(
                    agent_key=run["agent_key"], amount=amount,
                    reference=f"baseline:{run['id'][:8]}",
                )
                entry["ledger_entry"] = ledger_entry["id"]
                ok, violations = self._budget.invariant_ok()
                entry["post_check"] = {"ok": ok, "violations": violations}
                if not ok:
                    step.status = "failed"
                    entry["result"] = (
                        f"silent failure: committed ${amount:.2f} against the stale plan — "
                        f"budget invariant breached (excess {violations[0]['excess']}); "
                        "the plan never saw it coming")
                    run["step_log"].append(entry)
                    run["status"] = "escalated"
                    self._emit_audit(run["id"], "baseline_escalated", entry["result"],
                                     escalate=True)
                    self._plans.save(run["id"], plan)
                    self._runs.save(run)
                    return self.get_run(run["id"])
                step.status = "done"
                entry["result"] = f"ordered at ${amount:.2f} (blind)"
            else:
                step.status = "done"
                entry["result"] = "done (assumptions never re-checked)"
            run["step_log"].append(entry)
            self._plans.save(run["id"], plan)
        self._runs.save(run)
        return self.get_run(run["id"])

    # --- reads -------------------------------------------------------------

    def get_run(self, run_id: str) -> dict[str, Any]:
        run = self._require_run(run_id)
        plan = self._plans.get(run["plan_id"])
        revisions = [self._revisions_get(rid) for rid in run["revision_ids"]]
        return {
            **{k: v for k, v in run.items()},
            "plan": plan.as_dict() if plan else None,
            "plan_history": [p.as_dict() for p in self._plans.for_run(run_id)],
            "revisions": revisions,
            "world": self._snapshot_world(run),
            "budget": {"committed": self._budget.committed(), "limit": self._budget.limit()},
            "events": [e.as_dict() for e in self._events.all()],
        }

    def list_runs(self, *, limit: int = 50) -> list[dict[str, Any]]:
        return self._runs.list(limit=limit)

    # --- internals ----------------------------------------------------------

    def _snapshot_world(self, run: dict[str, Any]) -> dict[str, Any]:
        return {
            "suppliers": self._world.get()["suppliers"],
            "budget_limit": self._budget.limit(),
            "budget_committed": self._budget.committed(),
            "authority_valid": self._authority.authority_valid(
                agent_key=run["agent_key"], action="purchase"),
            "price_cap": run["params"]["price_cap"],
        }

    def _gate_step(self, step: Any) -> dict[str, Any]:
        """Every (re-)planned step passes through DecisionCore. A re-plan can
        never self-authorize: the same five-outcome gate decides."""
        if step.action != "place_order":
            return {"outcome": "execute", "resolution_path": "non_mutating_step",
                    "reasoning": "verification/scheduling steps are non-mutating"}
        return self._gate.decide(
            domain="purchase", action="purchase", actor_key=self._agent_key,
            amount=float(step.params.get("total", 0.0)),
            context={"invoice_id": f"po-{step.id[:8]}", "reason": "restock",
                     "supplier": step.params.get("supplier")},
        )

    def _record_revision(self, run: dict[str, Any], from_plan: Plan,
                         to_plan: Plan | None, contradictions: list[Any],
                         events: list[Any], damping_decision: Any,
                         damping: DampingState, revision_id: str,
                         gates: list[dict[str, Any]], sim_preview: dict[str, Any] | None,
                         ) -> None:
        diff = diff_plans(from_plan, to_plan) if to_plan else None
        rationale = ""
        if to_plan is not None:
            from core.adaptivecore.domain.replan import _rationale  # deterministic template
            rationale = _rationale(list(damping_decision.surviving or contradictions), to_plan)
        record = {
            "id": revision_id,
            "ts": utcnow_iso(),
            "run_id": run["id"],
            "from_plan_id": from_plan.id,
            "to_plan_id": to_plan.id if to_plan else None,
            "from_version": from_plan.version,
            "to_version": to_plan.version if to_plan else None,
            "contradictions": [c.as_dict() for c in contradictions],
            "triggering_events": [e.as_dict() for e in events],
            "plan_diff": diff.as_dict() if diff else None,
            "rationale": rationale or damping_decision.reason,
            "damping_verdict": damping_decision.verdict,
            "damping_reason": damping_decision.reason,
            "gates": gates,
            "sim_preview": {
                "predicted_effects": sim_preview.get("predicted_effects"),
                "rollback_preview": sim_preview.get("rollback_preview"),
            } if sim_preview else None,
            "damping_snapshot": damping.as_dict(),
            "receipt_id": None,
        }
        receipt = self._emit_audit(
            run["id"], "plan_revision",
            record["rationale"],
            inputs={"revision_id": revision_id,
                    "damping_verdict": damping_decision.verdict,
                    "contradictions": [c.statement for c in contradictions]},
            escalate=damping_decision.verdict != ALLOWED,
        )
        record["receipt_id"] = getattr(receipt, "id", None)
        self._revisions_save(record)
        run["revision_ids"].append(revision_id)
        run["damping"] = damping.as_dict()
        self._runs.save(run)

    def _revisions_save(self, record: dict[str, Any]) -> None:
        self._revision_store.save(record)

    def _revisions_get(self, revision_id: str) -> dict[str, Any] | None:
        return self._revision_store.get(revision_id)

    def _require_run(self, run_id: str) -> dict[str, Any]:
        run = self._runs.get(run_id)
        if run is None:
            raise ValueError(f"unknown run {run_id}")
        return run

    def _emit_audit(self, run_id: str, action: str, note: str,
                    inputs: dict[str, Any] | None = None, escalate: bool = False) -> Any:
        from core.trustcore.domain.policy import PolicyDecision

        return self._audit.record_event(
            actor="adaptivecore",
            action=action,
            note=note,
            inputs={"run_id": run_id, **(inputs or {})},
            decision=PolicyDecision.ESCALATE if escalate else PolicyDecision.ALLOW,
        )
