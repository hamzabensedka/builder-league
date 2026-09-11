"""TowerCore anomaly detection: deterministic drift rules over the event stream."""

from core.towercore.domain.anomaly import (
    DENIAL_BURST_THRESHOLD,
    DENIAL_BURST_WINDOW,
    detect_drift,
)
from core.towercore.domain.events import make_event
from core.towercore.domain.stream import EventStream


def denied(stream, agent, run="r1"):
    seq = stream.next_seq(agent)
    stream.append(make_event(agent_id=agent, run_id=run, seq=seq, ts="t",
                             kind="action_denied", payload={"action": "deploy"}))


def ok(stream, agent, run="r1", kind="action_executed"):
    seq = stream.next_seq(agent)
    stream.append(make_event(agent_id=agent, run_id=run, seq=seq, ts="t",
                             kind=kind, payload={"action": "deploy"}))


class TestDenialBurst:
    def test_no_denials_no_flag(self):
        s = EventStream()
        ok(s, "a1"), ok(s, "a1")
        assert detect_drift(s, "a1", budget_usd=1.0) == []

    def test_burst_at_threshold_flags(self):
        s = EventStream()
        for _ in range(DENIAL_BURST_THRESHOLD):
            denied(s, "a1")
        flags = detect_drift(s, "a1", budget_usd=1.0)
        assert any(f.kind == "denial_burst" for f in flags)

    def test_denials_spread_out_do_not_flag(self):
        s = EventStream()
        # interleave denials with successes so the window never fills
        for _ in range(DENIAL_BURST_THRESHOLD):
            denied(s, "a1")
            for _ in range(DENIAL_BURST_WINDOW):
                ok(s, "a1")
        flags = detect_drift(s, "a1", budget_usd=1.0)
        assert not any(f.kind == "denial_burst" for f in flags)

    def test_other_agents_denials_dont_count(self):
        s = EventStream()
        for _ in range(DENIAL_BURST_THRESHOLD + 1):
            denied(s, "a2")
        assert detect_drift(s, "a1", budget_usd=1.0) == []

    def test_flag_carries_evidence(self):
        s = EventStream()
        for _ in range(DENIAL_BURST_THRESHOLD):
            denied(s, "a1")
        flag = next(f for f in detect_drift(s, "a1", budget_usd=1.0)
                    if f.kind == "denial_burst")
        assert flag.detail["denials"] == DENIAL_BURST_THRESHOLD
        assert flag.detail["window"] == DENIAL_BURST_WINDOW


class TestCostRunaway:
    def test_cost_over_budget_flags(self):
        s = EventStream()
        seq = s.next_seq("a1")
        s.append(make_event(agent_id="a1", run_id="r1", seq=seq, ts="t",
                            kind="cost_recorded",
                            payload={"task": "t1", "cost_usd": 2.50}))
        flags = detect_drift(s, "a1", budget_usd=1.0)
        assert any(f.kind == "cost_runaway" for f in flags)

    def test_cost_under_budget_clean(self):
        s = EventStream()
        seq = s.next_seq("a1")
        s.append(make_event(agent_id="a1", run_id="r1", seq=seq, ts="t",
                            kind="cost_recorded",
                            payload={"task": "t1", "cost_usd": 0.40}))
        assert detect_drift(s, "a1", budget_usd=1.0) == []

    def test_cost_accumulates_across_events(self):
        s = EventStream()
        for _ in range(3):
            seq = s.next_seq("a1")
            s.append(make_event(agent_id="a1", run_id="r1", seq=seq, ts="t",
                                kind="cost_recorded",
                                payload={"task": "t", "cost_usd": 0.40}))
        assert any(f.kind == "cost_runaway" for f in detect_drift(s, "a1", budget_usd=1.0))


class TestOscillation:
    def test_flip_flop_flags(self):
        s = EventStream()
        for action in ["deploy_v11", "rollback_v11", "deploy_v11", "rollback_v11"]:
            seq = s.next_seq("a1")
            s.append(make_event(agent_id="a1", run_id="r1", seq=seq, ts="t",
                                kind="action_executed", payload={"action": action}))
        flags = detect_drift(s, "a1", budget_usd=10.0)
        assert any(f.kind == "oscillation" for f in flags)

    def test_steady_progress_clean(self):
        s = EventStream()
        for action in ["check_stock", "size_order", "purchase", "verify"]:
            seq = s.next_seq("a1")
            s.append(make_event(agent_id="a1", run_id="r1", seq=seq, ts="t",
                                kind="action_executed", payload={"action": action}))
        assert detect_drift(s, "a1", budget_usd=10.0) == []


class TestFlagShape:
    def test_flag_as_dict(self):
        s = EventStream()
        for _ in range(DENIAL_BURST_THRESHOLD):
            denied(s, "a1")
        flag = detect_drift(s, "a1", budget_usd=1.0)[0]
        d = flag.as_dict()
        assert d["agent_id"] == "a1"
        assert d["kind"] == "denial_burst"
        assert "summary" in d
