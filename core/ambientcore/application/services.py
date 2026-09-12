"""AmbientService — the inference loop behind the canvas.

fold (events+state) -> rank (one hypothesis) -> surface (one card). When the
fleet parks a risky action, the INTERFACE initiates the decision: the card
arrives pre-simulated through SimCore with a rollback preview — no human
request involved. Rejections are recorded as MemoryCore correction facts and
demote that intent kind on the next fold: the wrong-guess recovery is part of
the mechanism.

No LLM on the inference/enforcement path. The narrator port only writes the
card's one-line rationale and degrades to scripted offline.
"""

from typing import Any

from core.ambientcore.application.ports import CardStore, Clock, NarratorPort
from core.ambientcore.domain.card import make_card
from core.ambientcore.domain.fold import fold_intents
from core.ambientcore.domain.rank import EXHAUSTION_LIMIT, rank_next

CORRECTION_SLOT_PREFIX = "ambient.correction."
CORRECTION_CONFIDENCE = 0.9  # user_stated corrections are strong signals
AMOUNT_BEARING = {"purchase", "deploy_production", "issue_refund"}


class AmbientService:
    def __init__(
        self,
        *,
        tower: Any,      # TowerService — the fleet being watched
        sim: Any,        # SimService — pre-simulation of amount-bearing actions
        memory: Any,     # MemoryService — operator corrections, receipted
        trust: Any,      # TrustService — receipts for card lifecycle events
        cards: CardStore,
        clock: Clock,
        narrator: NarratorPort,
    ) -> None:
        self._tower = tower
        self._sim = sim
        self._memory = memory
        self._trust = trust
        self._cards = cards
        self._clock = clock
        self._narrator = narrator
        self._seeded = False
        self._agent_keys: dict[str, str] = {}

    # --- seed -----------------------------------------------------------------

    def seed_demo(self) -> dict[str, Any]:
        """Bind to the already-seeded tower fleet (call tower.seed_demo first,
        or let seed_demo do it). Learns the agents' public keys so cards can
        execute through TrustCore authority."""
        if not self._tower._seeded:
            self._tower.seed_demo()
        self._agent_keys = dict(self._tower._keys)
        self._seeded = True
        return {"agents": sorted(self._agent_keys), "beats": [
            {"label": "ambient canvas bound to the live fleet — watching, not chatting"}]}

    # --- the loop ----------------------------------------------------------------

    def canvas(self) -> dict[str, Any]:
        """The whole interface: ambient state + at most ONE active card."""
        self._require_seeded()
        events = self._tower.stream.all()
        fleet = self._tower.fleet_snapshot()
        ledger = self._ledger_snapshot()
        corrections = self._corrections()
        hyps = fold_intents(events, fleet=fleet, corrections=corrections,
                            ledger=ledger)
        verdict = rank_next(hyps, corrections=corrections, raw_events=events)

        active = self._active_card()
        card = None
        if active is not None:
            card = active.as_dict()
        elif verdict.mode == "card" and verdict.hypothesis is not None:
            card = self._surface(verdict.hypothesis).as_dict()

        return {
            "mode": "card" if card else verdict.mode,
            "ambient": self._ambient_line(fleet, verdict.mode),
            "fleet_summary": {a: v["status"] for a, v in fleet.items()},
            "card": card,
            "runner_ups": [h.as_dict() for h in hyps
                           if card is None or h.kind != card["hypothesis"]["kind"]][:3],
            "exhausted_kinds": list(verdict.exhausted_kinds),
            "raw_events": list(verdict.raw_events),
        }

    def _surface(self, hypothesis: Any) -> Any:
        """The interface-initiated action: narrate, pre-simulate, surface."""
        rationale, brain = self._narrator.narrate(hypothesis.as_dict())
        card = make_card(hypothesis=hypothesis, rationale=rationale, brain=brain)
        action = hypothesis.proposed_action
        if action.get("action") in AMOUNT_BEARING and action.get("amount"):
            key = self._agent_keys.get(hypothesis.target)
            if key:
                try:
                    sim = self._sim.simulate(
                        requester_key=key, amount=float(action["amount"]),
                        description=action.get("description", hypothesis.kind))
                    card = card.with_sim({
                        "id": sim["id"],
                        "predicted_effects": sim["predicted_effects"],
                        "rollback_preview": sim["rollback_preview"],
                        "fork_diff": sim["fork_diff"],
                    })
                except Exception as exc:  # noqa: BLE001 — surface the card anyway
                    card = card.with_sim({"error": f"pre-simulation failed: {exc}"})
        self._cards.save(card)
        self._trust.record_event(
            actor="ambient", action="ambient.card_surfaced",
            note=f"{hypothesis.kind} conf={hypothesis.confidence:.2f} "
                 f"demoted={hypothesis.demoted}",
            inputs={"card_id": card.id, "kind": hypothesis.kind,
                    "confidence": hypothesis.confidence,
                    "demoted": hypothesis.demoted, "brain": brain},
        )
        return card

    # --- the human's three verbs ---------------------------------------------------

    def approve(self, card_id: str, *, operator: str) -> dict[str, Any]:
        card = self._require_card(card_id)
        done = card.approve(operator=operator)
        self._cards.save(done)
        self._execute(done)
        self._trust.record_event(
            actor="ambient", action="ambient.card_approved",
            note=f"{done.hypothesis.kind} approved by {operator}",
            inputs={"card_id": card_id, "kind": done.hypothesis.kind})
        return done.as_dict()

    def edit(self, card_id: str, *, operator: str,
             new_action: dict[str, Any]) -> dict[str, Any]:
        card = self._require_card(card_id)
        done = card.edit(operator=operator, new_action=new_action)
        self._cards.save(done)
        self._execute(done)
        self._trust.record_event(
            actor="ambient", action="ambient.card_edited",
            note=f"{done.hypothesis.kind} re-parametrized by {operator}",
            inputs={"card_id": card_id, "from": done.original_action,
                    "to": done.action})
        return done.as_dict()

    def reject(self, card_id: str, *, operator: str, note: str) -> dict[str, Any]:
        card = self._require_card(card_id)
        kind = card.hypothesis.kind
        corrections = self._corrections()
        hits = sum(1 for c in corrections if c["kind"] == kind)
        if hits + 1 >= EXHAUSTION_LIMIT:
            done = card.to_manual(operator=operator, note=note)
            action_name = "ambient.card_manual"
        else:
            done = card.reject(operator=operator, note=note)
            action_name = "ambient.card_rejected"
        self._cards.save(done)
        # the correction is a real MemoryCore fact — receipted, decaying,
        # inspectable — and it demotes this intent kind on the next fold
        self._memory.learn(
            slot=f"{CORRECTION_SLOT_PREFIX}{kind}",
            value=f"rejected: {note}",
            source="operator", kind="user_stated",
            extraction_confidence=CORRECTION_CONFIDENCE,
            user_id="operator", agent_id="ambient",
        )
        self._trust.record_event(
            actor="ambient", action=action_name,
            note=f"{kind} rejected ({hits + 1}x): {note}",
            inputs={"card_id": card_id, "kind": kind, "rejections": hits + 1})
        return done.as_dict()

    def resume_fleet(self, agent_id: str) -> dict[str, Any]:
        """Operator releases a paused agent (used to walk the demo forward)."""
        return self._tower.resume(agent_id, operator="ambient-operator")

    # --- execution through the REAL cores -------------------------------------------

    def _execute(self, card: Any) -> None:
        """Execute the card's action. Parked-approval cards resolve the REAL
        tower approval queue; amount-bearing purchases run the pre-computed
        SimCore simulation."""
        kind = card.hypothesis.kind
        target = card.hypothesis.target
        if kind == "deploy_needs_review":
            for ap in self._tower.pending_approvals():
                if ap.agent_id == target:
                    self._tower.approve(ap.id, operator=card.operator or "operator")
                    return
        if kind == "drift_contain":
            if self._tower.gate.state(target) == "active":
                self._tower.pause(target, operator=card.operator or "operator")
            return
        if kind == "restock_needed" and card.sim and card.sim.get("id"):
            try:
                self._sim.execute(card.sim["id"])
            except ValueError:
                pass  # already resolved elsewhere; the card state stands

    # --- read helpers -----------------------------------------------------------------

    def intents(self) -> dict[str, Any]:
        """All current candidates — the runner-ups the interface chose NOT to
        show. This list is the proof the interface is deciding, not listing."""
        self._require_seeded()
        events = self._tower.stream.all()
        hyps = fold_intents(events, fleet=self._tower.fleet_snapshot(),
                            corrections=self._corrections(),
                            ledger=self._ledger_snapshot())
        return {"intents": [h.as_dict() for h in hyps]}

    def cards(self, *, limit: int = 20) -> dict[str, Any]:
        history = [c.as_dict() for c in self._cards.all()]
        return {"cards": history[-limit:]}

    def _active_card(self) -> Any | None:
        for c in reversed(self._cards.all()):
            if c.state == "surfaced":
                return c
        return None

    def _corrections(self) -> list[dict[str, Any]]:
        out = []
        try:
            facts = self._memory.inspect(user_id="operator", agent_id="ambient")["facts"]
        except Exception:  # noqa: BLE001 — no memory yet is not an error
            return []
        for f in facts:
            slot = f.get("slot", "")
            if slot.startswith(CORRECTION_SLOT_PREFIX):
                out.append({"kind": slot[len(CORRECTION_SLOT_PREFIX):],
                            "note": f.get("value", ""), "ts": f.get("learned_at", "")})
        return out

    def _ledger_snapshot(self) -> dict[str, Any] | None:
        try:
            ledger = self._sim._ledger_store.get()
            return {"projected_balance": ledger.projected_balance(),
                    "limit": self._sim._limit}
        except Exception:  # noqa: BLE001 — budget risk is optional
            return None

    @staticmethod
    def _ambient_line(fleet: dict[str, Any], mode: str) -> str:
        statuses = [v["status"] for v in fleet.values()]
        if mode == "manual":
            return "I've guessed wrong twice — handing you the raw picture."
        if any(s in ("paused", "awaiting_approval") for s in statuses):
            return "Something needs your call. One thing, not twenty."
        if any(s == "killed" for s in statuses):
            return "A rogue was contained. The rest of the fleet is steady."
        return "Fleet steady. Nothing needs you right now."

    def _require_card(self, card_id: str) -> Any:
        card = self._cards.get(card_id)
        if card is None:
            raise ValueError(f"unknown card {card_id}")
        return card

    def _require_seeded(self) -> None:
        if not self._seeded:
            raise ValueError("run /api/ambient/demo first")
