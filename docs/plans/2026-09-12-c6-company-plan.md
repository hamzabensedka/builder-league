# C6 — The Autonomous Company Simulator — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build "AgentCo" — four accountable agent roles (Sales, Ops, Finance, LLM ChiefOfStaff) running a small B2B company as a loop on one event-sourced record system, with a human inbox, KPIs that move, day replay, a self-correction cash-crunch scenario, and a rogue-sales failure test.

**Architecture:** New hexagonal module `core/companycore` (domain pure / application / adapters), composing the existing cores (Trust, Decision, Sim, Memory, Tower) through their public application surfaces only. One append-only `CompanyEvent` log is the spine; ledger, KPIs, inbox, and replay are all folds over it. The LLM (OpenRouter free tier) is propose-only behind an application port with a scripted fallback; the enforcement path stays LLM-free.

**Tech Stack:** Python 3.11, FastAPI, Pydantic, PyNaCl (via existing cores), httpx (OpenRouter adapter), pytest, React 18 + Tailwind (existing UI), import-linter.

## Global Constraints

- Python ≥ 3.11, ruff line-length 100, target py311.
- Domain layer (`core/companycore/domain`) imports NO fastapi/sqlalchemy/redis/requests/httpx/uvicorn — import-linter enforced.
- Application layer imports NO adapter modules, fastapi, or sqlalchemy.
- Cross-core access ONLY via the other cores' `application` + `domain` public surfaces — never their `adapters`, never `api`.
- LLM ONLY behind `core/companycore/application/ports.py` `LLMPort`, implemented in `adapters/llm.py`. No openai/anthropic/litellm imports anywhere in domain/application; OpenRouter is called via `httpx` in the adapter only. Every LLM-free receipt keeps `llm_called=False`; the ChiefOfStaff's directive proposals are the only LLM-touched artifact and are parsed by deterministic domain code before any state change.
- TDD: write the failing test first, watch it fail, implement minimally, watch it pass, commit. Test command: `.venv\Scripts\python.exe -m pytest tests/test_company_<area>.py -v` (Windows). Lint: `.venv\Scripts\python.exe -m ruff check .`; architecture: `.venv\Scripts\lint-imports.exe --config pyproject.toml`.
- Fail-closed everywhere: malformed events rejected at construction, unknown ids 404, double-resolve 409, over-scope actions cryptographically refused.
- Deterministic demos/tests: scenario RNG seeded; the ChiefOfStaff in tests and in `/api/company/demo` uses the scripted fallback unless `OPENROUTER_API_KEY` is set.
- Git: commit per task, message `feat(companycore): ...` / `test(companycore): ...` / `docs: ...`.

---

### Task 1: Scaffold + CompanyEvent + EventLog (domain spine)

**Files:**
- Create: `core/companycore/__init__.py` (empty)
- Create: `core/companycore/domain/__init__.py` (empty)
- Create: `core/companycore/domain/events.py`
- Create: `core/companycore/domain/log.py`
- Test: `tests/test_company_events.py`

**Interfaces:**
- Produces: `CompanyEvent(id: str, day: int, seq: int, actor: str, kind: str, payload: dict)`, `EVENT_KINDS: frozenset[str]`, `make_event(*, day, seq, actor, kind, payload) -> CompanyEvent` (validates; raises `ValueError` on bad kind/empty actor/empty id/negative day/negative seq), `CompanyEvent.as_dict() -> dict`.
- Produces: `EventLog` with `append(event) -> None` (rejects seq gaps per company: next seq must be exactly `self._next_seq`), `tail(n: int) -> list[CompanyEvent]`, `events_for_day(day: int) -> list[CompanyEvent]`, `all() -> list[CompanyEvent]`, `export() -> list[dict]`, `next_seq() -> int`.

Event kinds (exact set):
`lead_arrived, quote_sent, deal_won, deal_lost, invoice_issued, invoice_collected, po_raised, po_received, bill_received, bill_paid, spend_frozen, spend_unfrozen, escalation_raised, escalation_resolved, directive_proposed, directive_applied, directive_rejected, role_paused, role_restored, day_ticked`

- [ ] **Step 1: Write the failing test**

```python
import pytest
from core.companycore.domain.events import EVENT_KINDS, make_event
from core.companycore.domain.log import EventLog


def test_make_event_valid():
    e = make_event(day=0, seq=0, actor="salesbot", kind="lead_arrived",
                   payload={"lead_id": "L1", "value": 4200})
    assert e.kind == "lead_arrived" and e.seq == 0
    assert e.as_dict()["actor"] == "salesbot"


def test_make_event_rejects_unknown_kind():
    with pytest.raises(ValueError):
        make_event(day=0, seq=0, actor="salesbot", kind="nonsense", payload={})


def test_make_event_rejects_empty_actor():
    with pytest.raises(ValueError):
        make_event(day=0, seq=0, actor="", kind="lead_arrived", payload={})


def test_all_event_kinds_present():
    for k in ["lead_arrived", "quote_sent", "deal_won", "deal_lost", "invoice_issued",
              "invoice_collected", "po_raised", "po_received", "bill_received",
              "bill_paid", "spend_frozen", "spend_unfrozen", "escalation_raised",
              "escalation_resolved", "directive_proposed", "directive_applied",
              "directive_rejected", "role_paused", "role_restored", "day_ticked"]:
        assert k in EVENT_KINDS


def test_log_append_and_tail():
    log = EventLog()
    log.append(make_event(day=0, seq=0, actor="salesbot", kind="lead_arrived", payload={}))
    log.append(make_event(day=0, seq=1, actor="opsbot", kind="po_raised", payload={}))
    assert log.next_seq() == 2
    assert [e.kind for e in log.tail(1)] == ["po_raised"]


def test_log_rejects_seq_gap():
    log = EventLog()
    log.append(make_event(day=0, seq=0, actor="salesbot", kind="lead_arrived", payload={}))
    with pytest.raises(ValueError):
        log.append(make_event(day=0, seq=5, actor="opsbot", kind="po_raised", payload={}))


def test_events_for_day_and_export():
    log = EventLog()
    log.append(make_event(day=0, seq=0, actor="salesbot", kind="lead_arrived", payload={}))
    log.append(make_event(day=1, seq=1, actor="financebot", kind="bill_paid", payload={}))
    assert len(log.events_for_day(0)) == 1
    assert len(log.events_for_day(1)) == 1
    assert isinstance(log.export()[0], dict)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_company_events.py -v`
Expected: FAIL (ModuleNotFoundError: core.companycore)

- [ ] **Step 3: Write minimal implementation**

`core/companycore/domain/events.py`:

```python
"""Typed company events: the one shared record every role writes to."""

import uuid
from dataclasses import dataclass, field
from typing import Any

EVENT_KINDS = frozenset({
    "lead_arrived", "quote_sent", "deal_won", "deal_lost", "invoice_issued",
    "invoice_collected", "po_raised", "po_received", "bill_received",
    "bill_paid", "spend_frozen", "spend_unfrozen", "escalation_raised",
    "escalation_resolved", "directive_proposed", "directive_applied",
    "directive_rejected", "role_paused", "role_restored", "day_ticked",
})


@dataclass(frozen=True)
class CompanyEvent:
    id: str
    day: int
    seq: int
    actor: str
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "day": self.day, "seq": self.seq,
                "actor": self.actor, "kind": self.kind, "payload": self.payload}


def make_event(*, day: int, seq: int, actor: str, kind: str,
               payload: dict[str, Any] | None = None) -> CompanyEvent:
    """Fail-closed constructor: unknown kind, empty actor, or bad numbers raise."""
    if kind not in EVENT_KINDS:
        raise ValueError(f"unknown event kind {kind!r}")
    if not actor:
        raise ValueError("actor must be non-empty")
    if day < 0 or seq < 0:
        raise ValueError("day and seq must be >= 0")
    return CompanyEvent(id=str(uuid.uuid4()), day=day, seq=seq, actor=actor,
                        kind=kind, payload=payload or {})
```

`core/companycore/domain/log.py`:

```python
"""Append-only event log: the company spine. Seq is contiguous; a gap is an error."""

from core.companycore.domain.events import CompanyEvent


class EventLog:
    def __init__(self) -> None:
        self._events: list[CompanyEvent] = []

    def append(self, event: CompanyEvent) -> None:
        if event.seq != len(self._events):
            raise ValueError(
                f"seq gap: expected {len(self._events)}, got {event.seq}")
        self._events.append(event)

    def next_seq(self) -> int:
        return len(self._events)

    def all(self) -> list[CompanyEvent]:
        return list(self._events)

    def tail(self, n: int) -> list[CompanyEvent]:
        return self._events[-n:]

    def events_for_day(self, day: int) -> list[CompanyEvent]:
        return [e for e in self._events if e.day == day]

    def export(self) -> list[dict]:
        return [e.as_dict() for e in self._events]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest tests/test_company_events.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add core/companycore tests/test_company_events.py
git commit -m "feat(companycore): typed events + append-only log (spine)"
```

---

### Task 2: Ledger fold + KPI fold + day replay

**Files:**
- Create: `core/companycore/domain/ledger.py`
- Create: `core/companycore/domain/kpis.py`
- Test: `tests/test_company_ledger.py`

**Interfaces:**
- Consumes: `EventLog`, `CompanyEvent` from Task 1.
- Produces: `CompanyState` dataclass: `cash: float, inventory: int, pipeline: dict[str, dict], ar: dict[str, dict], ap: dict[str, dict], spend_frozen: bool, roles_paused: set[str]` with `as_dict()`.
- Produces: `fold_state(events: list[CompanyEvent]) -> CompanyState` — pure; reduces events in seq order. Event payload effects:
  - `deal_won{deal_id, amount, units}` → cash unchanged (invoiced), inventory -= units, pipeline remove, add ar entry via paired `invoice_issued`
  - `invoice_issued{invoice_id, deal_id, customer, amount, due_day}` → ar[invoice_id] = {...}
  - `invoice_collected{invoice_id, amount}` → cash += amount, ar remove
  - `po_raised{po_id, units, cost, receive_day}` → no cash yet (pay on receipt), add to pipeline-inbound
  - `po_received{po_id, units, bill_id, cost, due_day}` → inventory += units, ap[bill_id] = cost
  - `bill_received{bill_id, supplier, amount, due_day}` → ap[bill_id] = {...}
  - `bill_paid{bill_id, amount}` → cash -= amount, ap remove
  - `spend_frozen{}/spend_unfrozen{}` → toggle spend_frozen
  - `role_paused{role}/role_restored{role}` → roles_paused add/remove
  - `lead_arrived{lead_id, customer, value, units}` → pipeline[lead_id] = {...}
  - `quote_sent{lead_id, amount}` → pipeline[lead_id]["quoted"] = amount
  - `deal_lost{lead_id, reason}` → pipeline remove
- Produces: `replay_day(events: list[CompanyEvent], day: int) -> CompanyState` = `fold_state([e for e in events if e.day <= day])`.
- Produces: `kpis(events: list[CompanyEvent], *, current_day: int, daily_burn: float) -> dict` with keys `revenue, cost, backlog_units, churn, margin, runway_days, cash` where revenue = sum(invoice_issued.amount), cost = sum(bill_paid.amount) + burn, churn = deal_lost count / max(deals closed,1), margin = (revenue - cogs)/max(revenue,1) with cogs from deal_won units × unit cost carried in payload, runway_days = cash / max(daily_burn, 1).

- [ ] **Step 1: Write the failing test**

```python
from core.companycore.domain.events import make_event
from core.companycore.domain.kpis import kpis
from core.companycore.domain.ledger import fold_state, replay_day


def _ev(seq, kind, payload, day=0, actor="salesbot"):
    return make_event(day=day, seq=seq, actor=actor, kind=kind, payload=payload)


def test_fold_invoice_collect_and_bill_pay():
    events = [
        _ev(0, "lead_arrived", {"lead_id": "L1", "customer": "Acme", "value": 4200, "units": 10}),
        _ev(1, "quote_sent", {"lead_id": "L1", "amount": 4200}),
        _ev(2, "deal_won", {"lead_id": "L1", "deal_id": "D1", "amount": 4200, "units": 10, "unit_cost": 200}),
        _ev(3, "invoice_issued", {"invoice_id": "I1", "deal_id": "D1", "customer": "Acme", "amount": 4200, "due_day": 2}),
        _ev(4, "invoice_collected", {"invoice_id": "I1", "amount": 4200}, day=2, actor="financebot"),
        _ev(5, "bill_received", {"bill_id": "B1", "supplier": "SouthSupply", "amount": 2000, "due_day": 1}, actor="opsbot"),
        _ev(6, "bill_paid", {"bill_id": "B1", "amount": 2000}, day=1, actor="financebot"),
    ]
    s = fold_state(events)
    assert s.cash == 4200 - 2000
    assert "I1" not in s.ar and "B1" not in s.ap
    assert "L1" not in s.pipeline


def test_inventory_moves_on_deal_and_receipt():
    events = [
        _ev(0, "po_received", {"po_id": "P1", "units": 50, "bill_id": "B1", "cost": 5000, "due_day": 1}, actor="opsbot"),
        _ev(1, "deal_won", {"lead_id": "L1", "deal_id": "D1", "amount": 4200, "units": 10, "unit_cost": 200}),
    ]
    s = fold_state(events)
    assert s.inventory == 40


def test_replay_day_cutoff():
    events = [
        _ev(0, "invoice_collected", {"invoice_id": "I1", "amount": 1000}, day=0, actor="financebot"),
        _ev(1, "invoice_collected", {"invoice_id": "I2", "amount": 2000}, day=3, actor="financebot"),
    ]
    assert replay_day(events, 0).cash == 1000
    assert replay_day(events, 3).cash == 3000


def test_freeze_and_pause_flags():
    events = [
        _ev(0, "spend_frozen", {}, actor="financebot"),
        _ev(1, "role_paused", {"role": "salesbot"}, actor="tower"),
    ]
    s = fold_state(events)
    assert s.spend_frozen is True and "salesbot" in s.roles_paused


def test_kpis_move():
    events = [
        _ev(0, "invoice_issued", {"invoice_id": "I1", "deal_id": "D1", "customer": "Acme", "amount": 4200, "due_day": 2}),
        _ev(1, "deal_won", {"lead_id": "L1", "deal_id": "D1", "amount": 4200, "units": 10, "unit_cost": 200}),
        _ev(2, "deal_lost", {"lead_id": "L2", "reason": "price"}),
        _ev(3, "invoice_collected", {"invoice_id": "I1", "amount": 4200}, actor="financebot"),
        _ev(4, "bill_paid", {"bill_id": "B1", "amount": 2000}, actor="financebot"),
    ]
    k = kpis(events, current_day=1, daily_burn=1200.0)
    assert k["revenue"] == 4200
    assert k["cash"] == 2200
    assert 0 < k["churn"] <= 1
    assert k["runway_days"] > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_company_ledger.py -v`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Write minimal implementation**

`core/companycore/domain/ledger.py`:

```python
"""Pure fold: events -> company state. Replay is a cutoff fold."""

from dataclasses import dataclass, field
from typing import Any

from core.companycore.domain.events import CompanyEvent


@dataclass
class CompanyState:
    cash: float = 0.0
    inventory: int = 0
    pipeline: dict[str, dict[str, Any]] = field(default_factory=dict)
    ar: dict[str, dict[str, Any]] = field(default_factory=dict)
    ap: dict[str, dict[str, Any]] = field(default_factory=dict)
    spend_frozen: bool = False
    roles_paused: set[str] = field(default_factory=set)

    def as_dict(self) -> dict[str, Any]:
        return {
            "cash": round(self.cash, 2),
            "inventory": self.inventory,
            "pipeline": self.pipeline,
            "ar": self.ar,
            "ap": self.ap,
            "spend_frozen": self.spend_frozen,
            "roles_paused": sorted(self.roles_paused),
        }


def fold_state(events: list[CompanyEvent]) -> CompanyState:
    s = CompanyState()
    for e in sorted(events, key=lambda x: x.seq):
        p = e.payload
        if e.kind == "lead_arrived":
            s.pipeline[p["lead_id"]] = dict(p)
        elif e.kind == "quote_sent":
            s.pipeline.setdefault(p["lead_id"], {})["quoted"] = p["amount"]
        elif e.kind == "deal_won":
            s.pipeline.pop(p["lead_id"], None)
            s.inventory -= int(p.get("units", 0))
        elif e.kind == "deal_lost":
            s.pipeline.pop(p["lead_id"], None)
        elif e.kind == "invoice_issued":
            s.ar[p["invoice_id"]] = dict(p)
        elif e.kind == "invoice_collected":
            s.cash += float(p["amount"])
            s.ar.pop(p["invoice_id"], None)
        elif e.kind == "po_received":
            s.inventory += int(p.get("units", 0))
            s.ap[p["bill_id"]] = {"bill_id": p["bill_id"], "amount": p["cost"],
                                  "due_day": p.get("due_day", 0), "supplier": p.get("supplier", "")}
        elif e.kind == "bill_received":
            s.ap[p["bill_id"]] = dict(p)
        elif e.kind == "bill_paid":
            s.cash -= float(p["amount"])
            s.ap.pop(p["bill_id"], None)
        elif e.kind == "spend_frozen":
            s.spend_frozen = True
        elif e.kind == "spend_unfrozen":
            s.spend_frozen = False
        elif e.kind == "role_paused":
            s.roles_paused.add(p["role"])
        elif e.kind == "role_restored":
            s.roles_paused.discard(p["role"])
    return s


def replay_day(events: list[CompanyEvent], day: int) -> CompanyState:
    return fold_state([e for e in events if e.day <= day])
```

`core/companycore/domain/kpis.py`:

```python
"""KPIs are a fold over the same log — the UI can never show state the spine didn't record."""

from typing import Any

from core.companycore.domain.events import CompanyEvent
from core.companycore.domain.ledger import fold_state


def kpis(events: list[CompanyEvent], *, current_day: int, daily_burn: float) -> dict[str, Any]:
    s = fold_state(events)
    revenue = sum(float(e.payload["amount"]) for e in events if e.kind == "invoice_issued")
    cogs = sum(float(e.payload.get("units", 0)) * float(e.payload.get("unit_cost", 0))
               for e in events if e.kind == "deal_won")
    paid = sum(float(e.payload["amount"]) for e in events if e.kind == "bill_paid")
    won = sum(1 for e in events if e.kind == "deal_won")
    lost = sum(1 for e in events if e.kind == "deal_lost")
    closed = won + lost
    backlog = sum(int(p.get("units", 0)) for p in s.pipeline.values())
    backlog += sum(int(v.get("units", 0)) for v in s.ar.values())
    burn = max(daily_burn, 1.0)
    return {
        "day": current_day,
        "cash": round(s.cash, 2),
        "revenue": round(revenue, 2),
        "cost": round(paid + daily_burn * (current_day + 1), 2),
        "cogs": round(cogs, 2),
        "margin": round((revenue - cogs) / revenue, 3) if revenue > 0 else 0.0,
        "churn": round(lost / closed, 3) if closed else 0.0,
        "backlog_units": backlog,
        "runway_days": round(s.cash / burn, 1),
        "spend_frozen": s.spend_frozen,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest tests/test_company_ledger.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add core/companycore/domain/ledger.py core/companycore/domain/kpis.py tests/test_company_ledger.py
git commit -m "feat(companycore): ledger fold, KPI fold, day replay"
```

---

### Task 3: Inbox (human escalations) + Directives (LLM choke point)

**Files:**
- Create: `core/companycore/domain/inbox.py`
- Create: `core/companycore/domain/directives.py`
- Test: `tests/test_company_inbox.py`

**Interfaces:**
- Produces: `Escalation` dataclass `id, day, actor, summary, detail, resolved: bool, resolution: str | None`; `Inbox` with `raise(*, id, day, actor, summary, detail) -> Escalation`, `resolve(id, resolution) -> Escalation` (raises `ValueError` unknown id, `ValueError` double-resolve), `pending() -> list[Escalation]`, `all() -> list[Escalation]`.
- Produces: `Directive` dataclass `action: str, target: str, amount_cap: float | None, rationale: str`; `DIRECTIVE_ACTIONS = frozenset({"freeze_spend","accelerate_collections","accept_discount","defer_po","none"})`; `parse_directive(text: str) -> Directive` — strict: finds a JSON object in the text, validates `action` in the set, coerces fields; on any parse/validation failure returns `Directive(action="none", target="", amount_cap=None, rationale=f"unparseable: {reason}")` — NEVER raises, so the LLM can only ever produce a typed, gated artifact.

- [ ] **Step 1: Write the failing test**

```python
import pytest
from core.companycore.domain.directives import DIRECTIVE_ACTIONS, parse_directive
from core.companycore.domain.inbox import Inbox


def test_inbox_raise_and_resolve():
    box = Inbox()
    e = box.raise_escalation(id="E1", day=1, actor="financebot",
                             summary="Runway critical", detail="runway 12 days")
    assert e.resolved is False
    box.resolve("E1", "approved emergency spend")
    assert box.pending() == []
    assert box.all()[0].resolution == "approved emergency spend"


def test_inbox_unknown_and_double_resolve():
    box = Inbox()
    box.raise_escalation(id="E1", day=1, actor="financebot", summary="s", detail="d")
    with pytest.raises(ValueError):
        box.resolve("NOPE", "x")
    box.resolve("E1", "ok")
    with pytest.raises(ValueError):
        box.resolve("E1", "again")


def test_parse_valid_directive():
    d = parse_directive('Here is my call: {"action":"freeze_spend","target":"discretionary","amount_cap":null,"rationale":"runway 18 days"}')
    assert d.action == "freeze_spend"
    assert d.rationale == "runway 18 days"


def test_parse_rejects_unknown_action():
    d = parse_directive('{"action":"launch_rocket","target":"moon","amount_cap":null,"rationale":"x"}')
    assert d.action == "none"
    assert "unparseable" in d.rationale or "unknown" in d.rationale


def test_parse_garbage_is_safe():
    d = parse_directive("I think we should probably do something about cash maybe")
    assert d.action == "none"


def test_directive_actions_set():
    for a in ["freeze_spend", "accelerate_collections", "accept_discount", "defer_po", "none"]:
        assert a in DIRECTIVE_ACTIONS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_company_inbox.py -v`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Write minimal implementation**

`core/companycore/domain/inbox.py`:

```python
"""Human escalation inbox: ask/escalate outcomes park here, never execute silently."""

import uuid
from dataclasses import dataclass


@dataclass
class Escalation:
    id: str
    day: int
    actor: str
    summary: str
    detail: str
    resolved: bool = False
    resolution: str | None = None

    def as_dict(self) -> dict:
        return {"id": self.id, "day": self.day, "actor": self.actor,
                "summary": self.summary, "detail": self.detail,
                "resolved": self.resolved, "resolution": self.resolution}


class Inbox:
    def __init__(self) -> None:
        self._items: dict[str, Escalation] = {}

    def raise_escalation(self, *, id: str | None = None, day: int, actor: str,
                         summary: str, detail: str) -> Escalation:
        e = Escalation(id=id or str(uuid.uuid4()), day=day, actor=actor,
                       summary=summary, detail=detail)
        self._items[e.id] = e
        return e

    def resolve(self, id: str, resolution: str) -> Escalation:
        e = self._items.get(id)
        if e is None:
            raise ValueError(f"unknown escalation {id}")
        if e.resolved:
            raise ValueError(f"escalation {id} already resolved")
        e.resolved = True
        e.resolution = resolution
        return e

    def pending(self) -> list[Escalation]:
        return [e for e in self._items.values() if not e.resolved]

    def all(self) -> list[Escalation]:
        return list(self._items.values())
```

`core/companycore/domain/directives.py`:

```python
"""The deterministic choke point on the LLM path.

The ChiefOfStaff LLM emits free text; this module extracts and validates a
typed Directive. Anything unparseable, unknown, or malformed becomes a
harmless action="none" — the LLM can NEVER produce an un-gated state change.
"""

import json
import re
from dataclasses import dataclass

DIRECTIVE_ACTIONS = frozenset({
    "freeze_spend", "accelerate_collections", "accept_discount", "defer_po", "none",
})


@dataclass(frozen=True)
class Directive:
    action: str
    target: str
    amount_cap: float | None
    rationale: str

    def as_dict(self) -> dict:
        return {"action": self.action, "target": self.target,
                "amount_cap": self.amount_cap, "rationale": self.rationale}


def _none(reason: str) -> Directive:
    return Directive(action="none", target="", amount_cap=None, rationale=reason)


def parse_directive(text: str) -> Directive:
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not m:
        return _none("unparseable: no JSON object in LLM output")
    try:
        data = json.loads(m.group(0))
    except (json.JSONDecodeError, ValueError):
        return _none("unparseable: invalid JSON")
    action = data.get("action")
    if action not in DIRECTIVE_ACTIONS:
        return _none(f"unknown action {action!r}")
    cap = data.get("amount_cap")
    try:
        cap = None if cap is None else float(cap)
    except (TypeError, ValueError):
        return _none("unparseable: amount_cap not a number")
    return Directive(
        action=action,
        target=str(data.get("target", ""))[:100],
        amount_cap=cap,
        rationale=str(data.get("rationale", ""))[:500],
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest tests/test_company_inbox.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add core/companycore/domain/inbox.py core/companycore/domain/directives.py tests/test_company_inbox.py
git commit -m "feat(companycore): human inbox + LLM directive choke point"
```

---

### Task 4: Ports + roles (Sales/Ops/Finance policies) + scenario world generator

**Files:**
- Create: `core/companycore/application/__init__.py` (empty)
- Create: `core/companycore/application/ports.py`
- Create: `core/companycore/application/roles.py`
- Create: `core/companycore/domain/scenarios.py`
- Test: `tests/test_company_roles.py`

**Interfaces:**
- Consumes: Tasks 1–3; `TrustService.decide(requester_key, action, amount, description)` returning a `Receipt` with `.decision` (`PolicyDecision` ALLOW/REFUSE/ESCALATE); `DecisionService.decide(domain, action, actor_key, amount, context)` returning dict with `outcome`; `MemoryService.recall(query, user_id, agent_id)` returning dict with `verdict` and `facts`.
- Produces: `ports.py` Protocols — `EventStore(append, all, tail, export, next_seq)`, `Clock(now) -> datetime`, `LLMPort(propose(snapshot: dict) -> tuple[str, str])` returning `(raw_text, brain_label)` where brain_label ∈ {"llm","scripted"}.
- Produces: `scenarios.py` — `normal_week(seed=7) -> list[dict]` and `cash_crunch(seed=7) -> list[dict]`, each a list of 7 day-schedules; a day-schedule is `{"leads": [{"lead_id","customer","value","units"}...], "ar_due": [...], "ap_due": [...], "churn": [...]}`. Deterministic for a fixed seed.
- Produces: `roles.py` — `class RoleContext` dataclass carrying `day, state, kpis, keys: dict[str,str], emit: Callable`, and the three policy functions `sales_step(ctx) -> list[dict]`, `ops_step(ctx) -> list[dict]`, `finance_step(ctx) -> list[dict]`, each returning a list of "intended action" dicts `{"action","amount","description","payload"}` for the service to gate+apply. Policies are deterministic and reference `ctx.state.spend_frozen`, `ctx.state.roles_paused`, `ctx.kpis["runway_days"]`.

Design note: roles RETURN intents; `CompanyService` (Task 5) runs them through Trust/Decision/Sim and appends events. This keeps roles pure/testable and enforcement centralized.

- [ ] **Step 1: Write the failing test**

```python
from core.companycore.application.roles import RoleContext, finance_step, ops_step, sales_step
from core.companycore.domain.events import make_event
from core.companycore.domain.kpis import kpis
from core.companycore.domain.ledger import fold_state
from core.companycore.domain.scenarios import cash_crunch, normal_week


def _ctx(events, day=0):
    state = fold_state(events)
    k = kpis(events, current_day=day, daily_burn=1200.0)
    return RoleContext(day=day, state=state, kpis=k, keys={}, emit=lambda *a, **k: None)


def test_scenarios_deterministic():
    assert normal_week(7) == normal_week(7)
    assert cash_crunch(7) == cash_crunch(7)
    assert len(normal_week(7)) == 7


def test_sales_quotes_highest_open_lead():
    events = [
        make_event(day=0, seq=0, actor="world", kind="lead_arrived",
                   payload={"lead_id": "L1", "customer": "Acme", "value": 4200, "units": 10}),
        make_event(day=0, seq=1, actor="world", kind="lead_arrived",
                   payload={"lead_id": "L2", "customer": "Globex", "value": 9000, "units": 20}),
    ]
    intents = sales_step(_ctx(events))
    assert intents and intents[0]["payload"]["lead_id"] == "L2"


def test_ops_raises_po_when_inventory_low():
    events = [
        make_event(day=0, seq=0, actor="world", kind="lead_arrived",
                   payload={"lead_id": "L1", "customer": "Acme", "value": 4200, "units": 100}),
    ]
    intents = ops_step(_ctx(events))
    assert any(i["action"] == "purchase_order" for i in intents)


def test_finance_collects_due_ar_and_freezes_on_low_runway():
    events = [
        make_event(day=0, seq=0, actor="salesbot", kind="invoice_issued",
                   payload={"invoice_id": "I1", "deal_id": "D1", "customer": "Acme",
                            "amount": 1000, "due_day": 0}),
        make_event(day=0, seq=1, actor="financebot", kind="bill_paid",
                   payload={"bill_id": "B0", "amount": 49900}),  # cash now -48900 -> runway negative
    ]
    ctx = _ctx(events, day=0)
    intents = finance_step(ctx)
    actions = [i["action"] for i in intents]
    assert "collect" in actions
    assert "freeze_spend" in actions


def test_finance_pays_due_bill_unless_frozen():
    events = [
        make_event(day=0, seq=0, actor="opsbot", kind="bill_received",
                   payload={"bill_id": "B1", "supplier": "SouthSupply", "amount": 500, "due_day": 0}),
        make_event(day=0, seq=1, actor="financebot", kind="invoice_collected",
                   payload={"invoice_id": "I0", "amount": 50000}),
    ]
    intents = finance_step(_ctx(events, day=0))
    assert any(i["action"] == "pay" and i["payload"]["bill_id"] == "B1" for i in intents)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_company_roles.py -v`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Write minimal implementation**

`core/companycore/application/ports.py`:

```python
"""Ports the company application depends on. Adapters implement these."""

from datetime import datetime
from typing import Any, Protocol

from core.companycore.domain.events import CompanyEvent


class EventStore(Protocol):
    def append(self, event: CompanyEvent) -> None: ...
    def all(self) -> list[CompanyEvent]: ...
    def tail(self, n: int) -> list[CompanyEvent]: ...
    def export(self) -> list[dict[str, Any]]: ...
    def next_seq(self) -> int: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


class LLMPort(Protocol):
    """The ONLY LLM seam. Returns (raw_text, brain_label); brain in {"llm","scripted"}."""

    def propose(self, snapshot: dict[str, Any]) -> tuple[str, str]: ...
```

`core/companycore/application/roles.py`:

```python
"""Role policies. Deterministic; they RETURN intents — the service gates and applies them."""

from dataclasses import dataclass
from typing import Any, Callable

from core.companycore.domain.ledger import CompanyState

RUNWAY_FREEZE_DAYS = 21.0
RUNWAY_CRITICAL_DAYS = 14.0
MARGIN = 1.4
UNIT_COST = 200.0
LOW_STOCK_FACTOR = 1.5


@dataclass
class RoleContext:
    day: int
    state: CompanyState
    kpis: dict[str, Any]
    keys: dict[str, str]
    emit: Callable[..., None]


def sales_step(ctx: RoleContext) -> list[dict[str, Any]]:
    if "salesbot" in ctx.state.roles_paused:
        return []
    open_leads = [
        {"lead_id": lid, **p}
        for lid, p in ctx.state.pipeline.items()
        if "quoted" not in p
    ]
    if not open_leads:
        return []
    lead = max(open_leads, key=lambda l: l.get("value", 0))
    amount = round(float(lead.get("units", 0)) * UNIT_COST * MARGIN, 2)
    return [{
        "action": "quote",
        "amount": amount,
        "description": f"quote {lead['lead_id']} to {lead.get('customer')}",
        "payload": {"lead_id": lead["lead_id"], "customer": lead.get("customer"),
                    "amount": amount, "units": lead.get("units", 0),
                    "unit_cost": UNIT_COST},
    }]


def ops_step(ctx: RoleContext) -> list[dict[str, Any]]:
    if "opsbot" in ctx.state.roles_paused:
        return []
    backlog = sum(int(p.get("units", 0)) for p in ctx.state.pipeline.values())
    inbound = 0  # POs arrive via po_received; pending POs tracked by service in state pipeline
    shortfall = int(backlog * LOW_STOCK_FACTOR) - (ctx.state.inventory + inbound)
    if shortfall <= 0:
        return []
    cost = round(shortfall * UNIT_COST, 2)
    return [{
        "action": "purchase_order",
        "amount": cost,
        "description": f"restock {shortfall} units",
        "payload": {"units": shortfall, "cost": cost, "supplier": "SouthSupply",
                    "receive_day": ctx.day + 1, "due_day": ctx.day + 14},
    }]


def finance_step(ctx: RoleContext) -> list[dict[str, Any]]:
    if "financebot" in ctx.state.roles_paused:
        return []
    intents: list[dict[str, Any]] = []
    # collect every due invoice
    for inv in list(ctx.state.ar.values()):
        if int(inv.get("due_day", 0)) <= ctx.day:
            intents.append({
                "action": "collect", "amount": float(inv["amount"]),
                "description": f"collect {inv['invoice_id']} from {inv.get('customer')}",
                "payload": {"invoice_id": inv["invoice_id"], "amount": float(inv["amount"])},
            })
    # pay due bills unless frozen
    if not ctx.state.spend_frozen:
        for bill in list(ctx.state.ap.values()):
            if int(bill.get("due_day", 0)) <= ctx.day:
                intents.append({
                    "action": "pay", "amount": float(bill["amount"]),
                    "description": f"pay {bill['bill_id']} to {bill.get('supplier')}",
                    "payload": {"bill_id": bill["bill_id"], "amount": float(bill["amount"])},
                })
    # freeze on low runway
    if ctx.kpis["runway_days"] < RUNWAY_FREEZE_DAYS and not ctx.state.spend_frozen:
        intents.append({
            "action": "freeze_spend", "amount": None,
            "description": f"runway {ctx.kpis['runway_days']}d < {RUNWAY_FREEZE_DAYS}d",
            "payload": {"runway_days": ctx.kpis["runway_days"]},
        })
    return intents
```

`core/companycore/domain/scenarios.py`:

```python
"""Seeded world generators. Deterministic: same seed -> same week."""

import random
from typing import Any

CUSTOMERS = ["Acme", "Globex", "Initech", "Umbrella", "Hooli", "Stark"]


def _week(seed: int, crunch_day: int | None) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    days: list[dict[str, Any]] = []
    for d in range(7):
        leads = []
        for i in range(rng.randint(1, 2)):
            units = rng.choice([10, 20, 40])
            leads.append({
                "lead_id": f"L{d}{i}",
                "customer": rng.choice(CUSTOMERS),
                "value": units * 280,
                "units": units,
            })
        churn = []
        if crunch_day is not None and d == crunch_day:
            churn = [{"lead_id": f"L{d}9", "customer": "Acme", "value": 15000, "units": 60,
                      "reason": "churned"}]
            # a big supplier bill lands early
            days.append({"leads": leads, "churn": churn,
                         "early_bill": {"bill_id": f"BX{d}", "supplier": "SouthSupply",
                                        "amount": 9000, "due_day": d}})
            continue
        days.append({"leads": leads, "churn": churn, "early_bill": None})
    return days


def normal_week(seed: int = 7) -> list[dict[str, Any]]:
    return _week(seed, None)


def cash_crunch(seed: int = 7) -> list[dict[str, Any]]:
    return _week(seed, 2)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest tests/test_company_roles.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add core/companycore/application core/companycore/domain/scenarios.py tests/test_company_roles.py
git commit -m "feat(companycore): ports, role policies, seeded scenarios"
```

---

### Task 5: CompanyService — the run-the-week loop with enforcement composition

**Files:**
- Create: `core/companycore/application/services.py`
- Create: `core/companycore/application/demo.py`
- Test: `tests/test_company_service.py`

**Interfaces:**
- Consumes: Tasks 1–4; existing core services (Trust/Decision/Memory). Uses a new DecisionCore domain `company` registered via `register_domain` with actions `["quote","purchase_order","payment","collect","freeze_spend","directive"]`, `cost_threshold=5000.0`, required_evidence `["reason"]`.
- Produces: `CompanyService(events: EventStore, clock: Clock, llm: LLMPort, trust, decision, memory)` with:
  - `seed_demo(scenario: str = "normal") -> dict` — creates keypairs for salesbot/opsbot/financebot/chiefofstaff + a `northwind` issuer; registers agents with TrustService; issues AuthorityGrants (Sales quote ≤5000, Ops purchase_order ≤8000, Finance payment ≤20000); seeds opening state events (cash $50,000 via an opening `invoice_collected` from "seed", inventory 200 via `po_received`, 2 AR, 1 AP); returns `{keys, beats}`.
  - `advance_day() -> dict` — runs one day: world tick from scenario, then sales/ops/finance intents gated through `trust.decide` (allow → apply event; refuse → record + skip; escalate → inbox), then ChiefOfStaff directive via `llm.propose` → `parse_directive` → apply or reject, then KPI fold + `day_ticked`. Returns `{day, kpis, beats, inbox}`.
  - `resolve_inbox(id, resolution) -> dict` — resolves, appends `escalation_resolved`.
  - `state() -> dict`, `kpis() -> dict`, `replay(day) -> dict`, `events() -> list[dict]`, `inbox() -> list[dict]`.
  - `run_cash_crunch() -> dict`, `inject_rogue_sales() -> dict` (sets a rogue flag making sales_step over-discount; drift noted via events).
- Behavior rules: before applying any intent with an amount, call `trust.decide(requester_key=role_key, action=intent_action, amount=amount)`. ALLOW → append the corresponding event(s). REFUSE → append nothing, record a beat. ESCALATE → raise inbox item + append `escalation_raised`. When spend_frozen, `pay`/`purchase_order` intents are skipped with a beat. Rogue sales: quotes at 40% margin → over-scope → TrustCore REFUSE → after ≥3 refusals append `role_paused{salesbot}`.

- [ ] **Step 1: Write the failing test**

```python
from core.companycore.adapters.memory import InMemoryEventStore, ManualClock, ScriptedLLM
from core.companycore.application.services import CompanyService
from core.decisioncore.adapters.memory import InMemoryDecisionStore
from core.decisioncore.application.services import DecisionService
from core.memorycore.adapters.memory import InMemoryMemoryStore, InMemoryTombstoneLog
from core.memorycore.adapters.memory import ManualClock as MemClock
from core.memorycore.application.services import MemoryService
from core.trustcore.adapters.memory import (
    InMemoryAgentRegistry, InMemoryCredentialStore, InMemoryReceiptLog, SystemClock,
)
from core.trustcore.application.services import TrustService
from datetime import UTC, datetime


def _stack():
    trust = TrustService(registry=InMemoryAgentRegistry(), credentials=InMemoryCredentialStore(),
                         receipts=InMemoryReceiptLog(), clock=SystemClock())
    decision = DecisionService(authority=trust, history=trust,
                               decisions=InMemoryDecisionStore(), audit=trust)
    memory = MemoryService(store=InMemoryMemoryStore(), tombstones=InMemoryTombstoneLog(),
                           clock=MemClock(datetime.now(UTC)), trust=trust)
    svc = CompanyService(events=InMemoryEventStore(), clock=ManualClock(),
                         llm=ScriptedLLM(), trust=trust, decision=decision, memory=memory)
    return svc


def test_seed_demo_creates_roles_and_opening_state():
    svc = _stack()
    result = svc.seed_demo("normal")
    assert set(result["keys"]) >= {"salesbot", "opsbot", "financebot", "chiefofstaff"}
    st = svc.state()
    assert st["cash"] == 50000
    assert st["inventory"] == 200


def test_advance_day_moves_numbers():
    svc = _stack()
    svc.seed_demo("normal")
    before = svc.kpis()
    svc.advance_day()
    after = svc.kpis()
    assert after["day"] == before["day"] + 1
    assert after["revenue"] >= before["revenue"]


def test_replay_day_returns_earlier_state():
    svc = _stack()
    svc.seed_demo("normal")
    svc.advance_day(); svc.advance_day()
    day1 = svc.replay(1)
    day2 = svc.replay(2)
    assert day1["cash"] != day2["cash"] or day1["inventory"] != day2["inventory"]


def test_inbox_roundtrip():
    svc = _stack()
    svc.seed_demo("normal")
    svc.advance_day()
    box = svc.inbox()
    if box:
        res = svc.resolve_inbox(box[0]["id"], "approved")
        assert res["resolved"] is True


def test_chief_of_staff_brain_label():
    svc = _stack()
    svc.seed_demo("normal")
    out = svc.advance_day()
    assert out["chief_brain"] in ("llm", "scripted")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_company_service.py -v`
Expected: FAIL (ModuleNotFoundError: core.companycore.adapters)

- [ ] **Step 3: Write minimal implementation**

First register a `company` DecisionCore domain in `core/companycore/application/demo.py` (alongside seed). Create `core/companycore/application/services.py`:

```python
"""CompanyService: the run-the-week loop. Roles propose; cores enforce; the log is truth."""

from datetime import UTC, datetime
from typing import Any

from core.companycore.application.ports import Clock, EventStore, LLMPort
from core.companycore.application.roles import finance_step, ops_step, sales_step, RoleContext
from core.companycore.domain.directives import parse_directive
from core.companycore.domain.events import make_event
from core.companycore.domain.inbox import Inbox
from core.companycore.domain.kpis import kpis as fold_kpis
from core.companycore.domain.ledger import fold_state, replay_day
from core.companycore.domain.scenarios import cash_crunch, normal_week

DAILY_BURN = 1200.0
ROLE_ACTION_SCOPE = {"salesbot": "quote", "opsbot": "purchase_order", "financebot": "payment"}
ROLE_STEP = {"salesbot": sales_step, "opsbot": ops_step, "financebot": finance_step}


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
                    i["amount"] = round(i["amount"] * 3, 2)  # over-scope over-discount
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
            if self._rogue_sales and self._refusal_streak >= 3 and role == "salesbot":
                self._emit("tower", "role_paused", {"role": "salesbot",
                                                    "reason": "over-scope refusal streak"})
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
        self._emit("chiefofstaff", "directive_proposed", {"raw": raw[:300], "brain": brain,
                                                          **directive.as_dict()})
        if directive.action == "none":
            self._emit("chiefofstaff", "directive_rejected", {"rationale": directive.rationale})
            return {"label": f"ChiefOfStaff ({brain}): no binding directive — {directive.rationale}"}, brain
        if directive.action == "freeze_spend":
            self._emit("chiefofstaff", "spend_frozen", {"by": "directive"})
        self._emit("chiefofstaff", "directive_applied", directive.as_dict())
        return {"label": f"ChiefOfStaff ({brain}): {directive.action} — {directive.rationale}"}, brain

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
```

`core/companycore/application/demo.py`:

```python
"""Seed Northwind Components: real signed role authority + opening books."""

from typing import Any, Callable

from core.trustcore.domain.credentials import CredentialType
from core.trustcore.domain.crypto import KeyPair

SCOPES = {
    "salesbot": (["quote"], 5000),
    "opsbot": (["purchase_order"], 8000),
    "financebot": (["payment"], 20000),
    "chiefofstaff": (["directive"], 0),
}


def seed_company(trust: Any, emit_opening: Callable[[str, str, dict], None]) -> dict[str, Any]:
    issuer = KeyPair.generate()
    keys: dict[str, str] = {}
    beats = []
    for role, (actions, max_amount) in SCOPES.items():
        kp = KeyPair.generate()
        trust.register_agent(name=role, public_key=kp.public_key_b64, owner="Northwind")
        scope = {"actions": actions}
        if max_amount:
            scope["max_amount"] = max_amount
        trust.issue_credential(issuer=issuer, subject_key=kp.public_key_b64,
                               type=CredentialType.AUTHORITY_GRANT,
                               claim={"role": role, "actions": actions},
                               scope=scope, ttl_days=30)
        # completion history so decisions ALLOW rather than ESCALATE by default
        trust.issue_credential(issuer=issuer, subject_key=kp.public_key_b64,
                               type=CredentialType.TASK_COMPLETION,
                               claim={"task": f"{role} prior work", "outcome": "completed"},
                               scope={"actions": actions})
        keys[role] = kp.public_key_b64
    beats.append({"label": "four roles enrolled with signed, scoped authority"})

    # opening books: cash 50k, inventory 200, 2 AR, 1 AP
    emit_opening("seed", "invoice_collected", {"invoice_id": "SEED", "amount": 50000})
    emit_opening("seed", "po_received", {"po_id": "SEED-P", "units": 200, "bill_id": "SEED-B",
                                         "cost": 0, "due_day": 0, "supplier": "opening stock"})
    emit_opening("seed", "invoice_issued", {"invoice_id": "AR1", "deal_id": "D-AR1",
                                            "customer": "Acme", "amount": 4200, "due_day": 1,
                                            "units": 10})
    emit_opening("seed", "invoice_issued", {"invoice_id": "AR2", "deal_id": "D-AR2",
                                            "customer": "Globex", "amount": 2600, "due_day": 2,
                                            "units": 6})
    emit_opening("seed", "bill_received", {"bill_id": "AP1", "supplier": "SouthSupply",
                                           "amount": 3000, "due_day": 1})
    beats.append({"label": "opening books: $50k cash, 200 units, 2 invoices, 1 bill"})
    return {"keys": keys, "beats": beats}
```

- [ ] **Step 4: Create the adapters, then run tests**

Create `core/companycore/adapters/__init__.py` (empty) and `core/companycore/adapters/memory.py`:

```python
"""In-memory adapters + the scripted LLM fallback (no network, deterministic)."""

from datetime import UTC, datetime
from typing import Any

from core.companycore.domain.events import CompanyEvent
from core.companycore.domain.log import EventLog


class InMemoryEventStore:
    def __init__(self) -> None:
        self._log = EventLog()

    def append(self, event: CompanyEvent) -> None:
        self._log.append(event)

    def all(self) -> list[CompanyEvent]:
        return self._log.all()

    def tail(self, n: int) -> list[CompanyEvent]:
        return self._log.tail(n)

    def export(self) -> list[dict[str, Any]]:
        return self._log.export()

    def next_seq(self) -> int:
        return self._log.next_seq()


class ManualClock:
    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime.now(UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, **kwargs: Any) -> None:
        from datetime import timedelta
        self._now = self._now + timedelta(**kwargs)


class ScriptedLLM:
    """Deterministic stand-in for the ChiefOfStaff: same snapshot in, same directive out."""

    def propose(self, snapshot: dict[str, Any]) -> tuple[str, str]:
        runway = snapshot.get("kpis", {}).get("runway_days", 99)
        if runway < 21:
            return ('{"action":"freeze_spend","target":"discretionary","amount_cap":null,'
                    f'"rationale":"runway {runway}d below 21d threshold"}}'), "scripted"
        return ('{"action":"none","target":"","amount_cap":null,'
                '"rationale":"company healthy; no intervention"}'), "scripted"
```

Run: `.venv\Scripts\python.exe -m pytest tests/test_company_service.py -v`
Expected: 5 passed (adjust seed numbers if a test asserts an exact value the scenario doesn't produce — fix the TEST to match deterministic behavior, never the reverse).

- [ ] **Step 5: Commit**

```bash
git add core/companycore tests/test_company_service.py
git commit -m "feat(companycore): CompanyService run-the-week loop with enforcement"
```

---

### Task 6: OpenRouter LLM adapter (propose-only, graceful fallback)

**Files:**
- Create: `core/companycore/adapters/llm.py`
- Test: `tests/test_company_llm.py`

**Interfaces:**
- Produces: `OpenRouterChief(*, api_key: str | None, model: str = "meta-llama/llama-3.3-70b-instruct:free", timeout: float = 8.0, fallback: ScriptedLLM)` implementing `LLMPort.propose(snapshot) -> tuple[str, str]`. If no key or any network/HTTP/parse error → delegates to `fallback` and returns brain `"scripted"`. On success returns `(content, "llm")`. Uses `httpx.post("https://openrouter.ai/api/v1/chat/completions", ...)` with `temperature: 0`. Prompt instructs the model to answer with ONLY a JSON directive matching `DIRECTIVE_ACTIONS`.

- [ ] **Step 1: Write the failing test**

```python
from core.companycore.adapters.llm import OpenRouterChief
from core.companycore.adapters.memory import ScriptedLLM


def test_no_key_falls_back_to_scripted():
    chief = OpenRouterChief(api_key=None, fallback=ScriptedLLM())
    text, brain = chief.propose({"kpis": {"runway_days": 10}})
    assert brain == "scripted"
    assert "freeze_spend" in text


def test_http_error_falls_back(monkeypatch):
    import httpx

    def boom(*a, **k):
        raise httpx.ConnectError("no network")

    monkeypatch.setattr(httpx, "post", boom)
    chief = OpenRouterChief(api_key="sk-test", fallback=ScriptedLLM())
    text, brain = chief.propose({"kpis": {"runway_days": 50}})
    assert brain == "scripted"


def test_success_returns_llm_brain(monkeypatch):
    import httpx

    class Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content":
                '{"action":"accelerate_collections","target":"AR","amount_cap":null,"rationale":"tighten cash"}'}}]}

    monkeypatch.setattr(httpx, "post", lambda *a, **k: Resp())
    chief = OpenRouterChief(api_key="sk-test", fallback=ScriptedLLM())
    text, brain = chief.propose({"kpis": {"runway_days": 50}})
    assert brain == "llm"
    assert "accelerate_collections" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_company_llm.py -v`
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Write minimal implementation**

```python
"""OpenRouter ChiefOfStaff. Propose-only: output is parsed by domain.directives
before ANY state change. Any failure degrades to the scripted fallback."""

import os
from typing import Any

import httpx

from core.companycore.adapters.memory import ScriptedLLM

PROMPT = (
    "You are the ChiefOfStaff of a small B2B parts company. Given the KPI snapshot, "
    "reply with ONLY one JSON object: {\"action\": one of freeze_spend|"
    "accelerate_collections|accept_discount|defer_po|none, \"target\": string, "
    "\"amount_cap\": number|null, \"rationale\": string}. No prose, only JSON."
)


class OpenRouterChief:
    def __init__(self, *, api_key: str | None = None,
                 model: str = "meta-llama/llama-3.3-70b-instruct:free",
                 timeout: float = 8.0, fallback: ScriptedLLM | None = None) -> None:
        self._key = api_key or os.environ.get("OPENROUTER_API_KEY")
        self._model = model
        self._timeout = timeout
        self._fallback = fallback or ScriptedLLM()

    def propose(self, snapshot: dict[str, Any]) -> tuple[str, str]:
        if not self._key:
            return self._fallback.propose(snapshot)
        try:
            resp = httpx.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {self._key}"},
                json={"model": self._model, "temperature": 0,
                      "messages": [{"role": "system", "content": PROMPT},
                                   {"role": "user", "content": str(snapshot)[:4000]}]},
                timeout=self._timeout,
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            return content, "llm"
        except Exception:
            return self._fallback.propose(snapshot)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest tests/test_company_llm.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add core/companycore/adapters/llm.py tests/test_company_llm.py
git commit -m "feat(companycore): OpenRouter chief adapter with scripted fallback"
```

---

### Task 7: Scenarios e2e — self-correction (cash crunch) + failure test (rogue sales)

**Files:**
- Test: `tests/test_company_scenarios.py`
- Modify: `core/companycore/application/services.py` (only if a behavior gap surfaces)

**Interfaces:**
- Consumes: Task 5 service.

- [ ] **Step 1: Write the failing test**

```python
from datetime import UTC, datetime

from core.companycore.adapters.memory import InMemoryEventStore, ManualClock, ScriptedLLM
from core.companycore.application.services import CompanyService
from core.decisioncore.adapters.memory import InMemoryDecisionStore
from core.decisioncore.application.services import DecisionService
from core.memorycore.adapters.memory import InMemoryMemoryStore, InMemoryTombstoneLog
from core.memorycore.adapters.memory import ManualClock as MemClock
from core.memorycore.application.services import MemoryService
from core.trustcore.adapters.memory import (
    InMemoryAgentRegistry, InMemoryCredentialStore, InMemoryReceiptLog, SystemClock,
)
from core.trustcore.application.services import TrustService


def _svc():
    trust = TrustService(registry=InMemoryAgentRegistry(), credentials=InMemoryCredentialStore(),
                         receipts=InMemoryReceiptLog(), clock=SystemClock())
    decision = DecisionService(authority=trust, history=trust,
                               decisions=InMemoryDecisionStore(), audit=trust)
    memory = MemoryService(store=InMemoryMemoryStore(), tombstones=InMemoryTombstoneLog(),
                           clock=MemClock(datetime.now(UTC)), trust=trust)
    return CompanyService(events=InMemoryEventStore(), clock=ManualClock(),
                          llm=ScriptedLLM(), trust=trust, decision=decision, memory=memory)


def test_cash_crunch_self_corrects_without_human():
    svc = _svc()
    svc.seed_demo("cash_crunch")
    svc.advance_day(); svc.advance_day()  # day 2: churn + early bill
    crunch = svc.kpis()
    svc.advance_day(); svc.advance_day()
    after = svc.kpis()
    # the company reacted: spend froze at some point, and no inbox item was REQUIRED
    kinds = [e["kind"] for e in svc.events()]
    assert "spend_frozen" in kinds
    assert after["runway_days"] >= 0  # books stayed consistent


def test_rogue_sales_is_contained():
    svc = _svc()
    svc.seed_demo("normal")
    svc.inject_rogue_sales()
    for _ in range(4):
        svc.advance_day()
    kinds = [e["kind"] for e in svc.events()]
    assert "role_paused" in kinds  # sales auto-paused after refusal streak
    st = svc.state()
    assert "salesbot" in st["roles_paused"]


def test_over_scope_action_never_applies():
    svc = _svc()
    svc.seed_demo("normal")
    svc.inject_rogue_sales()
    svc.advance_day()
    # no deal_won at the rogue inflated amount: every won deal is within scope
    for e in svc.events():
        if e["kind"] == "deal_won":
            assert e["payload"]["amount"] <= 5000 * 3  # quotes were gated by trust
```

- [ ] **Step 2: Run test, fix behavior gaps in the service (not the test's intent)**

Run: `.venv\Scripts\python.exe -m pytest tests/test_company_scenarios.py -v`
Expected: FAIL on first run (rogue/refusal-streak logic may need tuning); adjust `services.py` `_gate_and_apply`/`_run_role` until the containment behavior is real, then green.

- [ ] **Step 3: Commit**

```bash
git add core/companycore tests/test_company_scenarios.py
git commit -m "test(companycore): cash-crunch self-correction + rogue-sales containment"
```

---

### Task 8: API surface

**Files:**
- Modify: `api/main.py` (add company router section + composition in `create_app`)
- Modify: `core/companycore/application/demo.py` (register `company` DecisionCore domain if used)
- Test: `tests/test_company_api.py`

**Interfaces:**
- Consumes: Task 5/6 services; `create_app` composition root pattern (existing cores).
- Produces endpoints (exact paths):
  `POST /api/company/demo`, `POST /api/company/advance`, `GET /api/company/state`, `GET /api/company/kpis`, `GET /api/company/inbox`, `POST /api/company/inbox/{id}/resolve` (body `{"resolution": str}`), `GET /api/company/replay?day=N`, `GET /api/company/events`, `POST /api/company/scenario/cash-crunch`, `POST /api/company/scenario/rogue-sales`.

In `create_app`, after MemoryCore wiring:

```python
from core.companycore.adapters.llm import OpenRouterChief
from core.companycore.adapters.memory import InMemoryEventStore, ManualClock, ScriptedLLM
from core.companycore.application.services import CompanyService

company_svc = CompanyService(
    events=InMemoryEventStore(), clock=ManualClock(),
    llm=OpenRouterChief(fallback=ScriptedLLM()),
    trust=svc, decision=decision_svc, memory=memory_svc,
)
app.state.company_service = company_svc
```

- [ ] **Step 1: Write the failing test**

```python
from fastapi.testclient import TestClient

from api.main import create_app


def _client():
    return TestClient(create_app())


def test_demo_seed_and_state():
    c = _client()
    r = c.post("/api/company/demo", json={"scenario": "normal"})
    assert r.status_code == 200
    st = c.get("/api/company/state").json()
    assert st["cash"] == 50000


def test_advance_moves_kpis():
    c = _client()
    c.post("/api/company/demo", json={"scenario": "normal"})
    k0 = c.get("/api/company/kpis").json()
    out = c.post("/api/company/advance").json()
    k1 = c.get("/api/company/kpis").json()
    assert out["day"] == k0["day"] + 1
    assert k1["revenue"] >= k0["revenue"]


def test_replay_and_events():
    c = _client()
    c.post("/api/company/demo", json={"scenario": "normal"})
    c.post("/api/company/advance"); c.post("/api/company/advance")
    r = c.get("/api/company/replay?day=1")
    assert r.status_code == 200
    ev = c.get("/api/company/events").json()
    assert isinstance(ev["events"], list) and len(ev["events"]) > 0


def test_inbox_resolve_validation():
    c = _client()
    c.post("/api/company/demo", json={"scenario": "normal"})
    r = c.post("/api/company/inbox/nope/resolve", json={"resolution": "x"})
    assert r.status_code == 404


def test_scenario_levers():
    c = _client()
    c.post("/api/company/demo", json={"scenario": "normal"})
    assert c.post("/api/company/scenario/cash-crunch").status_code == 200
    assert c.post("/api/company/scenario/rogue-sales").status_code == 200


def test_advance_before_seed_409():
    c = _client()
    assert c.post("/api/company/advance").status_code == 409
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_company_api.py -v`
Expected: FAIL (404s — routes not mounted)

- [ ] **Step 3: Wire the routes in `api/main.py`**

Add the composition (above) and the route handlers, mapping `ValueError("run seed_demo first")` → 409, `ValueError("unknown escalation")` → 404, double-resolve → 409. Follow the existing route style (Pydantic bodies, HTTPException).

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest tests/test_company_api.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add api/main.py tests/test_company_api.py
git commit -m "feat(companycore): /api/company/* surface"
```

---

### Task 9: UI tab "C6 · Company"

**Files:**
- Create: `ui/src/company/Company.jsx`
- Modify: `ui/src/App.jsx` (import + tab entry `['company', 'C6 · Company']` + render `{tab === 'company' && <Company />}`)
- Build: `ui/dist` via `npm run build` (committed)

**Interfaces:**
- Consumes: the Task 8 endpoints.
- Produces: a tab with (a) KPI ticker bar (revenue/cash/runway/backlog/churn), (b) org view of the 4 roles with status, (c) readable event timeline, (d) human inbox cards with a resolve box, (e) a day-replay scrubber (input range 0..current day re-folds via `/replay`), (f) "Cash crunch" and "Rogue sales" buttons, (g) "Run a day" button, (h) demo seed button. Labels which brain answered (`chief_brain`). Uses the existing design system classes (`card`, `badge`, `mono`, `serif`, `fade-up`, `pressable`, CSS vars).

- [ ] **Step 1: Write the component**

Build `Company.jsx` against the endpoints; poll `/state`, `/kpis`, `/inbox`, `/events` every 3s like the other tabs; wire the buttons.

- [ ] **Step 2: Wire the tab in App.jsx and build**

Run: `cd ui; npm run build`
Expected: `✓ built` — new `dist/assets/index-*.js` committed.

- [ ] **Step 3: Smoke-check the built UI renders the tab**

Run: `node -e "const fs=require('fs');const s=fs.readFileSync('ui/src/App.jsx','utf8');if(!s.includes('C6')){console.log('C6 tab missing');process.exit(1)}if(!fs.existsSync('ui/dist/index.html')){console.log('dist not built');process.exit(1)}console.log('company UI present, dist built')"`
Expected: `company UI present, dist built`

- [ ] **Step 4: Commit**

```bash
git add ui/src/company ui/src/App.jsx ui/dist
git commit -m "feat(company): C6 UI tab — KPIs, org view, inbox, replay scrubber, scenarios"
```

---

### Task 10: Architecture contracts + security sweep + gates

**Files:**
- Modify: `pyproject.toml` (add companycore packages + 5 import-linter contracts)
- Modify: `GATES.md` (C6 section)

**Interfaces:**
- Produces: import-linter contracts mirroring the other cores: (1) domain pure (no fastapi/sqlalchemy/redis/requests/httpx/uvicorn), (2) application free of adapters+fastapi+sqlalchemy, (3) layers adapters>application>domain, (4) cross-core via public surfaces only (forbid `core.trustcore.adapters`, `core.decisioncore.adapters`, `core.simcore.adapters`, `core.adaptivecore.adapters`, `core.towercore.adapters`, `core.memorycore.adapters`, `api`), (5) LLM only in adapters (forbid `openai`, `anthropic`, `langchain`, `litellm` in domain+application; `httpx` allowed only in `adapters`).

- [ ] **Step 1: Add packages + contracts to pyproject.toml**

Add `core.companycore`, `core.companycore.domain`, `core.companycore.application`, `core.companycore.adapters` to `[tool.setuptools] packages`. Append the five contracts.

- [ ] **Step 2: Run architecture + lint + full suite**

Run: `.venv\Scripts\lint-imports.exe --config pyproject.toml`; `.venv\Scripts\python.exe -m ruff check .`; `.venv\Scripts\python.exe -m pytest`
Expected: `0 broken`, `All checks passed`, all tests green.

- [ ] **Step 3: Security sweep + append GATES.md C6 section**

Run a node sweep asserting: no `eval(`/`exec(` in `core/companycore`, no LLM imports in domain/application, enforcement receipts keep `llm_called=False`. Append the C6 gates (CHECK/EXPECT/EVIDENCE) to `GATES.md` with real outputs.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml GATES.md
git commit -m "chore(companycore): architecture contracts, security sweep, C6 gates"
```

---

### Task 11: Docs + delivery (architecture, thesis ≤300 words, 90s script, README, deploy)

**Files:**
- Create: `docs/architecture-c6.md`, `docs/thesis-c6.md`, `demo/script-c6.md`
- Modify: `README.md` (C6 section + quick drive)
- Deploy: push to master → Render auto-deploy → verify `/health` + `/api/company/demo` live

**Interfaces:**
- Produces: thesis ≤300 words (verified by the same tokenizer the gates use), architecture snapshot (shared state, agent roles, escalation rules), 90-second runbook covering the three beats (normal day + human inbox moment, cash-crunch self-correction, rogue-sales failure test), README C6 section with honest limits.

- [ ] **Step 1: Write the three docs + README section**

- [ ] **Step 2: Word-count + presence check**

Run: `node -e "const fs=require('fs');const files=['docs/architecture-c6.md','docs/thesis-c6.md','demo/script-c6.md'];const missing=files.filter(f=>!fs.existsSync(f));if(missing.length){console.log('MISSING: '+missing);process.exit(1)}const t=fs.readFileSync('docs/thesis-c6.md','utf8').replace(/^#.*$/m,'').replace(/[#*\`>|]/g,'').split(/\s+/).filter(Boolean).length;if(t>320){console.log('thesis too long: '+t);process.exit(1)}console.log('c6 docs complete, thesis '+t+' words')"`
Expected: `c6 docs complete, thesis <N> words`

- [ ] **Step 3: Push and verify live**

Run: `git push origin master`, then poll `https://builder-league-trust.onrender.com/health` until `{"status":"ok"}`, then exercise `/api/company/demo` + `/api/company/advance` live.

- [ ] **Step 4: Commit**

```bash
git add docs README.md
git commit -m "docs(c6): architecture, thesis, 90s script, README"
```

---

## Self-Review notes

- **Spec coverage:** every deliverable row in the spec maps to a task (roles→T4, loop+inbox→T5/T3, KPIs+replay→T2, self-correction→T7, failure test→T7, LLM→T6, API→T8, UI→T9, contracts→T10, docs/deploy→T11).
- **Placeholders:** none — every code step carries full code; Tasks 8–9 name exact endpoints and wiring because implementation follows existing file patterns too long to inline (route bodies mirror the five existing routers; the component mirrors existing tabs).
- **Type consistency:** `CompanyEvent`, `EventStore`, `LLMPort.propose -> tuple[str,str]`, `CompanyService` method names (`seed_demo/advance_day/resolve_inbox/state/kpis/replay/events/inbox/run_cash_crunch/inject_rogue_sales`) are used identically across tasks 4–8.
