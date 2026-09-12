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
