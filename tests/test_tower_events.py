"""TowerCore events: typed agent events, fail-closed validation, canonical form."""

import pytest

from core.towercore.domain.events import (
    EVENT_KINDS,
    AgentEvent,
    make_event,
)


class TestEventKinds:
    def test_all_required_kinds_exist(self):
        required = {
            "step_started",
            "decision_requested",
            "action_executed",
            "action_denied",
            "blocker_raised",
            "drift_flagged",
            "cost_recorded",
            "approval_requested",
            "approval_resolved",
            "intervention_applied",
        }
        assert required <= set(EVENT_KINDS)


class TestMakeEvent:
    def test_builds_event_with_seq_and_payload(self):
        ev = make_event(
            agent_id="a1", run_id="r1", seq=1, ts="2026-09-11T10:00:00+00:00",
            kind="step_started", payload={"step": "check_stock"},
        )
        assert isinstance(ev, AgentEvent)
        assert ev.agent_id == "a1"
        assert ev.kind == "step_started"
        assert ev.seq == 1

    def test_unknown_kind_rejected(self):
        with pytest.raises(ValueError, match="unknown event kind"):
            make_event(
                agent_id="a1", run_id="r1", seq=1, ts="t", kind="teleported", payload={}
            )

    def test_empty_agent_or_run_rejected(self):
        with pytest.raises(ValueError):
            make_event(agent_id="", run_id="r1", seq=1, ts="t", kind="step_started", payload={})
        with pytest.raises(ValueError):
            make_event(agent_id="a1", run_id="", seq=1, ts="t", kind="step_started", payload={})

    def test_negative_seq_rejected(self):
        with pytest.raises(ValueError):
            make_event(agent_id="a1", run_id="r1", seq=0, ts="t", kind="step_started", payload={})

    def test_payload_must_be_dict(self):
        with pytest.raises(ValueError):
            make_event(
                agent_id="a1", run_id="r1", seq=1, ts="t", kind="step_started",
                payload="not-a-dict",
            )


class TestCanonicalForm:
    def test_as_dict_roundtrip_shape(self):
        ev = make_event(
            agent_id="a1", run_id="r1", seq=3, ts="2026-09-11T10:00:00+00:00",
            kind="action_denied", payload={"action": "deploy", "reason": "no authority"},
        )
        d = ev.as_dict()
        assert d == {
            "agent_id": "a1",
            "run_id": "r1",
            "seq": 3,
            "ts": "2026-09-11T10:00:00+00:00",
            "kind": "action_denied",
            "payload": {"action": "deploy", "reason": "no authority"},
        }

    def test_event_is_immutable(self):
        ev = make_event(agent_id="a1", run_id="r1", seq=1, ts="t", kind="step_started", payload={})
        with pytest.raises(AttributeError):
            ev.kind = "action_executed"  # type: ignore[misc]
