"""MemoryService tests: write/recall/forget paths against real TrustCore."""

from datetime import UTC, datetime

import pytest

from core.memorycore.adapters.memory import (
    InMemoryMemoryStore,
    InMemoryTombstoneLog,
    ManualClock,
)
from core.memorycore.application.services import MemoryService
from core.memorycore.domain.facts import SourceKind
from core.trustcore.adapters.memory import (
    InMemoryAgentRegistry,
    InMemoryCredentialStore,
    InMemoryReceiptLog,
)
from core.trustcore.application.services import TrustService
from core.trustcore.domain.crypto import KeyPair, sign_payload

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def make_stack():
    clock = ManualClock(T0)
    trust_clock = ManualClock(T0)
    trust = TrustService(
        registry=InMemoryAgentRegistry(),
        credentials=InMemoryCredentialStore(),
        receipts=InMemoryReceiptLog(),
        clock=trust_clock,
    )
    svc = MemoryService(
        store=InMemoryMemoryStore(),
        tombstones=InMemoryTombstoneLog(),
        clock=clock,
        trust=trust,
    )
    return svc, clock, trust


def learn(svc, **kw):
    defaults = dict(
        slot="user.city", value="Lisbon", source="booking-email",
        kind=SourceKind.OBSERVED, extraction_confidence=0.8,
        user_id="u1", agent_id="maya",
    )
    defaults.update(kw)
    return svc.learn(**defaults)


# ---------------------------------------------------------------- write path


def test_learn_stores_new_fact_with_tags():
    svc, _, _ = make_stack()
    out = learn(svc)
    assert out["outcome"] == "stored"
    view = svc.inspect(user_id="u1", agent_id="maya")
    assert len(view["facts"]) == 1
    f = view["facts"][0]
    assert f["source"] == "booking-email"
    assert f["source_kind"] == "observed"
    assert f["scope"] == {"user_id": "u1", "agent_id": "maya", "task_id": None}
    assert 0 < f["effective_confidence"] < 1


def test_learn_same_value_corroborates():
    svc, _, _ = make_stack()
    first = learn(svc)
    second = learn(svc, source="checkin-form")
    assert second["outcome"] == "corroborate"
    assert second["fact_id"] == first["fact_id"]
    view = svc.inspect(user_id="u1", agent_id="maya")
    assert len(view["facts"]) == 1
    assert view["facts"][0]["corroborations"] == 1


def test_learn_conflict_user_correction_supersedes():
    svc, _, _ = make_stack()
    learn(svc, value="Lisbon", extraction_confidence=0.6)
    out = learn(svc, value="Porto", source="user", kind=SourceKind.USER_STATED,
                extraction_confidence=0.95)
    assert out["outcome"] == "supersede"
    view = svc.inspect(user_id="u1", agent_id="maya")
    assert [f["value"] for f in view["facts"]] == ["Porto"]
    assert len(view["tombstones"]) == 1
    assert view["tombstones"][0]["reason"] == "superseded"


def test_learn_conflict_near_equal_flags_both_untrusted():
    svc, _, _ = make_stack()
    learn(svc, value="Lisbon", extraction_confidence=0.75)  # obs 0.7*0.75=.525
    out = learn(svc, value="Porto", source="other-email",
                extraction_confidence=0.78)  # obs ~.546
    assert out["outcome"] == "contradiction"
    view = svc.inspect(user_id="u1", agent_id="maya")
    assert view["facts"] == []  # neither trusted
    assert {t["reason"] for t in view["tombstones"]} == {"contradicted"}
    # and recall says so, rather than picking one
    r = svc.recall(query="city", user_id="u1", agent_id="maya")
    assert r["verdict"] == "unknown"
    assert r["relied_on"] == []


# ------------------------------------------------------------ retrieval path


def test_recall_confident_on_user_stated_fact():
    svc, _, _ = make_stack()
    learn(svc, slot="user.seat_preference", value="window", source="user",
          kind=SourceKind.USER_STATED, extraction_confidence=0.95)
    r = svc.recall(query="seat preference", user_id="u1", agent_id="maya")
    assert r["verdict"] == "confident"
    assert r["sure"] is True
    assert r["relied_on"][0]["value"] == "window"
    assert r["calibrated_confidence"] >= r["threshold"]


def test_recall_unsure_moment_on_weak_inferred_fact():
    svc, _, _ = make_stack()
    learn(svc, slot="user.city", value="Lisbon", source="booking-email",
          kind=SourceKind.INFERRED, extraction_confidence=0.8)  # 0.5*0.8 = 0.4
    r = svc.recall(query="city", user_id="u1", agent_id="maya")
    assert r["verdict"] == "unsure"          # the "I might be wrong" state
    assert r["sure"] is False
    assert r["calibrated_confidence"] < r["threshold"]
    assert r["gaps"]  # explains WHY it isn't sure
    assert r["relied_on"][0]["value"] == "Lisbon"  # shows what it half-trusts


def test_recall_unknown_when_nothing_matches():
    svc, _, _ = make_stack()
    r = svc.recall(query="favorite color", user_id="u1", agent_id="maya")
    assert r["verdict"] == "unknown"
    assert "nothing remembered" in r["gaps"][0]


def test_recall_is_receipted_in_trust_log():
    svc, _, trust = make_stack()
    learn(svc)
    svc.recall(query="city", user_id="u1", agent_id="maya")
    actions = [r.action for r in trust.list_receipts(limit=50)]
    assert "memory.learn" in actions and "memory.recall" in actions
    assert all(not r.llm_called for r in trust.list_receipts(limit=50))


# ------------------------------------------------------------ forgetting path


def test_forget_requires_valid_signature():
    svc, _, _ = make_stack()
    out = learn(svc)
    user = KeyPair.generate()
    with pytest.raises(ValueError, match="signature"):
        svc.forget(fact_id=out["fact_id"], user_key=user.public_key_b64,
                   signature="baddies")


def test_forget_signed_revocation_tombstones_and_cascades():
    svc, _, _ = make_stack()
    user = KeyPair.generate()
    root = learn(svc, value="Porto", kind=SourceKind.USER_STATED,
                 extraction_confidence=0.95)
    derived = learn(svc, slot="user.timezone", value="Europe/Lisbon",
                    kind=SourceKind.INFERRED, derived_from=(root["fact_id"],))
    payload = {"fact_id": root["fact_id"], "reason": "forget my location"}
    out = svc.forget(fact_id=root["fact_id"], user_key=user.public_key_b64,
                     signature=sign_payload(user, payload),
                     reason="forget my location")
    forgotten_ids = {f["fact_id"] for f in out["forgotten"]}
    assert forgotten_ids == {root["fact_id"], derived["fact_id"]}
    assert all(f["reason"] == "revoked" for f in out["forgotten"])
    # recall no longer surfaces them
    r = svc.recall(query="city", user_id="u1", agent_id="maya")
    assert r["relied_on"] == []


def test_forget_unknown_fact_404s():
    svc, _, _ = make_stack()
    user = KeyPair.generate()
    payload = {"fact_id": "nope", "reason": "r"}
    with pytest.raises(ValueError, match="unknown fact"):
        svc.forget(fact_id="nope", user_key=user.public_key_b64,
                   signature=sign_payload(user, payload), reason="r")


def test_sweep_tombstones_stale_facts_explicitly():
    svc, clock, _ = make_stack()
    learn(svc, slot="user.airline", value="TAP", source="import:crm",
          kind=SourceKind.IMPORTED, extraction_confidence=0.8, ttl_days=30)
    assert svc.sweep()["swept"] == []
    clock.advance(days=45)
    out = svc.sweep()
    assert len(out["swept"]) == 1
    assert out["swept"][0]["reason"] == "stale"
    assert "TTL expired" in out["swept"][0]["detail"]
    r = svc.recall(query="airline", user_id="u1", agent_id="maya")
    assert r["relied_on"] == []


def test_inspect_shows_live_facts_and_tombstones():
    svc, clock, _ = make_stack()
    learn(svc, value="Lisbon", kind=SourceKind.USER_STATED,
          extraction_confidence=0.95)
    learn(svc, slot="user.airline", value="TAP", kind=SourceKind.IMPORTED,
          extraction_confidence=0.8, ttl_days=10)
    clock.advance(days=20)
    svc.sweep()
    view = svc.inspect(user_id="u1", agent_id="maya")
    assert [f["value"] for f in view["facts"]] == ["Lisbon"]
    assert [t["value"] for t in view["tombstones"]] == ["TAP"]
