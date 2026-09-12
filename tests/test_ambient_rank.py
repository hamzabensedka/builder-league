"""TDD: the ranker — picks at most ONE hypothesis to surface, and knows when
to stop guessing (manual fallback after repeated corrections)."""

from core.ambientcore.domain.fold import fold_intents
from core.ambientcore.domain.rank import (
    SURFACE_THRESHOLD,
    rank_next,
)
from core.towercore.domain.events import make_event


def _ev(agent, seq, kind, payload):
    return make_event(agent_id=agent, run_id="run-1", seq=seq,
                      ts="2026-09-12T08:00:00+00:00", kind=kind, payload=payload)


def _deploy_events():
    return [
        _ev("deploybot", 1, "approval_requested",
            {"action": "deploy_production", "amount": 1200.0, "reason": "escalate"}),
        _ev("deploybot", 2, "drift_flagged",
            {"kind": "escalation_burst", "summary": "burst"}),
        _ev("restockbot", 1, "action_executed",
            {"action": "check_stock", "stock": {"widgets": 2}, "low": ["widgets"]}),
    ]


def test_rank_picks_single_argmax_above_threshold():
    hyps = fold_intents(
        _deploy_events(),
        fleet={"deploybot": {"status": "awaiting_approval"},
               "restockbot": {"status": "running"}},
        corrections=[],
    )
    verdict = rank_next(hyps, corrections=[])
    assert verdict.mode == "card"
    # drift_contain (0.85) beats deploy_needs_review (0.80) — but drift_contain
    # requires paused status; awaiting_approval agent only yields review+restock.
    # The surfaced card is the argmax of what the fold produced.
    assert verdict.hypothesis is not None
    assert verdict.hypothesis.confidence >= SURFACE_THRESHOLD


def test_below_threshold_yields_calm():
    events = [
        _ev("restockbot", 1, "action_executed",
            {"action": "check_stock", "stock": {"widgets": 9}, "low": []}),
    ]
    verdict = rank_next(fold_intents(events, fleet={}, corrections=[]),
                        corrections=[])
    assert verdict.mode == "calm"
    assert verdict.hypothesis is None


def test_one_correction_demotes_but_still_surfaces_when_strong():
    hyps = fold_intents(
        [_ev("deploybot", 1, "approval_requested",
             {"action": "deploy_production", "amount": 1200.0, "reason": "escalate"})],
        fleet={"deploybot": {"status": "awaiting_approval"}},
        corrections=[{"kind": "deploy_needs_review", "note": "not now", "ts": "t"}],
    )
    verdict = rank_next(hyps, corrections=[
        {"kind": "deploy_needs_review", "note": "not now", "ts": "t"}])
    # 0.80 * 0.5 = 0.40 < threshold → no card; but not yet manual fallback
    assert verdict.mode in ("calm", "manual")
    if verdict.mode == "manual":
        assert "deploy_needs_review" in verdict.exhausted_kinds


def test_two_corrections_on_same_kind_force_manual_fallback():
    corrections = [
        {"kind": "deploy_needs_review", "note": "wrong", "ts": "t1"},
        {"kind": "deploy_needs_review", "note": "still wrong", "ts": "t2"},
    ]
    hyps = fold_intents(
        [_ev("deploybot", 1, "approval_requested",
             {"action": "deploy_production", "amount": 1200.0, "reason": "escalate"})],
        fleet={"deploybot": {"status": "awaiting_approval"}},
        corrections=corrections,
    )
    verdict = rank_next(hyps, corrections=corrections)
    assert verdict.mode == "manual"
    assert "deploy_needs_review" in verdict.exhausted_kinds
    # the raw evidence is still available for the human to decide manually
    assert verdict.raw_events is not None


def test_second_kind_still_surfaces_when_first_exhausted():
    corrections = [
        {"kind": "drift_contain", "note": "wrong", "ts": "t1"},
        {"kind": "drift_contain", "note": "wrong", "ts": "t2"},
    ]
    hyps = fold_intents(
        [
            _ev("deploybot", 1, "drift_flagged",
                {"kind": "escalation_burst", "summary": "burst"}),
            _ev("deploybot", 2, "approval_requested",
                {"action": "deploy_production", "amount": 1200.0, "reason": "escalate"}),
        ],
        fleet={"deploybot": {"status": "awaiting_approval"}},
        corrections=corrections,
    )
    verdict = rank_next(hyps, corrections=corrections)
    # drift_contain exhausted (needs paused status anyway), but the parked
    # approval is still a live decision
    assert verdict.mode == "card"
    assert verdict.hypothesis.kind == "deploy_needs_review"


def test_rank_determinism():
    hyps = fold_intents(_deploy_events(),
                        fleet={"deploybot": {"status": "awaiting_approval"},
                               "restockbot": {"status": "running"}},
                        corrections=[])
    a = rank_next(hyps, corrections=[])
    b = rank_next(hyps, corrections=[])
    assert a.as_dict() == b.as_dict()
