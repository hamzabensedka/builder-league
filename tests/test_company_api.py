from fastapi.testclient import TestClient

from api.main import create_app


def _client():
    return TestClient(create_app())


def test_demo_seed_and_state():
    c = _client()
    r = c.post("/api/company/demo", json={"scenario": "normal"})
    assert r.status_code == 200
    st = c.get("/api/company/state").json()
    assert st["cash"] == 50000


def test_advance_moves_kpis():
    c = _client()
    c.post("/api/company/demo", json={"scenario": "normal"})
    k0 = c.get("/api/company/kpis").json()
    out = c.post("/api/company/advance").json()
    k1 = c.get("/api/company/kpis").json()
    assert out["day"] == k0["day"] + 1
    assert k1["revenue"] >= k0["revenue"]


def test_replay_and_events():
    c = _client()
    c.post("/api/company/demo", json={"scenario": "normal"})
    c.post("/api/company/advance")
    c.post("/api/company/advance")
    r = c.get("/api/company/replay?day=1")
    assert r.status_code == 200
    ev = c.get("/api/company/events").json()
    assert isinstance(ev["events"], list) and len(ev["events"]) > 0


def test_inbox_resolve_validation():
    c = _client()
    c.post("/api/company/demo", json={"scenario": "normal"})
    r = c.post("/api/company/inbox/nope/resolve", json={"resolution": "x"})
    assert r.status_code == 404


def test_scenario_levers():
    c = _client()
    c.post("/api/company/demo", json={"scenario": "normal"})
    assert c.post("/api/company/scenario/cash-crunch").status_code == 200
    assert c.post("/api/company/scenario/rogue-sales").status_code == 200


def test_advance_before_seed_409():
    c = _client()
    assert c.post("/api/company/advance").status_code == 409
