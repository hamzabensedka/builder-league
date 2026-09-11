"""MemoryCore domain tests: facts, decay, contradiction, forgetting, recall.

Pure domain — no services, no I/O. TDD: these define the model.
"""

from datetime import UTC, datetime, timedelta

import pytest

from core.memorycore.domain.contradiction import ConflictOutcome, resolve_conflict
from core.memorycore.domain.facts import (
    Fact,
    Provenance,
    SourceKind,
    decayed_confidence,
    make_fact,
)
from core.memorycore.domain.forgetting import (
    ForgetReason,
    cascaded_forgets,
    stale_facts,
)
from core.memorycore.domain.recall import (
    ACT_THRESHOLD,
    calibrated_confidence,
    recall,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def prov(kind: SourceKind, conf: float, source: str = "test") -> Provenance:
    return Provenance(source=source, kind=kind, extraction_confidence=conf)


def fact(
    slot: str = "user.city",
    value: str = "Lisbon",
    *,
    kind: SourceKind = SourceKind.OBSERVED,
    conf: float = 0.55,
    user_id: str = "u1",
    agent_id: str = "maya",
    task_id: str | None = None,
    ttl_days: int | None = None,
    learned_at: datetime = T0,
    half_life_days: int = 30,
    derived_from: tuple[str, ...] = (),
) -> Fact:
    return make_fact(
        slot=slot,
        value=value,
        provenance=prov(kind, conf),
        user_id=user_id,
        agent_id=agent_id,
        task_id=task_id,
        ttl_days=ttl_days,
        learned_at=learned_at,
        half_life_days=half_life_days,
        derived_from=derived_from,
    )


# --------------------------------------------------------------------- facts


def test_fact_base_confidence_depends_on_source_kind():
    stated = fact(kind=SourceKind.USER_STATED, conf=0.9)
    inferred = fact(kind=SourceKind.INFERRED, conf=0.9)
    assert stated.base_confidence > inferred.base_confidence


def test_fact_confidence_capped_at_one():
    f = fact(kind=SourceKind.USER_STATED, conf=1.0, value="x")
    assert 0 < f.base_confidence <= 1.0


def test_fact_rejects_empty_slot_or_value():
    with pytest.raises(ValueError):
        make_fact(slot="", value="x", provenance=prov(SourceKind.OBSERVED, 0.5),
                  user_id="u", agent_id="a", learned_at=T0)
    with pytest.raises(ValueError):
        make_fact(slot="s", value="", provenance=prov(SourceKind.OBSERVED, 0.5),
                  user_id="u", agent_id="a", learned_at=T0)


# --------------------------------------------------------------------- decay


def test_decay_monotonic_halves_at_half_life():
    f = fact(conf=0.8, half_life_days=30)
    at_zero = decayed_confidence(f, T0)
    at_half = decayed_confidence(f, T0 + timedelta(days=30))
    at_sixty = decayed_confidence(f, T0 + timedelta(days=60))
    assert at_zero == pytest.approx(f.base_confidence)
    assert at_half == pytest.approx(f.base_confidence / 2, rel=1e-3)
    assert at_sixty < at_half


def test_ttl_expired_fact_decays_to_zero():
    f = fact(conf=0.9, ttl_days=10)
    assert decayed_confidence(f, T0 + timedelta(days=11)) == 0.0
    assert f.expires_at == T0 + timedelta(days=10)


def test_no_ttl_fact_never_fully_expires():
    f = fact(conf=0.9, ttl_days=None)
    assert f.expires_at is None
    assert decayed_confidence(f, T0 + timedelta(days=3650)) > 0.0


# ------------------------------------------------------------ contradiction


def test_conflict_newer_higher_confidence_supersedes():
    old = fact(value="Lisbon", conf=0.5)
    new = fact(value="Porto", kind=SourceKind.USER_STATED, conf=0.95,
               learned_at=T0 + timedelta(days=1))
    outcome = resolve_conflict(existing=old, incoming=new, now=T0 + timedelta(days=1))
    assert outcome.outcome == ConflictOutcome.SUPERSEDE
    assert outcome.loser_id == old.id
    assert outcome.winner_id == new.id


def test_conflict_older_stronger_existing_wins():
    old = fact(value="Lisbon", kind=SourceKind.USER_STATED, conf=0.95)
    new = fact(value="Porto", kind=SourceKind.OBSERVED, conf=0.4,
               learned_at=T0 + timedelta(days=1))
    outcome = resolve_conflict(existing=old, incoming=new, now=T0 + timedelta(days=1))
    assert outcome.outcome == ConflictOutcome.REJECT_INCOMING
    assert outcome.loser_id == new.id


def test_conflict_near_equal_marks_both_contradictory():
    a = fact(value="Lisbon", conf=0.6)
    b = fact(value="Porto", conf=0.62, learned_at=T0 + timedelta(days=1))
    outcome = resolve_conflict(existing=a, incoming=b, now=T0 + timedelta(days=1))
    assert outcome.outcome == ConflictOutcome.CONTRADICTION
    assert a.id in outcome.flagged_ids and b.id in outcome.flagged_ids


def test_same_value_corroborates_not_conflicts():
    a = fact(value="Lisbon", conf=0.5)
    b = fact(value="Lisbon", conf=0.5, learned_at=T0 + timedelta(days=1))
    outcome = resolve_conflict(existing=a, incoming=b, now=T0 + timedelta(days=1))
    assert outcome.outcome == ConflictOutcome.CORROBORATE
    assert outcome.winner_id == a.id


# --------------------------------------------------------------- forgetting


def test_stale_facts_detects_decayed_below_floor():
    fresh = fact(value="a", conf=0.9, half_life_days=100)
    old_weak = fact(value="b", conf=0.4, half_life_days=5,
                    learned_at=T0 - timedelta(days=60))
    stale = stale_facts([fresh, old_weak], now=T0)
    assert [f.id for f in stale] == [old_weak.id]


def test_stale_facts_detects_ttl_expiry():
    expired = fact(value="a", conf=0.95, ttl_days=5, learned_at=T0 - timedelta(days=10))
    assert [f.id for f in stale_facts([expired], now=T0)] == [expired.id]


def test_cascade_forgets_derived_facts():
    root = fact(value="Porto")
    derived = fact(slot="user.timezone", value="Europe/Lisbon", derived_from=(root.id,))
    grandchild = fact(slot="user.currency", value="EUR", derived_from=(derived.id,))
    unrelated = fact(slot="user.drink", value="espresso")
    doomed = cascaded_forgets(root.id, [root, derived, grandchild, unrelated])
    assert doomed == {root.id, derived.id, grandchild.id}


def test_forget_reasons_enumerated():
    assert {str(r) for r in ForgetReason} == {
        "stale", "contradicted", "superseded", "revoked",
    }


# ------------------------------------------------------------------- recall


def test_recall_scope_gate_user_isolation():
    mine = fact(user_id="u1", value="Lisbon")
    theirs = fact(user_id="u2", value="Porto")
    result = recall([mine, theirs], query="city", user_id="u1",
                    agent_id="maya", now=T0)
    assert [f.id for f in result.facts] == [mine.id]


def test_recall_scope_gate_task_isolation():
    task_fact = fact(task_id="t1", value="Lisbon")
    result = recall([task_fact], query="city", user_id="u1", agent_id="maya",
                    task_id="t2", now=T0)
    assert list(result.facts) == []


def test_recall_ranks_by_relevance_times_decayed_confidence():
    strong_irrelevant = fact(slot="user.drink", value="espresso",
                             kind=SourceKind.USER_STATED, conf=0.95)
    weak_relevant = fact(slot="user.city", value="Lisbon", conf=0.5)
    result = recall([strong_irrelevant, weak_relevant], query="user city",
                    user_id="u1", agent_id="maya", now=T0)
    assert [f.id for f in result.facts] == [weak_relevant.id]


def test_recall_excludes_contradicted_and_forgotten():
    ok = fact(value="Lisbon")
    bad = fact(slot="user.city", value="Porto", conf=0.6)
    tombstoned = {bad.id: ForgetReason.CONTRADICTED}
    result = recall([ok, bad], query="city", user_id="u1", agent_id="maya", now=T0,
                    tombstones=tombstoned)
    assert [f.id for f in result.facts] == [ok.id]


def test_calibrated_confidence_below_threshold_means_unsure():
    weak = fact(conf=0.3)
    conf = calibrated_confidence([weak], now=T0)
    assert conf < ACT_THRESHOLD


def test_calibrated_confidence_single_strong_fact():
    strong = fact(kind=SourceKind.USER_STATED, conf=0.95)
    conf = calibrated_confidence([strong], now=T0)
    assert conf >= ACT_THRESHOLD


def test_recall_reports_gaps_when_nothing_matches():
    result = recall([], query="favorite color", user_id="u1", agent_id="maya", now=T0)
    assert list(result.facts) == []
    assert result.gaps  # non-empty: names what it doesn't know
