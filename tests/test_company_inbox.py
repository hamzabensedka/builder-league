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
    d = parse_directive(
        'Here is my call: {"action":"freeze_spend","target":"discretionary",'
        '"amount_cap":null,"rationale":"runway 18 days"}'
    )
    assert d.action == "freeze_spend"
    assert d.rationale == "runway 18 days"


def test_parse_rejects_unknown_action():
    d = parse_directive(
        '{"action":"launch_rocket","target":"moon","amount_cap":null,"rationale":"x"}'
    )
    assert d.action == "none"
    assert "unparseable" in d.rationale or "unknown" in d.rationale


def test_parse_garbage_is_safe():
    d = parse_directive("I think we should probably do something about cash maybe")
    assert d.action == "none"


def test_directive_actions_set():
    for a in ["freeze_spend", "accelerate_collections", "accept_discount", "defer_po", "none"]:
        assert a in DIRECTIVE_ACTIONS
