"""The intent fold — deterministic inference of what needs a decision.

Folds the TowerCore event stream + fleet state (+ budget ledger, optional)
into candidate IntentHypotheses. This is the "real intent inference, not
hardcoded flows" core: candidates emerge from event SHAPES, and the demo is
just a seeded world. No LLM anywhere on this path — every score is a named,
weighted, inspectable rule.

Corrections (operator rejections recorded via MemoryCore) demote the matching
intent kind on subsequent folds — the wrong-guess recovery is a mechanism in
the fold itself, not a separate screen.
"""

from typing import Any

from core.ambientcore.domain.intents import (
    INTENT_KINDS,
    IntentHypothesis,
    make_hypothesis,
)

# Named weights — the fold's whole job is deciding what NOT to show.
W_PENDING_APPROVAL = 0.80
W_DRIFT_FLAG = 0.85
W_LOW_STOCK = 0.60
W_BUDGET_NEAR_LIMIT = 0.55
BUDGET_RISK_PCT = 85.0  # projected_balance/limit above which spend is a risk
DEMOTION_FACTOR = 0.5  # one correction halves the kind's confidence
LOW_STOCK_THRESHOLD = 5
RESTOCK_QTY = 20
RESTOCK_UNIT_COST = 16.0  # 20 units x $16 = $320, inside the $500 authority


def _demote(kind: str, base: float, corrections: list[dict[str, Any]],
            evidence: list[str]) -> tuple[float, bool, str | None]:
    """Apply correction-driven demotion. Fail-closed: unknown correction
    kinds raise rather than silently mis-weighting the fold."""
    hits = []
    for c in corrections:
        ck = c.get("kind")
        if ck not in INTENT_KINDS:
            raise ValueError(f"unknown correction kind {ck!r}")
        if ck == kind:
            hits.append(c)
    if not hits:
        return base, False, None
    confidence = base * (DEMOTION_FACTOR ** len(hits))
    note = str(hits[-1].get("note", ""))[:200]
    evidence.append(f"correction applied ({len(hits)}x): {note or 'operator rejected this kind'}")
    return round(confidence, 3), True, note


def fold_intents(
    events: list[Any],
    *,
    fleet: dict[str, dict[str, Any]],
    corrections: list[dict[str, Any]],
    ledger: dict[str, Any] | None = None,
) -> list[IntentHypothesis]:
    """Fold events + state into scored candidates. Deterministic: identical
    inputs produce identical output order (stable sort by base confidence)."""
    # fail-closed: validate all corrections BEFORE folding — a bad correction
    # must never silently mis-weight a candidate
    for c in corrections:
        if c.get("kind") not in INTENT_KINDS:
            raise ValueError(f"unknown correction kind {c.get('kind')!r}")

    candidates: list[tuple[float, IntentHypothesis]] = []
    by_agent: dict[str, list[Any]] = {}
    for e in events:
        by_agent.setdefault(e.agent_id, []).append(e)

    # --- deploy_needs_review: a parked approval is a decision waiting ---------
    for agent_id, evs in sorted(by_agent.items()):
        requested = [e for e in evs if e.kind == "approval_requested"]
        resolved_actions = {
            e.payload.get("action")
            for e in evs if e.kind == "approval_resolved"
        }
        for e in requested:
            if (e.payload.get("action") in resolved_actions
                    and fleet.get(agent_id, {}).get("status") != "awaiting_approval"):
                continue
            if fleet.get(agent_id, {}).get("status") != "awaiting_approval":
                continue
            ev = [f"approval_requested: {e.payload.get('action')} "
                  f"(${e.payload.get('amount')}) — {e.payload.get('reason', '')}"]
            conf, demoted, note = _demote(
                "deploy_needs_review", W_PENDING_APPROVAL, corrections, ev)
            candidates.append((W_PENDING_APPROVAL, make_hypothesis(
                kind="deploy_needs_review", target=agent_id, confidence=conf,
                evidence=tuple(ev),
                missing=("what changed since the request was parked",),
                proposed_action={
                    "action": e.payload.get("action", "review"),
                    "amount": e.payload.get("amount"),
                    "description": f"resolve parked {e.payload.get('action')}",
                },
                demoted=demoted, correction_note=note,
            )))

    # --- drift_contain: a drift flag means the agent needs containment --------
    for agent_id, evs in sorted(by_agent.items()):
        flags = [e for e in evs if e.kind == "drift_flagged"]
        if not flags:
            continue
        if fleet.get(agent_id, {}).get("status") != "paused":
            continue
        latest = flags[-1]
        ev = [f"drift_flagged: {latest.payload.get('kind')} — "
              f"{latest.payload.get('summary', '')}",
              f"{len(flags)} drift flag(s) on record"]
        conf, demoted, note = _demote("drift_contain", W_DRIFT_FLAG, corrections, ev)
        candidates.append((W_DRIFT_FLAG, make_hypothesis(
            kind="drift_contain", target=agent_id, confidence=conf,
            evidence=tuple(ev),
            proposed_action={
                "action": "pause_agent", "agent_id": agent_id,
                "description": f"keep {agent_id} contained (auto-paused by tower)",
            },
            demoted=demoted, correction_note=note,
        )))

    # --- restock_needed: a low-stock observation implies a purchase decision --
    for agent_id, evs in sorted(by_agent.items()):
        checks = [e for e in evs if e.kind == "action_executed"
                  and e.payload.get("action") == "check_stock"]
        if not checks:
            continue
        latest = checks[-1]
        low = latest.payload.get("low") or []
        if not low:
            continue
        item = low[0]
        amount = round(RESTOCK_QTY * RESTOCK_UNIT_COST, 2)
        ev = [f"check_stock: {item} at "
              f"{latest.payload.get('stock', {}).get(item, '?')} units "
              f"(< {LOW_STOCK_THRESHOLD} threshold)"]
        conf, demoted, note = _demote("restock_needed", W_LOW_STOCK, corrections, ev)
        candidates.append((W_LOW_STOCK, make_hypothesis(
            kind="restock_needed", target=agent_id, confidence=conf,
            evidence=tuple(ev),
            missing=("whether a restock PO is already inbound",),
            proposed_action={
                "action": "purchase", "amount": amount,
                "description": f"restock {RESTOCK_QTY} {item} (${amount})",
            },
            demoted=demoted, correction_note=note,
        )))

    # --- budget_risk: projected spend near the enforced limit -----------------
    if ledger:
        limit = float(ledger.get("limit") or 0)
        balance = float(ledger.get("projected_balance") or 0)
        if limit > 0 and 100 * balance / limit >= BUDGET_RISK_PCT:
            ev = [f"ledger projected ${balance:.0f} of ${limit:.0f} "
                  f"({100 * balance / limit:.0f}% of enforced limit)"]
            conf, demoted, note = _demote(
                "budget_risk", W_BUDGET_NEAR_LIMIT, corrections, ev)
            candidates.append((W_BUDGET_NEAR_LIMIT, make_hypothesis(
                kind="budget_risk", target="fleet", confidence=conf,
                evidence=tuple(ev),
                missing=("which pending holds will clear vs settle",
                         "whether a top-up is planned"),
                proposed_action={
                    "action": "review_spend",
                    "description": "review pending spend before the limit bites",
                },
                demoted=demoted, correction_note=note,
            )))

    # stable, deterministic order: highest base confidence first, then kind
    candidates.sort(key=lambda t: (-t[0], t[1].kind, t[1].target))
    return [h for _, h in candidates]
