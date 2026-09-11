"""C4 API tests: the /api/memory surface over HTTP (TestClient)."""

from fastapi.testclient import TestClient

from api.main import create_app


def make_client():
    return TestClient(create_app())


def test_demo_seed_and_inspect():
    c = make_client()
    r = c.post("/api/memory/demo")
    assert r.status_code == 200
    body = r.json()
    assert len(body["beats"]) == 3
    assert body["city_fact_id"]
    view = c.get("/api/memory/inspect", params={"user_id": "demo-user"}).json()
    assert len(view["facts"]) == 3
    slots = {f["slot"] for f in view["facts"]}
    assert slots == {"user.seat_preference", "user.city", "user.airline"}


def test_unsure_beat_is_the_i_might_be_wrong_moment():
    c = make_client()
    c.post("/api/memory/demo")
    r = c.post("/api/memory/demo/unsure").json()
    assert r["seat"]["verdict"] == "confident"
    city = r["city"]
    assert city["verdict"] == "unsure"
    assert city["sure"] is False
    assert city["calibrated_confidence"] < city["threshold"]
    assert city["gaps"]  # explains why it isn't sure
    assert city["relied_on"][0]["value"] == "Lisbon"


def test_full_demo_arc_correct_age_revoke():
    c = make_client()
    c.post("/api/memory/demo")

    # beat 3: user correction supersedes
    corr = c.post("/api/memory/demo/correct").json()
    assert corr["correction"]["outcome"] == "supersede"
    assert corr["recall_after"]["relied_on"][0]["value"] == "Porto"
    assert corr["recall_after"]["verdict"] == "confident"

    # beat 4: ageing sweeps the imported airline fact
    aged = c.post("/api/memory/demo/age").json()
    assert len(aged["swept"]["swept"]) == 1
    assert aged["swept"]["swept"][0]["reason"] == "stale"
    assert aged["airline_recall_after"]["relied_on"] == []

    # beat 5: signed revocation forgets the city fact
    rev = c.post("/api/memory/demo/revoke").json()
    assert rev["revoked"]["forgotten"]
    assert all(f["reason"] == "revoked" for f in rev["revoked"]["forgotten"])
    assert rev["recall_after"]["relied_on"] == []

    # inspector shows live facts + tombstones
    view = c.get("/api/memory/inspect", params={"user_id": "demo-user"}).json()
    assert [f["slot"] for f in view["facts"]] == ["user.seat_preference"]
    assert len(view["tombstones"]) >= 2


def test_revoke_before_demo_is_409():
    c = make_client()
    r = c.post("/api/memory/demo/revoke")
    assert r.status_code == 409


def test_learn_recall_roundtrip_over_http():
    c = make_client()
    r = c.post("/api/memory/learn", json={
        "slot": "user.drink", "value": "espresso", "source": "user",
        "kind": "user_stated", "extraction_confidence": 0.95, "user_id": "u9",
    })
    assert r.status_code == 201
    rec = c.post("/api/memory/recall", json={"query": "drink", "user_id": "u9"}).json()
    assert rec["verdict"] == "confident"
    assert rec["relied_on"][0]["value"] == "espresso"


def test_learn_validation_422():
    c = make_client()
    r = c.post("/api/memory/learn", json={
        "slot": "user.drink", "value": "espresso", "source": "user",
        "kind": "user_stated", "extraction_confidence": 1.5, "user_id": "u9",
    })
    assert r.status_code == 422


def test_forget_unsigned_is_403():
    c = make_client()
    out = c.post("/api/memory/learn", json={
        "slot": "user.city", "value": "Porto", "source": "user",
        "kind": "user_stated", "extraction_confidence": 0.95, "user_id": "u9",
    }).json()
    r = c.post("/api/memory/forget", json={
        "fact_id": out["fact_id"], "user_key": "aaaa", "signature": "bbbb",
    })
    assert r.status_code == 403
    # nothing was forgotten
    view = c.get("/api/memory/inspect", params={"user_id": "u9"}).json()
    assert len(view["facts"]) == 1


def test_events_feed_lists_tombstones():
    c = make_client()
    c.post("/api/memory/demo")
    c.post("/api/memory/demo/age")
    events = c.get("/api/memory/events").json()
    assert any(t["reason"] == "stale" for t in events["tombstones"])


def test_memory_receipts_land_in_trust_log():
    c = make_client()
    c.post("/api/memory/demo")
    c.post("/api/memory/demo/unsure")
    receipts = c.get("/api/trust/receipts", params={"limit": 50}).json()["receipts"]
    actions = {r["action"] for r in receipts}
    assert "memory.learn" in actions and "memory.recall" in actions
    assert all(r["llm_called"] is False for r in receipts)
