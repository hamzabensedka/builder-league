"""TowerCore registry: fleet state folded from the event stream + gate."""

from core.towercore.domain.events import make_event
from core.towercore.domain.gate import InterventionGate
from core.towercore.domain.registry import fleet_view
from core.towercore.domain.stream import EventStream


def emit(stream, agent, kind, payload=None, run="r1"):
    seq = stream.next_seq(agent)
    stream.append(make_event(agent_id=agent, run_id=run, seq=seq, ts="t",
                             kind=kind, payload=payload or {}))


class TestFleetView:
    def test_agent_with_step_is_running(self):
        s, g = EventStream(), InterventionGate()
        emit(s, "a1", "step_started", {"step": "check_stock"})
        view = fleet_view(s, g, budgets={"a1": 1.0})
        assert view["a1"]["status"] == "running"

    def test_last_action_is_latest_executed(self):
        s, g = EventStream(), InterventionGate()
        emit(s, "a1", "action_executed", {"action": "purchase"})
        emit(s, "a1", "action_executed", {"action": "verify"})
        assert fleet_view(s, g, budgets={"a1": 1.0})["a1"]["last_action"] == "verify"

    def test_last_action_none_before_any_execution(self):
        s, g = EventStream(), InterventionGate()
        emit(s, "a1", "step_started")
        assert fleet_view(s, g, budgets={"a1": 1.0})["a1"]["last_action"] is None

    def test_gate_state_overrides(self):
        s, g = EventStream(), InterventionGate()
        emit(s, "a1", "step_started")
        g.pause("a1")
        assert fleet_view(s, g, budgets={"a1": 1.0})["a1"]["status"] == "paused"
        g.kill("a1")
        assert fleet_view(s, g, budgets={"a1": 1.0})["a1"]["status"] == "killed"

    def test_open_blockers_listed(self):
        s, g = EventStream(), InterventionGate()
        emit(s, "a1", "blocker_raised", {"blocker": "supplier offline"})
        view = fleet_view(s, g, budgets={"a1": 1.0})
        assert view["a1"]["blockers"] == ["supplier offline"]
        assert view["a1"]["status"] == "blocked"

    def test_drift_flags_surfaced(self):
        s, g = EventStream(), InterventionGate()
        for _ in range(3):
            emit(s, "a1", "action_denied", {"action": "deploy"})
        view = fleet_view(s, g, budgets={"a1": 1.0})
        assert view["a1"]["drift"]
        assert view["a1"]["drift"][0]["kind"] == "denial_burst"

    def test_cost_totals_summed_from_stream(self):
        s, g = EventStream(), InterventionGate()
        emit(s, "a1", "cost_recorded", {"task": "t1", "cost_usd": 0.010, "tokens": 100})
        emit(s, "a1", "cost_recorded", {"task": "t2", "cost_usd": 0.020, "tokens": 200})
        view = fleet_view(s, g, budgets={"a1": 1.0})
        assert abs(view["a1"]["cost_usd"] - 0.030) < 1e-9
        assert view["a1"]["tokens"] == 300
        assert view["a1"]["cost_basis"] == "metered_estimate"

    def test_status_priority_killed_over_blocked(self):
        s, g = EventStream(), InterventionGate()
        emit(s, "a1", "blocker_raised", {"blocker": "x"})
        g.kill("a1")
        assert fleet_view(s, g, budgets={"a1": 1.0})["a1"]["status"] == "killed"

    def test_recent_events_tail_included(self):
        s, g = EventStream(), InterventionGate()
        for i in range(6):
            emit(s, "a1", "action_executed", {"action": f"step{i}"})
        view = fleet_view(s, g, budgets={"a1": 1.0}, recent_n=3)
        kinds = [e["payload"]["action"] for e in view["a1"]["recent"]]
        assert kinds == ["step3", "step4", "step5"]
