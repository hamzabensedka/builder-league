"""HTTP round-trip for the /api/sim router: simulate → get → execute →
rollback over FastAPI TestClient. The approval payload must be a real
before/after diff, not a confirm string."""

from fastapi.testclient import TestClient

from api.main import create_app


def _client() -> TestClient:
    return TestClient(create_app())


def _seeded_buyer_key(client: TestClient) -> str:
    """Use the C8 demo seeder to stand up a funded buyer, return its key."""
    resp = client.post("/api/sim/demo")
    assert resp.status_code == 200
    return resp.json()["buyer_key"]


class TestSimulateFlow:
    def test_simulate_returns_real_diff_payload(self):
        client = _client()
        buyer_key = _seeded_buyer_key(client)
        resp = client.post(
            "/api/sim/simulate",
            json={"requester_key": buyer_key, "amount": 900.0, "description": "100 units"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["status"] == "pending"
        assert body["fork_diff"], "approval payload must contain the computed diff"
        assert "ledger" in str(body["fork_diff"]) or "receipts" in str(body["fork_diff"])
        assert body["rollback_preview"]["entries"], "rollback path shown pre-approval"
        assert body["predicted_effects"]["balance_after"] == 900.0

    def test_get_simulation(self):
        client = _client()
        buyer_key = _seeded_buyer_key(client)
        sim_id = client.post(
            "/api/sim/simulate",
            json={"requester_key": buyer_key, "amount": 100.0, "description": "x"},
        ).json()["id"]
        resp = client.get(f"/api/sim/{sim_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == sim_id

    def test_unknown_simulation_404(self):
        client = _client()
        assert client.get("/api/sim/no-such-id").status_code == 404
        assert client.post("/api/sim/no-such-id/execute").status_code == 404

    def test_execute_then_rollback_round_trip(self):
        client = _client()
        buyer_key = _seeded_buyer_key(client)
        sim_id = client.post(
            "/api/sim/simulate",
            json={"requester_key": buyer_key, "amount": 900.0, "description": "x"},
        ).json()["id"]

        executed = client.post(f"/api/sim/{sim_id}/execute").json()
        assert executed["status"] == "executed"
        assert executed["post_check"]["ok"] is True

        rolled = client.post(f"/api/sim/{sim_id}/rollback").json()
        assert rolled["status"] == "rolled_back"
        assert rolled["post_check"]["ok"] is True

    def test_double_execute_rejected(self):
        client = _client()
        buyer_key = _seeded_buyer_key(client)
        sim_id = client.post(
            "/api/sim/simulate",
            json={"requester_key": buyer_key, "amount": 100.0, "description": "x"},
        ).json()["id"]
        assert client.post(f"/api/sim/{sim_id}/execute").status_code == 200
        assert client.post(f"/api/sim/{sim_id}/execute").status_code == 409

    def test_reject_blocks_execute(self):
        client = _client()
        buyer_key = _seeded_buyer_key(client)
        sim_id = client.post(
            "/api/sim/simulate",
            json={"requester_key": buyer_key, "amount": 100.0, "description": "x"},
        ).json()["id"]
        assert client.post(f"/api/sim/{sim_id}/reject").json()["status"] == "rejected"
        assert client.post(f"/api/sim/{sim_id}/execute").status_code == 409


class TestFailureOverHttp:
    def test_concurrent_hold_escalates_and_rollback_restores(self):
        client = _client()
        buyer_key = _seeded_buyer_key(client)
        sim_id = client.post(
            "/api/sim/simulate",
            json={"requester_key": buyer_key, "amount": 900.0, "description": "bulk"},
        ).json()["id"]

        # separate actor injects a real hold between simulate and execute
        hold = client.post(
            "/api/sim/hold", json={"agent_key": "vendor-x", "amount": 200.0}
        )
        assert hold.status_code == 201

        executed = client.post(f"/api/sim/{sim_id}/execute").json()
        assert executed["status"] == "escalated"
        assert executed["post_check"]["ok"] is False
        assert executed["rollback_preview"]["entries"], "rollback offered on escalation"

        rolled = client.post(f"/api/sim/{sim_id}/rollback").json()
        assert rolled["status"] == "rolled_back"
        assert rolled["post_check"]["ok"] is True
