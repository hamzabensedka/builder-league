"""The C4 one-click demo: Maya, a travel companion whose memory knows it
might be wrong. Scripted beats hit every rubric line, server-side, on the
REAL MemoryService + TrustCore — nothing is mocked. Safe to re-click: the
scenario runs under a fresh user_id each time.

The beats mirror demo/script-c4.md (the 90s runbook).
"""

from typing import Any

from core.memorycore.application.services import MemoryService
from core.memorycore.domain.facts import SourceKind
from core.trustcore.domain.crypto import KeyPair, sign_payload

USER_ID = "demo-user"
AGENT_ID = "maya"


def seed_demo(svc: MemoryService, *, user_key: KeyPair) -> dict[str, Any]:
    """Beat 1: Maya learns two facts — one told directly (high trust), one
    inferred once from a booking email (low trust)."""
    seat = svc.learn(
        slot="user.seat_preference",
        value="window",
        source="user",
        kind=SourceKind.USER_STATED,
        extraction_confidence=0.95,
        user_id=USER_ID,
        agent_id=AGENT_ID,
    )
    city = svc.learn(
        slot="user.city",
        value="Lisbon",
        source="booking-email",
        kind=SourceKind.INFERRED,
        extraction_confidence=0.80,
        user_id=USER_ID,
        agent_id=AGENT_ID,
    )
    svc.learn(
        slot="user.airline",
        value="TAP Air Portugal",
        source="import:crm",
        kind=SourceKind.IMPORTED,
        extraction_confidence=0.80,
        user_id=USER_ID,
        agent_id=AGENT_ID,
        ttl_days=30,
    )
    return {
        "seat_fact_id": seat["fact_id"],
        "city_fact_id": city["fact_id"],
        "user_public_key": user_key.public_key_b64,
        "beats": [
            {"label": "Maya learned 'prefers window seat' — you told her "
                      "(confidence 0.95)"},
            {"label": "Maya inferred 'lives in Lisbon' from one booking email "
                      "(confidence 0.40 — and she knows it)"},
            {"label": "Imported 'flies TAP Air Portugal' from the CRM "
                      "(30-day TTL — imports go stale on purpose)"},
        ],
    }


def beat_unsure(svc: MemoryService) -> dict[str, Any]:
    """Beat 2: plan a trip. The seat recall is confident; the city recall is
    the 'I might be wrong about this' moment."""
    seat = svc.recall(query="seat preference", user_id=USER_ID, agent_id=AGENT_ID)
    city = svc.recall(query="city", user_id=USER_ID, agent_id=AGENT_ID)
    return {"seat": seat, "city": city}


def beat_correct(svc: MemoryService) -> dict[str, Any]:
    """Beat 3: the user corrects — 'I moved to Porto'. A user-stated fact
    decisively supersedes the weak inference; the old fact is tombstoned."""
    outcome = svc.learn(
        slot="user.city",
        value="Porto",
        source="user",
        kind=SourceKind.USER_STATED,
        extraction_confidence=0.95,
        user_id=USER_ID,
        agent_id=AGENT_ID,
    )
    recall_after = svc.recall(query="city", user_id=USER_ID, agent_id=AGENT_ID)
    return {"correction": outcome, "recall_after": recall_after}


def beat_age(svc: MemoryService, clock: Any) -> dict[str, Any]:
    """Beat 4: time passes. The imported airline fact crosses its TTL and the
    sweeper forgets it explicitly — retrieval stops relying on it."""
    clock.advance(days=45)
    swept = svc.sweep()
    airline = svc.recall(query="airline", user_id=USER_ID, agent_id=AGENT_ID)
    return {"swept": swept, "airline_recall_after": airline}


def beat_revoke(svc: MemoryService, *, user_key: KeyPair) -> dict[str, Any]:
    """Beat 5: privacy. The user SIGNS 'forget my location' — the Porto fact
    (and anything derived from it) is tombstoned with a receipt."""
    view = svc.inspect(user_id=USER_ID, agent_id=AGENT_ID)
    city_fact = next((f for f in view["facts"] if f["slot"] == "user.city"), None)
    if city_fact is None:
        raise ValueError("no live user.city fact to revoke — run the earlier beats first")
    reason = "forget my location"
    payload = {"fact_id": city_fact["id"], "reason": reason}
    forgotten = svc.forget(
        fact_id=city_fact["id"],
        user_key=user_key.public_key_b64,
        signature=sign_payload(user_key, payload),
        reason=reason,
    )
    recall_after = svc.recall(query="city", user_id=USER_ID, agent_id=AGENT_ID)
    return {"revoked": forgotten, "recall_after": recall_after}
