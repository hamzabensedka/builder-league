"""The deterministic choke point on the LLM path.

The ChiefOfStaff LLM emits free text; this module extracts and validates a
typed Directive. Anything unparseable, unknown, or malformed becomes a
harmless action="none" — the LLM can NEVER produce an un-gated state change.
"""

import json
import re
from dataclasses import dataclass

DIRECTIVE_ACTIONS = frozenset({
    "freeze_spend", "accelerate_collections", "accept_discount", "defer_po", "none",
})


@dataclass(frozen=True)
class Directive:
    action: str
    target: str
    amount_cap: float | None
    rationale: str

    def as_dict(self) -> dict:
        return {"action": self.action, "target": self.target,
                "amount_cap": self.amount_cap, "rationale": self.rationale}


def _none(reason: str) -> Directive:
    return Directive(action="none", target="", amount_cap=None, rationale=reason)


def parse_directive(text: str) -> Directive:
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not m:
        return _none("unparseable: no JSON object in LLM output")
    try:
        data = json.loads(m.group(0))
    except (json.JSONDecodeError, ValueError):
        return _none("unparseable: invalid JSON")
    action = data.get("action")
    if action not in DIRECTIVE_ACTIONS:
        return _none(f"unknown action {action!r}")
    cap = data.get("amount_cap")
    try:
        cap = None if cap is None else float(cap)
    except (TypeError, ValueError):
        return _none("unparseable: amount_cap not a number")
    return Directive(
        action=action,
        target=str(data.get("target", ""))[:100],
        amount_cap=cap,
        rationale=str(data.get("rationale", ""))[:500],
    )
