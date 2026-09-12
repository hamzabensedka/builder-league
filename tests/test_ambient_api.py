"""TDD: /api/ambient/* over TestClient. The canvas endpoint is the whole UI
contract: ambient field + at most one card + runner-ups + brain label."""

from fastapi.testclient import TestClient

from api.main import create_app


def _client():
    return TestClient(create_app())


def _seeded(c):
    c.post("/api/ambient/demo")
    for _ in range(3):  # walk deploybot to the parked v12 deploy
        r = c.post("/api/tower/agents/deploybot/advance")
        if r.status_code == 409:
            break
    return c


def test_demo_seed_and_canvas():
    c = _seeded(_client())
    snap = c.get("/api/ambient/canvas").json()
    assert snap["mode"] == "card"
    assert snap["card"]["hypothesis"]["kind"] == "deploy_needs_review"
    assert snap["card"]["brain"] in ("scripted", "llm")
    assert "ambient" in snap
    assert "fleet_summary" in snap


def test_canvas_409_before_seed():
    c = _client()
    assert c.get("/api/ambient/canvas").status_code == 409


def test_intents_lists_runner_ups():
    c = _seeded(_client())
    out = c.get("/api/ambient/intents").json()
    assert isinstance(out["intents"], list)
    assert any(i["kind"] == "deploy_needs_review" for i in out["intents"])


def test_approve_roundtrip():
    c = _seeded(_client())
    card_id = c.get("/api/ambient/canvas").json()["card"]["id"]
    r = c.post(f"/api/ambient/cards/{card_id}/approve", json={"operator": "op"})
    assert r.status_code == 200
    assert r.json()["state"] == "approved"
    # the parked tower approval is resolved by the card's execution
    assert c.get("/api/tower/approvals").json()["approvals"] == []


def test_reject_then_demoted_retry():
    c = _seeded(_client())
    first = c.get("/api/ambient/canvas").json()["card"]
    r = c.post(f"/api/ambient/cards/{first['id']}/reject",
               json={"operator": "op", "note": "not useful"})
    assert r.status_code == 200
    assert r.json()["state"] == "rejected"


def test_reject_requires_note_422():
    c = _seeded(_client())
    card_id = c.get("/api/ambient/canvas").json()["card"]["id"]
    r = c.post(f"/api/ambient/cards/{card_id}/reject", json={"operator": "op", "note": ""})
    assert r.status_code == 422


def test_unknown_card_404_and_double_resolve_409():
    c = _seeded(_client())
    assert c.post("/api/ambient/cards/card-nope/approve",
                  json={"operator": "op"}).status_code == 404
    card_id = c.get("/api/ambient/canvas").json()["card"]["id"]
    c.post(f"/api/ambient/cards/{card_id}/approve", json={"operator": "op"})
    assert c.post(f"/api/ambient/cards/{card_id}/approve",
                  json={"operator": "op"}).status_code == 409


def test_edit_reparametrizes():
    c = _seeded(_client())
    card_id = c.get("/api/ambient/canvas").json()["card"]["id"]
    r = c.post(f"/api/ambient/cards/{card_id}/edit",
               json={"operator": "op", "new_action": {
                   "action": "deploy_production", "amount": 400.0,
                   "description": "reduced blast radius"}})
    assert r.status_code == 200
    assert r.json()["state"] == "edited"
    assert r.json()["action"]["amount"] == 400.0


def test_cards_history():
    c = _seeded(_client())
    card_id = c.get("/api/ambient/canvas").json()["card"]["id"]
    c.post(f"/api/ambient/cards/{card_id}/approve", json={"operator": "op"})
    history = c.get("/api/ambient/cards").json()["cards"]
    assert any(h["id"] == card_id and h["state"] == "approved" for h in history)
