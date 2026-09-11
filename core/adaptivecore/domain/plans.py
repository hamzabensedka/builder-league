"""Plans, steps, and assumptions — the unit of change detection.

Pure domain, zero I/O. A Plan is VERSIONED: every re-plan appends a new
version (supersedes chain), never mutates in place. Every step carries
explicit, typed assumptions — re-verified deterministically against observed
reality. A contradiction (holds at planning time, fails now) is the ONLY
trigger for a re-plan. No timers, no re-prompt loops.
"""

import hashlib
import json
import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

# --- assumption kinds ----------------------------------------------------

PRICE_AT_MOST = "price_at_most"
BUDGET_HEADROOM_AT_LEAST = "budget_headroom_at_least"
AUTHORITY_VALID = "authority_valid"
SUPPLIER_AVAILABLE = "supplier_available"
DELIVERY_WITHIN_DAYS = "delivery_within_days"
BETTER_ALTERNATIVE = "better_alternative"

ALL_KINDS = [
    PRICE_AT_MOST,
    BUDGET_HEADROOM_AT_LEAST,
    AUTHORITY_VALID,
    SUPPLIER_AVAILABLE,
    DELIVERY_WITHIN_DAYS,
    BETTER_ALTERNATIVE,
]

STEP_ACTIONS = [
    "verify_price",
    "verify_authority",
    "place_order",
    "schedule_delivery",
    "confirm_restock",
]


@dataclass(frozen=True)
class Assumption:
    """An explicit, re-verifiable belief a plan step depends on."""

    id: str
    kind: str  # one of ALL_KINDS
    params: dict[str, Any]
    statement: str  # human-readable, e.g. "NorthParts price ≤ $8.00"
    critical: bool = True

    def __post_init__(self) -> None:
        if self.kind not in ALL_KINDS:
            raise ValueError(f"unknown assumption kind {self.kind!r}")

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "params": self.params,
            "statement": self.statement,
            "critical": self.critical,
        }


@dataclass
class PlanStep:
    id: str
    index: int
    action: str  # one of STEP_ACTIONS
    params: dict[str, Any]
    assumptions: list[Assumption] = field(default_factory=list)
    status: str = "pending"  # pending|running|done|skipped|failed|deferred|blocked

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "index": self.index,
            "action": self.action,
            "params": self.params,
            "assumptions": [a.as_dict() for a in self.assumptions],
            "status": self.status,
        }


@dataclass(frozen=True)
class Plan:
    """One version of a plan. Re-planning creates a NEW Plan (supersedes)."""

    id: str
    goal: str
    version: int
    steps: tuple[PlanStep, ...]
    supersedes: str | None = None
    created_reason: str = "initial"  # "initial" | revision id

    def shape(self) -> str:
        """Canonical signature of the plan (sorted action+params). Two plans
        with the same shape are equivalent for oscillation detection."""
        keyed = sorted(
            self.steps,
            key=lambda s: (s.action, json.dumps(s.params, sort_keys=True, default=str)),
        )
        parts = [
            f"{s.action}:{json.dumps(s.params, sort_keys=True, default=str)}" for s in keyed
        ]
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]

    def with_steps(self, steps: list[PlanStep]) -> "Plan":
        """Copy with replaced steps (step status updates flow through here —
        the Plan record itself is versioned and never mutated)."""
        return replace(self, steps=tuple(steps))

    def choice_signature(self) -> str:
        """The strategic fingerprint: which supplier/entity each action chose
        AND the sizing bucket, ignoring exact prices. Oscillation is
        flip-flopping CHOICES — re-selecting the same supplier at a new price
        is the same decision; re-sizing within ±10% is the same decision."""
        keyed = sorted(self.steps, key=lambda s: s.action)
        parts = []
        for s in keyed:
            supplier = s.params.get("supplier", "-")
            qty = s.params.get("qty")
            bucket = round(qty / 10) * 10 if isinstance(qty, int | float) else "-"
            parts.append(f"{s.action}:{supplier}:{bucket}")
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "goal": self.goal,
            "version": self.version,
            "steps": [s.as_dict() for s in self.steps],
            "supersedes": self.supersedes,
            "created_reason": self.created_reason,
            "shape": self.shape(),
            "choice_signature": self.choice_signature(),
        }


_STATEMENT_BUILDERS = {
    PRICE_AT_MOST: lambda p: f"{p['supplier']} price ≤ ${p['max_price']:.2f}",
    BUDGET_HEADROOM_AT_LEAST: lambda p: f"budget headroom ≥ ${p['min_headroom']:.2f}",
    AUTHORITY_VALID: lambda p: f"valid signed authority for {p['action']}",
    SUPPLIER_AVAILABLE: lambda p: f"{p['supplier']} can fulfil orders",
    DELIVERY_WITHIN_DAYS: lambda p: f"{p['supplier']} delivers within {p['max_days']} days",
    BETTER_ALTERNATIVE: lambda p: (
        f"no feasible supplier beats {p['supplier']} by > {p['margin_pct']:.0%}"
    ),
}


def make_assumption(kind: str, *, critical: bool = True, **params: Any) -> Assumption:
    """Build a typed assumption with its human-readable statement."""
    if kind not in _STATEMENT_BUILDERS:
        raise ValueError(f"unknown assumption kind {kind!r}")
    return Assumption(
        id=str(uuid.uuid4()),
        kind=kind,
        params=params,
        statement=_STATEMENT_BUILDERS[kind](params),
        critical=critical,
    )


def make_step(index: int, action: str, params: dict[str, Any],
              assumptions: list[Assumption] | None = None) -> PlanStep:
    if action not in STEP_ACTIONS:
        raise ValueError(f"unknown step action {action!r}")
    return PlanStep(
        id=str(uuid.uuid4()),
        index=index,
        action=action,
        params=params,
        assumptions=assumptions or [],
    )


def initial_plan(*, goal: str, steps: list[PlanStep]) -> Plan:
    return Plan(
        id=str(uuid.uuid4()),
        goal=goal,
        version=1,
        steps=tuple(steps),
        supersedes=None,
        created_reason="initial",
    )


def utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()
