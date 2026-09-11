"""Damping — the stability layer that keeps adaptation from becoming the bug.

Pure domain. Three deterministic rules, each producing an explicit decision:

1. HYSTERESIS (min-delta): a contradiction on a kind that already triggered a
   revision only re-triggers when the observed value moved beyond the last
   trigger by more than `margin_pct`. Sub-margin flaps are absorbed.
2. REVISION BUDGET: a run may re-plan at most `max_revisions` times; the next
   contradiction escalates to a human instead of re-planning.
3. OSCILLATION DETECTION: if the new plan's shape matches a shape seen two
   revisions back (A→B→A), the world is unstable around the decision
   boundary — escalate immediately rather than flip again.
"""

from dataclasses import dataclass, field
from typing import Any

from core.adaptivecore.domain.detection import Contradiction
from core.adaptivecore.domain.plans import PRICE_AT_MOST

DAMPED = "damped"
ALLOWED = "allowed"
ESCALATE_BUDGET = "escalate_budget"
ESCALATE_OSCILLATION = "escalate_oscillation"


@dataclass
class DampingState:
    revision_count: int = 0
    max_revisions: int = 3
    cooldown_until_seq: int = 0  # hysteresis on time-axis: no re-plan before this seq
    recent_plan_shapes: list[str] = field(default_factory=list)
    last_trigger_values: dict[str, float] = field(default_factory=dict)  # kind -> observed number
    margin_pct: float = 0.02  # 2% min-delta
    cooldown_span: int = 1  # stream positions to wait after a revision
    epsilon: float = 0.01  # absolute floor for the min-delta (cents, for prices)

    def as_dict(self) -> dict[str, Any]:
        return {
            "revision_count": self.revision_count,
            "max_revisions": self.max_revisions,
            "cooldown_until_seq": self.cooldown_until_seq,
            "recent_plan_shapes": list(self.recent_plan_shapes),
            "last_trigger_values": dict(self.last_trigger_values),
            "margin_pct": self.margin_pct,
            "cooldown_span": self.cooldown_span,
            "epsilon": self.epsilon,
        }


@dataclass(frozen=True)
class DampingDecision:
    verdict: str  # DAMPED | ALLOWED | ESCALATE_BUDGET | ESCALATE_OSCILLATION
    reason: str
    surviving: list[Contradiction] = field(default_factory=list)  # post-hysteresis

    def as_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "reason": self.reason,
            "surviving": [c.as_dict() for c in self.surviving],
        }


def _observed_number(c: Contradiction) -> float | None:
    """Extract the numeric observed value for min-delta comparison."""
    import re

    patterns = {
        PRICE_AT_MOST: r"price = ([\d.]+)",
        "budget_headroom_at_least": r"headroom = ([\d.]+)",
    }
    pattern = patterns.get(c.assumption_kind)
    if pattern is None:
        return None
    m = re.search(pattern, c.observed)
    return float(m.group(1)) if m else None


def evaluate_damping(
    *,
    state: DampingState,
    contradictions: list[Contradiction],
    new_plan_shape: str,
    current_seq: int,
) -> DampingDecision:
    """Decide whether these contradictions may trigger a re-plan. Pure."""
    if not contradictions:
        return DampingDecision(verdict=DAMPED, reason="no contradictions to act on", surviving=[])

    # rule 3: oscillation — new shape seen two revisions ago (A→B→A)
    if len(state.recent_plan_shapes) >= 2 and state.recent_plan_shapes[-2] == new_plan_shape:
        return DampingDecision(
            verdict=ESCALATE_OSCILLATION,
            reason=(
                "oscillation detected: revised plan repeats the shape from two revisions ago "
                "(A→B→A); world is unstable around the decision boundary — escalating to a human"
            ),
            surviving=contradictions,
        )

    # rule 2: revision budget
    if state.revision_count >= state.max_revisions:
        return DampingDecision(
            verdict=ESCALATE_BUDGET,
            reason=(
                f"revision budget exhausted ({state.revision_count}/{state.max_revisions}); "
                "refusing to re-plan again — escalating to a human"
            ),
            surviving=contradictions,
        )

    # hysteresis on the time axis: just revised, let the world settle
    if current_seq <= state.cooldown_until_seq:
        return DampingDecision(
            verdict=DAMPED,
            reason=(
                f"cooldown active until stream position {state.cooldown_until_seq}; "
                "absorbing contradiction to let the world settle"
            ),
            surviving=[],
        )

    # rule 1: min-delta hysteresis per assumption kind
    surviving: list[Contradiction] = []
    damped: list[str] = []
    for c in contradictions:
        num = _observed_number(c)
        last = state.last_trigger_values.get(c.assumption_kind)
        if num is not None and last is not None:
            delta = abs(num - last)
            threshold = max(abs(last) * state.margin_pct, state.epsilon)
            if delta <= threshold:
                damped.append(
                    f"{c.assumption_kind} moved {delta:.2f} (≤ {threshold:.2f} margin) "
                    f"since last trigger {last:.2f}"
                )
                continue
        surviving.append(c)

    if not surviving:
        return DampingDecision(
            verdict=DAMPED,
            reason="hysteresis absorbed all contradictions: " + "; ".join(damped),
            surviving=[],
        )

    return DampingDecision(
        verdict=ALLOWED,
        reason=(
            f"{len(surviving)} contradiction(s) exceed damping margins"
            + (f"; damped: {'; '.join(damped)}" if damped else "")
        ),
        surviving=surviving,
    )


def record_revision(state: DampingState, *, contradictions: list[Contradiction],
                    new_plan_shape: str, current_seq: int) -> None:
    """Update damping state after an allowed revision (mutates state — the
    DampingState object is the persisted per-run record)."""
    state.revision_count += 1
    state.recent_plan_shapes.append(new_plan_shape)
    state.cooldown_until_seq = current_seq + state.cooldown_span
    for c in contradictions:
        num = _observed_number(c)
        if num is not None:
            state.last_trigger_values[c.assumption_kind] = num
