"""TowerCore replay: last N events folded into human-readable trace lines."""

from core.towercore.domain.events import make_event
from core.towercore.domain.replay import replay
from core.towercore.domain.stream import EventStream


def emit(stream, agent, kind, payload=None, run="r1"):
    seq = stream.next_seq(agent)
    stream.append(make_event(agent_id=agent, run_id=run, seq=seq, ts="t",
                             kind=kind, payload=payload or {}))


class TestReplay:
    def test_empty_agent_replays_empty(self):
        s = EventStream()
        assert replay(s, "a1", 10) == []

    def test_trace_lines_narrate_each_kind(self):
        s = EventStream()
        emit(s, "a1", "step_started", {"step": "check_stock"})
        emit(s, "a1", "decision_requested", {"domain": "refund", "action": "issue_refund"})
        emit(s, "a1", "action_executed", {"action": "purchase"})
        emit(s, "a1", "action_denied", {"action": "deploy", "reason": "no authority"})
        emit(s, "a1", "drift_flagged", {"kind": "denial_burst"})
        emit(s, "a1", "approval_requested", {"action": "issue_refund", "amount": 2400})
        emit(s, "a1", "approval_resolved", {"status": "approved", "operator": "ops"})
        emit(s, "a1", "intervention_applied", {"intervention": "kill", "operator": "ops"})
        trace = replay(s, "a1", 20)
        assert len(trace) == 8
        assert all("seq" in line and "text" in line for line in trace)
        assert "check_stock" in trace[0]["text"]
        assert "no authority" in trace[3]["text"]
        assert "kill" in trace[7]["text"].lower()

    def test_tail_limits_to_last_n(self):
        s = EventStream()
        for i in range(10):
            emit(s, "a1", "action_executed", {"action": f"a{i}"})
        trace = replay(s, "a1", 3)
        assert [line["payload"]["action"] for line in trace] == ["a7", "a8", "a9"]

    def test_trace_includes_seq_for_audit_alignment(self):
        s = EventStream()
        emit(s, "a1", "step_started", {"step": "x"})
        emit(s, "a1", "action_executed", {"action": "y"})
        trace = replay(s, "a1", 5)
        assert [line["seq"] for line in trace] == [1, 2]

    def test_only_target_agent(self):
        s = EventStream()
        emit(s, "a1", "action_executed", {"action": "mine"})
        emit(s, "a2", "action_executed", {"action": "theirs"})
        trace = replay(s, "a1", 10)
        assert len(trace) == 1
        assert trace[0]["payload"]["action"] == "mine"
