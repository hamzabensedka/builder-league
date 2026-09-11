"""TowerCore cost meter: deterministic token estimates per agent per task."""

from core.towercore.domain.cost import (
    ACTION_TOKEN_ESTIMATES,
    CostMeter,
    estimate_tokens,
)


class TestEstimates:
    def test_known_action_types_have_estimates(self):
        for action in ["decide", "simulate", "execute", "replan"]:
            est = estimate_tokens(action)
            assert est["input_tokens"] > 0
            assert est["output_tokens"] > 0

    def test_unknown_action_uses_default(self):
        est = estimate_tokens("some_future_action")
        assert est == ACTION_TOKEN_ESTIMATES["default"]

    def test_estimates_are_deterministic(self):
        assert estimate_tokens("decide") == estimate_tokens("decide")


class TestMeter:
    def test_record_and_totals(self):
        m = CostMeter(input_price_per_1k=0.003, output_price_per_1k=0.015)
        m.record(agent_id="a1", task="task-1", action_type="decide")
        m.record(agent_id="a1", task="task-1", action_type="execute")
        snap = m.for_agent("a1")
        assert snap["tasks"]["task-1"]["calls"] == 2
        assert snap["total_tokens"] > 0
        assert snap["total_cost_usd"] > 0

    def test_per_task_breakdown(self):
        m = CostMeter(input_price_per_1k=0.003, output_price_per_1k=0.015)
        m.record(agent_id="a1", task="t1", action_type="decide")
        m.record(agent_id="a1", task="t2", action_type="simulate")
        snap = m.for_agent("a1")
        assert set(snap["tasks"]) == {"t1", "t2"}
        assert snap["tasks"]["t1"]["calls"] == 1
        assert snap["tasks"]["t2"]["calls"] == 1

    def test_agents_isolated(self):
        m = CostMeter(input_price_per_1k=0.003, output_price_per_1k=0.015)
        m.record(agent_id="a1", task="t1", action_type="decide")
        assert m.for_agent("a2")["total_tokens"] == 0

    def test_cost_math_is_correct(self):
        m = CostMeter(input_price_per_1k=0.003, output_price_per_1k=0.015)
        est = estimate_tokens("decide")
        m.record(agent_id="a1", task="t", action_type="decide")
        expected = (est["input_tokens"] / 1000 * 0.003
                    + est["output_tokens"] / 1000 * 0.015)
        assert abs(m.for_agent("a1")["total_cost_usd"] - expected) < 1e-9

    def test_labeled_as_metered_estimate(self):
        m = CostMeter(input_price_per_1k=0.003, output_price_per_1k=0.015)
        m.record(agent_id="a1", task="t", action_type="decide")
        assert m.for_agent("a1")["basis"] == "metered_estimate"

    def test_fleet_snapshot(self):
        m = CostMeter(input_price_per_1k=0.003, output_price_per_1k=0.015)
        m.record(agent_id="a1", task="t", action_type="decide")
        m.record(agent_id="a2", task="t", action_type="execute")
        snap = m.fleet_snapshot()
        assert set(snap) == {"a1", "a2"}
