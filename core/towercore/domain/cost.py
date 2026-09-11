"""Cost meter — deterministic simulated token accounting per agent per task.

Honest by construction: fixed input/output estimates per action type, priced
at configurable rates, and ALWAYS labeled "metered_estimate" — never presented
as real provider billing. Deterministic: same call sequence → same totals.
"""

from typing import Any

# Fixed token estimates per action type (input, output). These stand in for
# real provider metering; the point is per-agent/per-task accountability with
# a stable, auditable basis.
ACTION_TOKEN_ESTIMATES: dict[str, dict[str, int]] = {
    "decide": {"input_tokens": 800, "output_tokens": 200},
    "simulate": {"input_tokens": 1200, "output_tokens": 350},
    "execute": {"input_tokens": 600, "output_tokens": 150},
    "replan": {"input_tokens": 1500, "output_tokens": 500},
    "default": {"input_tokens": 400, "output_tokens": 100},
}


def estimate_tokens(action_type: str) -> dict[str, int]:
    return dict(ACTION_TOKEN_ESTIMATES.get(action_type, ACTION_TOKEN_ESTIMATES["default"]))


class CostMeter:
    def __init__(self, *, input_price_per_1k: float, output_price_per_1k: float) -> None:
        self._in_price = input_price_per_1k
        self._out_price = output_price_per_1k
        # agent_id -> task -> {calls, input_tokens, output_tokens, cost_usd}
        self._ledger: dict[str, dict[str, dict[str, Any]]] = {}

    def record(self, *, agent_id: str, task: str, action_type: str) -> dict[str, Any]:
        est = estimate_tokens(action_type)
        cost = (est["input_tokens"] / 1000 * self._in_price
                + est["output_tokens"] / 1000 * self._out_price)
        bucket = self._ledger.setdefault(agent_id, {}).setdefault(
            task, {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
        )
        bucket["calls"] += 1
        bucket["input_tokens"] += est["input_tokens"]
        bucket["output_tokens"] += est["output_tokens"]
        bucket["cost_usd"] += cost
        return {"agent_id": agent_id, "task": task, "action_type": action_type,
                **est, "cost_usd": cost}

    def for_agent(self, agent_id: str) -> dict[str, Any]:
        tasks = self._ledger.get(agent_id, {})
        total_in = sum(t["input_tokens"] for t in tasks.values())
        total_out = sum(t["output_tokens"] for t in tasks.values())
        return {
            "agent_id": agent_id,
            "basis": "metered_estimate",
            "total_tokens": total_in + total_out,
            "total_cost_usd": round(sum(t["cost_usd"] for t in tasks.values()), 6),
            "tasks": {
                task: {
                    "calls": t["calls"],
                    "tokens": t["input_tokens"] + t["output_tokens"],
                    "cost_usd": round(t["cost_usd"], 6),
                }
                for task, t in tasks.items()
            },
        }

    def fleet_snapshot(self) -> dict[str, dict[str, Any]]:
        return {agent_id: self.for_agent(agent_id) for agent_id in self._ledger}
