"""C4 failure tests: contradictory facts, stale data, privacy revocation,
scope leaks, determinism. Each is an explicit, receipted behavior — the
rubric's 'failure thinking' criterion.
"""

from datetime import UTC, datetime

from core.memorycore.adapters.memory import (
    InMemoryMemoryStore,
    InMemoryTombstoneLog,
    ManualClock,
)
from core.memorycore.application.demo import AGENT_ID, USER_ID, beat_unsure, seed_demo
from core.memorycore.application.services import MemoryService
from core.memorycore.domain.facts import SourceKind
from core.trustcore.adapters.memory import (
    InMemoryAgentRegistry,
    InMemoryCredentialStore,
    InMemoryReceiptLog,
)
from core.trustcore.application.services import TrustService
from core.trustcore.domain.crypto import KeyPair

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def make_stack():
    clock = ManualClock(T0)
    trust = TrustService(
        registry=InMemoryAgentRegistry(),
        credentials=InMemoryCredentialStore(),
        receipts=InMemoryReceiptLog(),
        clock=ManualClock(T0),
    )
    svc = MemoryService(
        store=InMemoryMemoryStore(),
        tombstones=InMemoryTombstoneLog(),
        clock=clock,
        trust=trust,
    )
    return svc, clock, trust


# ------------------------------------------------------------- contradiction


def test_failure_contradiction_equal_confidence_trusts_neither():
    svc, _, _ = make_stack()
    svc.learn(slot="user.city", value="Lisbon", source="email-a",
              kind=SourceKind.OBSERVED, extraction_confidence=0.75,
              user_id="u1", agent_id="maya")
    out = svc.learn(slot="user.city", value="Porto", source="email-b",
                    kind=SourceKind.OBSERVED, extraction_confidence=0.78,
                    user_id="u1", agent_id="maya")
    assert out["outcome"] == "contradiction"
    r = svc.recall(query="city", user_id="u1", agent_id="maya")
    # the memory does NOT pick a side — it reports the conflict
    assert r["relied_on"] == []
    assert r["verdict"] == "unknown"


def test_failure_contradiction_resolved_by_user_correction():
    svc, _, _ = make_stack()
    svc.learn(slot="user.city", value="Lisbon", source="email-a",
              kind=SourceKind.OBSERVED, extraction_confidence=0.75,
              user_id="u1", agent_id="maya")
    svc.learn(slot="user.city", value="Porto", source="email-b",
              kind=SourceKind.OBSERVED, extraction_confidence=0.78,
              user_id="u1", agent_id="maya")
    # user settles it — a fresh user-stated fact has no live rival after the
    # tie tombstoned both claimants
    svc.learn(slot="user.city", value="Porto", source="user",
              kind=SourceKind.USER_STATED, extraction_confidence=0.95,
              user_id="u1", agent_id="maya")
    r = svc.recall(query="city", user_id="u1", agent_id="maya")
    assert r["verdict"] == "confident"
    assert r["relied_on"][0]["value"] == "Porto"


# ----------------------------------------------------------------- staleness


def test_failure_stale_fact_never_relied_on_after_sweep():
    svc, clock, _ = make_stack()
    svc.learn(slot="user.airline", value="TAP", source="import:crm",
              kind=SourceKind.IMPORTED, extraction_confidence=0.8,
              user_id="u1", agent_id="maya", ttl_days=30)
    before = svc.recall(query="airline", user_id="u1", agent_id="maya")
    assert before["relied_on"]  # fresh import is still relied on
    clock.advance(days=60)
    svc.sweep()
    after = svc.recall(query="airline", user_id="u1", agent_id="maya")
    assert after["relied_on"] == []
    assert after["verdict"] == "unknown"


def test_failure_decay_is_deterministic():
    svc_a, clock_a, _ = make_stack()
    svc_b, clock_b, _ = make_stack()
    for svc in (svc_a, svc_b):
        svc.learn(slot="user.city", value="Lisbon", source="obs",
                  kind=SourceKind.OBSERVED, extraction_confidence=0.8,
                  user_id="u1", agent_id="maya")
    clock_a.advance(days=10)
    clock_b.advance(days=10)
    ra = svc_a.recall(query="city", user_id="u1", agent_id="maya")
    rb = svc_b.recall(query="city", user_id="u1", agent_id="maya")
    assert ra["calibrated_confidence"] == rb["calibrated_confidence"]


# ---------------------------------------------------------------- revocation


def test_failure_unsigned_revocation_refused_fail_closed():
    svc, _, _ = make_stack()
    out = svc.learn(slot="user.city", value="Porto", source="user",
                    kind=SourceKind.USER_STATED, extraction_confidence=0.95,
                    user_id="u1", agent_id="maya")
    attacker = KeyPair.generate()
    try:
        svc.forget(fact_id=out["fact_id"], user_key=attacker.public_key_b64,
                   signature="forged", reason="forget my location")
        raise AssertionError("unsigned revocation must be refused")
    except ValueError as exc:
        assert "signature" in str(exc)
    # fact still live — failed revocations change nothing
    view = svc.inspect(user_id="u1", agent_id="maya")
    assert len(view["facts"]) == 1


def test_failure_revocation_is_receipted_in_append_only_log():
    svc, _, trust = make_stack()
    user = KeyPair.generate()
    from core.trustcore.domain.crypto import sign_payload

    out = svc.learn(slot="user.city", value="Porto", source="user",
                    kind=SourceKind.USER_STATED, extraction_confidence=0.95,
                    user_id="u1", agent_id="maya")
    reason = "forget my location"
    svc.forget(fact_id=out["fact_id"], user_key=user.public_key_b64,
               signature=sign_payload(user, {"fact_id": out["fact_id"],
                                             "reason": reason}),
               reason=reason)
    notes = [r for r in trust.list_receipts(limit=50) if r.action == "memory.forget"]
    assert notes and "revoked" in notes[0].reasoning


# --------------------------------------------------------------------- scope


def test_failure_task_scoped_fact_never_leaks():
    svc, _, _ = make_stack()
    svc.learn(slot="task.budget", value="$500", source="user",
              kind=SourceKind.USER_STATED, extraction_confidence=0.95,
              user_id="u1", agent_id="maya", task_id="task-A")
    leaked = svc.recall(query="budget", user_id="u1", agent_id="maya",
                        task_id="task-B")
    assert leaked["relied_on"] == []
    inside = svc.recall(query="budget", user_id="u1", agent_id="maya",
                        task_id="task-A")
    assert inside["relied_on"]


def test_failure_user_scoped_fact_never_leaks_across_users():
    svc, _, _ = make_stack()
    svc.learn(slot="user.city", value="Lisbon", source="user",
              kind=SourceKind.USER_STATED, extraction_confidence=0.95,
              user_id="u1", agent_id="maya")
    other = svc.recall(query="city", user_id="u2", agent_id="maya")
    assert other["relied_on"] == []
    inspector = svc.inspect(user_id="u2", agent_id="maya")
    assert inspector["facts"] == []


# --------------------------------------------------------------- determinism


def test_failure_demo_scenario_deterministic_across_stacks():
    def run():
        svc, _, _ = make_stack()
        user = KeyPair.generate()
        seed_demo(svc, user_key=user)
        return beat_unsure(svc)

    a, b = run(), run()
    assert a["seat"]["verdict"] == b["seat"]["verdict"] == "confident"
    assert a["city"]["verdict"] == b["city"]["verdict"] == "unsure"
    assert a["city"]["calibrated_confidence"] == b["city"]["calibrated_confidence"]


def test_demo_seed_beats_narrate_tags():
    svc, _, _ = make_stack()
    out = seed_demo(svc, user_key=KeyPair.generate())
    assert len(out["beats"]) == 3
    assert out["city_fact_id"]
    view = svc.inspect(user_id=USER_ID, agent_id=AGENT_ID)
    assert len(view["facts"]) == 3
