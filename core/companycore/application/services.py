"""CompanyService: the run-the-week loop. Roles propose; cores enforce; the log is truth."""

from typing import Any

from core.companycore.application.ports import Clock, EventStore, LLMPort
from core.companycore.application.roles import (
    RoleContext,
    finance_step,
    ops_step,
    sales_step,
)
from core.companycore.domain.directives import parse_directive
from core.companycore.domain.events import make_event
from core.companycore.domain.inbox import Inbox
from core.companycore.domain.kpis import kpis as fold_kpis
from core.companycore.domain.ledger import fold_state, replay_day
from core.companycore.domain.scenarios import cash_crunch, normal_week

DAILY_BURN = 1200.0
ROLE_ACTION_SCOPE = {"salesbot": "quote", "opsbot": "purchase_order", "financebot": "payment"}
ROLE_STEP = {"salesbot": sales_step, "opsbot": ops_step, "financebot": finance_step}
ROGUE_REFUSAL_LIMIT = 3


class CompanyService:
    def __init__(self, *, events: EventStore, clock: Clock, llm: LLMPort,
                 trust: Any, decision: Any, memory: Any) -> None:
        self._events = events
        self._clock = clock
        self._llm = llm
        self._trust = trust
        self._decision = decision
        self._memory = memory
        self._inbox = Inbox()
        self._day = 0
        self._keys: dict[str, str] = {}
        self._scenario = normal_week(7)
        self._rogue_sales = False
        self._refusal_streak = 0
        self._seeded = False

    # --- seed ------------------------------------------------------------
    def seed_demo(self, scenario: str = "normal") -> dict[str, Any]:
        from core.companycore.application.demo import seed_company
        out = seed_company(self._trust, self._emit_opening)
        self._keys = out["keys"]
        self._scenario = cash_crunch(7) if scenario == "cash_crunch" else normal_week(7)
        self._seeded = True
        return out

    def _emit_opening(self, actor: str, kind: str, payload: dict) -> None:
        self._events.append(make_event(day=0, seq=self._events.next_seq(),
                                       actor=actor, kind=kind, payload=payload))

    def _emit(self, actor: str, kind: str, payload: dict) -> None:
        self._events.append(make_event(day=self._day, seq=self._events.next_seq(),
                                       actor=actor, kind=kind, payload=payload))

    # --- the day loop ------------------------------------------------------
    def advance_day(self) -> dict[str, Any]:
        if not self._seeded:
            raise ValueError("run seed_demo first")
        self._day += 1
        beats: list[dict[str, Any]] = []
        schedule = self._scenario[min(self._day - 1, len(self._scenario) - 1)]
        # world tick
        for lead in schedule.get("leads", []):
            self._emit("world", "lead_arrived", lead)
        for churn in schedule.get("churn", []):
            self._emit("world", "lead_arrived", churn)
            self._emit("world", "deal_lost", {"lead_id": churn["lead_id"],
                                              "reason": churn.get("reason", "churned")})
            beats.append({"label": f"{churn['customer']} churned (${churn['value']} pipeline lost)"})
        if schedule.get("early_bill"):
            self._emit("world", "bill_received", schedule["early_bill"])
            beats.append({"label": f"early supplier bill ${schedule['early_bill']['amount']} landed"})

        # roles act in order
        for role, step in ROLE_STEP.items():
            beats.extend(self._run_role(role, step))

        # chief of staff (LLM proposes, gate disposes)
        chief_beat, brain = self._run_chief()
        beats.append(chief_beat)

        self._emit("system", "day_ticked", {"day": self._day})
        return {"day": self._day, "kpis": self.kpis(), "beats": beats,
                "inbox": self.inbox(), "chief_brain": brain}

    def _run_role(self, role: str, step: Any) -> list[dict[str, Any]]:
        beats: list[dict[str, Any]] = []
        state = fold_state(self._events.all())
        k = fold_kpis(self._events.all(), current_day=self._day, daily_burn=DAILY_BURN)
        ctx = RoleContext(day=self._day, state=state, kpis=k, keys=self._keys,
                          emit=lambda *a, **kk: None)
        intents = step(ctx)
        if self._rogue_sales and role == "salesbot" and intents:
            for i in intents:
                if i["action"] == "quote":
                    i["amount"] = round(i["amount"] * 3, 2)  # rogue: over-scope over-discount
                    i["payload"]["amount"] = i["amount"]
        for intent in intents:
            beats.extend(self._gate_and_apply(role, intent))
        return beats

    def _gate_and_apply(self, role: str, intent: dict[str, Any]) -> list[dict[str, Any]]:
        beats: list[dict[str, Any]] = []
        action = intent["action"]
        amount = intent.get("amount")
        state = fold_state(self._events.all())
        if state.spend_frozen and action in ("pay", "purchase_order"):
            beats.append({"label": f"{role}: {action} skipped — spend frozen"})
            return beats
        receipt = self._trust.decide(requester_key=self._keys[role],
                                     action=ROLE_ACTION_SCOPE.get(role, action),
                                     amount=amount, description=intent["description"])
        verdict = str(receipt.decision)
        if verdict == "refuse":
            self._refusal_streak += 1
            beats.append({"label": f"{role}: {action} REFUSED — {receipt.reasoning}",
                          "decision": "refuse"})
            if (self._rogue_sales and role == "salesbot"
                    and self._refusal_streak >= ROGUE_REFUSAL_LIMIT):
                self._emit("tower", "role_paused",
                           {"role": "salesbot", "reason": "over-scope refusal streak"})
                beats.append({"label": "SalesBot auto-paused after repeated refusals",
                              "decision": "refuse"})
            return beats
        if verdict == "escalate":
            e = self._inbox.raise_escalation(day=self._day, actor=role,
                                             summary=f"{action} needs a human",
                                             detail=receipt.reasoning)
            self._emit(role, "escalation_raised", {"id": e.id, "action": action,
                                                   "amount": amount})
            beats.append({"label": f"{role}: {action} escalated to human inbox",
                          "decision": "escalate"})
            return beats
        self._apply(role, intent)
        beats.append({"label": f"{role}: {intent['description']} (${amount})",
                      "decision": "allow"})
        return beats

    def _apply(self, role: str, intent: dict[str, Any]) -> None:
        a, p = intent["action"], intent["payload"]
        if a == "quote":
            self._emit(role, "quote_sent", {"lead_id": p["lead_id"], "amount": p["amount"]})
            self._emit(role, "deal_won", {"lead_id": p["lead_id"],
                                          "deal_id": f"D-{p['lead_id']}",
                                          "amount": p["amount"], "units": p["units"],
                                          "unit_cost": p["unit_cost"]})
            self._emit(role, "invoice_issued", {"invoice_id": f"I-{p['lead_id']}",
                                                "deal_id": f"D-{p['lead_id']}",
                                                "customer": p["customer"],
                                                "amount": p["amount"],
                                                "due_day": self._day + 2,
                                                "units": p["units"]})
        elif a == "purchase_order":
            pid = f"P{self._day}-{self._events.next_seq()}"
            self._emit(role, "po_raised", {"po_id": pid, "units": p["units"], "cost": p["cost"],
                                           "receive_day": p["receive_day"]})
            self._emit(role, "po_received", {"po_id": pid, "units": p["units"],
                                             "bill_id": f"B-{pid}", "cost": p["cost"],
                                             "due_day": p["due_day"], "supplier": p["supplier"]})
        elif a == "collect":
            self._emit(role, "invoice_collected", p)
        elif a == "pay":
            self._emit(role, "bill_paid", p)
        elif a == "freeze_spend":
            self._emit(role, "spend_frozen", p)

    def _run_chief(self) -> tuple[dict[str, Any], str]:
        snapshot = {"day": self._day, "kpis": self.kpis(), "inbox": self.inbox()}
        raw, brain = self._llm.propose(snapshot)
        directive = parse_directive(raw)
        self._emit("chiefofstaff", "directive_proposed",
                   {"raw": raw[:300], "brain": brain, **directive.as_dict()})
        if directive.action == "none":
            self._emit("chiefofstaff", "directive_rejected", {"rationale": directive.rationale})
            return ({"label": f"ChiefOfStaff ({brain}): no binding directive — "
                              f"{directive.rationale}"}, brain)
        if directive.action == "freeze_spend":
            self._emit("chiefofstaff", "spend_frozen", {"by": "directive"})
        self._emit("chiefofstaff", "directive_applied", directive.as_dict())
        return ({"label": f"ChiefOfStaff ({brain}): {directive.action} — "
                          f"{directive.rationale}"}, brain)

    # --- read/intervene -----------------------------------------------------
    def resolve_inbox(self, id: str, resolution: str) -> dict[str, Any]:
        e = self._inbox.resolve(id, resolution)
        self._emit("human", "escalation_resolved", {"id": id, "resolution": resolution})
        return e.as_dict()

    def state(self) -> dict[str, Any]:
        return fold_state(self._events.all()).as_dict()

    def kpis(self) -> dict[str, Any]:
        return fold_kpis(self._events.all(), current_day=self._day, daily_burn=DAILY_BURN)

    def replay(self, day: int) -> dict[str, Any]:
        return replay_day(self._events.all(), day).as_dict()

    def events(self) -> list[dict[str, Any]]:
        return self._events.export()

    def inbox(self) -> list[dict[str, Any]]:
        return [e.as_dict() for e in self._inbox.pending()]

    def run_cash_crunch(self) -> dict[str, Any]:
        self._scenario = cash_crunch(7)
        return {"label": "cash-crunch scenario armed; advance days to run it"}

    def inject_rogue_sales(self) -> dict[str, Any]:
        self._rogue_sales = True
        return {"label": "SalesBot objective corrupted: over-discounting armed"}
