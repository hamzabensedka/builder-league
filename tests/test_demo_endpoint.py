"""The one-click demo endpoint: a judge with no codebase access lands on /,
clicks 'Run the demo', and the whole 6-beat scenario executes server-side.

RED first: api endpoint doesn't exist yet.
"""

from fastapi.testclient import TestClient

from api.main import create_app


def test_demo_endpoint_runs_full_scenario():
    client = TestClient(create_app())
    r = client.post("/api/trust/demo")
    assert r.status_code == 200, r.text
    body = r.json()

    # the scenario produced agents
    agents = client.get("/api/trust/agents").json()["agents"]
    names = {a["name"] for a in agents}
    assert {"BuyerBot", "VendorBot", "SpooferBot"} <= names

    # and a full receipt trail: 1 allow + 3 refuses from the demo beats
    receipts = client.get("/api/trust/receipts?limit=50").json()["receipts"]
    decisions = [rec["decision"] for rec in receipts]
    assert decisions.count("allow") >= 1
    assert decisions.count("refuse") >= 3
    assert all(rec["llm_called"] is False for rec in receipts)

    # the response narrates the beats for the UI
    assert "beats" in body
    assert any(b.get("decision") == "allow" for b in body["beats"])
    assert any("forg" in b.get("label", "").lower() for b in body["beats"])
    assert any("revok" in b.get("label", "").lower() for b in body["beats"])


def test_demo_endpoint_is_idempotent_per_fresh_instance():
    # a second click on a fresh service instance reproduces the same story
    client = TestClient(create_app())
    client.post("/api/trust/demo")
    client.post("/api/trust/demo")
    receipts = client.get("/api/trust/receipts?limit=100").json()["receipts"]
    # 4 decisions per run (allow + 2 spoofer refuses + revocation refuse)
    assert len(receipts) == 8
