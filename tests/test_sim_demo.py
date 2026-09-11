"""One-click C8 demo endpoint: seeds the world, returns narrated beats,
safe to click repeatedly."""

from fastapi.testclient import TestClient

from api.main import create_app


def test_demo_endpoint_seeds_and_narrates():
    client = TestClient(create_app())
    resp = client.post("/api/sim/demo")
    assert resp.status_code == 200
    body = resp.json()
    assert body["buyer_key"]
    assert body["vendor_key"]
    assert body["limit"] == 1000.0
    assert len(body["beats"]) >= 2


def test_demo_seeded_buyer_can_simulate_allow():
    """The seeded buyer has authority + history, so a $900 purchase simulates
    as ALLOW with a non-empty diff — the happy path the judges click first."""
    client = TestClient(create_app())
    buyer_key = client.post("/api/sim/demo").json()["buyer_key"]
    sim = client.post(
        "/api/sim/simulate",
        json={"requester_key": buyer_key, "amount": 900.0, "description": "100 units"},
    ).json()
    assert sim["predicted_effects"]["decision"] == "allow"
    assert sim["fork_diff"]
