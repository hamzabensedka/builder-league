"""A10: /api/adaptive router over TestClient."""

import pytest
from fastapi.testclient import TestClient

from api.main import create_app


@pytest.fixture()
def client():
    app = create_app()
    c = TestClient(app)
    seed = c.post("/api/adaptive/demo").json()
    return c, seed


def test_demo_seeds_agent_and_beats(client):
    _, seed = client
    assert seed["agent_key"]
    assert len(seed["beats"]) >= 3


def test_scenarios_listed(client):
    c, _ = client
    scenarios = c.get("/api/adaptive/scenarios").json()["scenarios"]
    ids = {s["id"] for s in scenarios}
    assert ids == {"price_spike", "budget_squeeze", "flapping_price"}
    for s in scenarios:
        assert s["injectors"]


def test_full_cycle_over_http(client):
    c, _ = client
    run = c.post("/api/adaptive/runs",
                 json={"scenario": "price_spike", "mode": "adaptive"}).json()
    assert run["status"] == "running"

    r = c.post(f"/api/adaptive/runs/{run['id']}/events",
               json={"kind": "price_changed",
                     "payload": {"supplier": "NorthParts", "new_price": 14.0}})
    assert r.status_code == 201
    assert r.json()["applied_effects"]

    run = c.post(f"/api/adaptive/runs/{run['id']}/run-to-end").json()
    assert run["status"] == "completed"
    assert len(run["revisions"]) == 1
    assert "I changed my mind because" in run["revisions"][0]["rationale"]

    fetched = c.get(f"/api/adaptive/runs/{run['id']}").json()
    assert fetched["status"] == "completed"
    assert fetched["plan"]["version"] == 2


def test_unknown_run_404(client):
    c, _ = client
    assert c.get("/api/adaptive/runs/nope").status_code == 404
    assert c.post("/api/adaptive/runs/nope/advance").status_code == 404
    r = c.post("/api/adaptive/runs/nope/events",
               json={"kind": "price_changed", "payload": {}})
    assert r.status_code == 404


def test_unknown_scenario_and_mode_422(client):
    c, _ = client
    r = c.post("/api/adaptive/runs", json={"scenario": "nope", "mode": "adaptive"})
    assert r.status_code == 422
    r = c.post("/api/adaptive/runs", json={"scenario": "price_spike", "mode": "yolo"})
    assert r.status_code == 422


def test_baseline_mode_over_http(client):
    c, _ = client
    run = c.post("/api/adaptive/runs",
                 json={"scenario": "price_spike", "mode": "baseline"}).json()
    c.post(f"/api/adaptive/runs/{run['id']}/events",
           json={"kind": "price_changed",
                 "payload": {"supplier": "NorthParts", "new_price": 14.0}})
    run = c.post(f"/api/adaptive/runs/{run['id']}/run-to-end").json()
    # the blind baseline pays the stale $7.50 → completes (within budget);
    # its failure mode is exercised with real effects in test_adaptive_baseline
    assert run["status"] in ("completed", "escalated", "failed")
    assert run["revisions"] == []


def test_adaptive_responses_carry_no_private_material(client):
    c, _ = client
    run = c.post("/api/adaptive/runs",
                 json={"scenario": "price_spike", "mode": "adaptive"}).json()
    run = c.post(f"/api/adaptive/runs/{run['id']}/run-to-end").json()
    import json

    blob = json.dumps(run)
    assert "private" not in blob.lower()
    assert "signing" not in blob.lower()
