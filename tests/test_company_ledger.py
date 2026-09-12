from core.companycore.domain.events import make_event
from core.companycore.domain.kpis import kpis
from core.companycore.domain.ledger import fold_state, replay_day


def _ev(seq, kind, payload, day=0, actor="salesbot"):
    return make_event(day=day, seq=seq, actor=actor, kind=kind, payload=payload)


def test_fold_invoice_collect_and_bill_pay():
    events = [
        _ev(0, "lead_arrived",
            {"lead_id": "L1", "customer": "Acme", "value": 4200, "units": 10}),
        _ev(1, "quote_sent", {"lead_id": "L1", "amount": 4200}),
        _ev(2, "deal_won",
            {"lead_id": "L1", "deal_id": "D1", "amount": 4200, "units": 10, "unit_cost": 200}),
        _ev(3, "invoice_issued",
            {"invoice_id": "I1", "deal_id": "D1", "customer": "Acme",
             "amount": 4200, "due_day": 2}),
        _ev(4, "invoice_collected", {"invoice_id": "I1", "amount": 4200},
            day=2, actor="financebot"),
        _ev(5, "bill_received",
            {"bill_id": "B1", "supplier": "SouthSupply", "amount": 2000, "due_day": 1},
            actor="opsbot"),
        _ev(6, "bill_paid", {"bill_id": "B1", "amount": 2000}, day=1, actor="financebot"),
    ]
    s = fold_state(events)
    assert s.cash == 4200 - 2000
    assert "I1" not in s.ar and "B1" not in s.ap
    assert "L1" not in s.pipeline


def test_inventory_moves_on_deal_and_receipt():
    events = [
        _ev(0, "po_received",
            {"po_id": "P1", "units": 50, "bill_id": "B1", "cost": 5000, "due_day": 1},
            actor="opsbot"),
        _ev(1, "deal_won",
            {"lead_id": "L1", "deal_id": "D1", "amount": 4200, "units": 10, "unit_cost": 200}),
    ]
    s = fold_state(events)
    assert s.inventory == 40


def test_replay_day_cutoff():
    events = [
        _ev(0, "invoice_collected", {"invoice_id": "I1", "amount": 1000},
            day=0, actor="financebot"),
        _ev(1, "invoice_collected", {"invoice_id": "I2", "amount": 2000},
            day=3, actor="financebot"),
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
        _ev(0, "invoice_issued",
            {"invoice_id": "I1", "deal_id": "D1", "customer": "Acme",
             "amount": 4200, "due_day": 2}),
        _ev(1, "deal_won",
            {"lead_id": "L1", "deal_id": "D1", "amount": 4200, "units": 10, "unit_cost": 200}),
        _ev(2, "deal_lost", {"lead_id": "L2", "reason": "price"}),
        _ev(3, "invoice_collected", {"invoice_id": "I1", "amount": 4200}, actor="financebot"),
        _ev(4, "bill_paid", {"bill_id": "B1", "amount": 2000}, actor="financebot"),
    ]
    k = kpis(events, current_day=1, daily_burn=1200.0)
    assert k["revenue"] == 4200
    assert k["cash"] == 2200
    assert 0 < k["churn"] <= 1
    assert k["runway_days"] > 0
