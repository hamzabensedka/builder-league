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
