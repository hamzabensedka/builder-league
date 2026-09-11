"""TowerCore API: HTTP surface for the control plane — fleet, interventions,
approvals, replay, rogue scenario, audit export."""

import pytest
from fastapi.testclient import TestClient

from api.main import create_app


@pytest.fixture
def client():
    return TestClient(create_app())


@pytest.fixture
def seeded(client):
    client.post("/api/tower/demo")
    return client


class TestSeed:
    def test_demo_seeds_fleet(self, client):
        r = client.post("/api/tower/demo")
        assert r.status_code == 200
        fleet = r.json()["fleet"]
        assert {a["agent_id"] for a in fleet} == {"restockbot", "refundbot", "deploybot"}

    def test_fleet_snapshot(self, seeded):
        r = seeded.get("/api/tower/fleet")
        assert r.status_code == 200
        agents = r.json()["agents"]
        assert set(agents) == {"restockbot", "refundbot", "deploybot"}
        assert agents["restockbot"]["cost_basis"] == "metered_estimate"


class TestAdvance:
    def test_advance_steps_agent(self, seeded):
        r = seeded.post("/api/tower/agents/restockbot/advance")
        assert r.status_code == 200
        assert r.json()["kind"] in ("action_executed", "step_started")

    def test_unknown_agent_404(self, seeded):
        r = seeded.post("/api/tower/agents/nobody/advance")
        assert r.status_code == 404

    def test_unseeded_fleet_409(self, client):
        r = client.post("/api/tower/agents/restockbot/advance")
        assert r.status_code == 409


class TestInterventions:
    def test_pause_then_advance_409(self, seeded):
        seeded.post("/api/tower/agents/restockbot/pause", json={"operator": "ops"})
        r = seeded.post("/api/tower/agents/restockbot/advance")
        assert r.status_code == 409
        assert "paused" in r.json()["detail"]

    def test_kill_is_terminal_over_http(self, seeded):
        seeded.post("/api/tower/agents/deploybot/kill", json={"operator": "ops"})
        r = seeded.post("/api/tower/agents/deploybot/advance")
        assert r.status_code == 409
        fleet = seeded.get("/api/tower/fleet").json()["agents"]
        assert fleet["deploybot"]["status"] == "killed"

    def test_resume_recovers(self, seeded):
        seeded.post("/api/tower/agents/restockbot/pause", json={"operator": "ops"})
        seeded.post("/api/tower/agents/restockbot/resume", json={"operator": "ops"})
        r = seeded.post("/api/tower/agents/restockbot/advance")
        assert r.status_code == 200


class TestApprovalFlow:
    def _park_deploy(self, seeded):
        for _ in range(3):
            seeded.post("/api/tower/agents/deploybot/advance")

    def test_approval_lands_in_queue(self, seeded):
        self._park_deploy(seeded)
        r = seeded.get("/api/tower/approvals")
        assert r.status_code == 200
        pending = r.json()["approvals"]
        assert pending and pending[0]["action"] == "deploy_production"

    def test_approve_releases(self, seeded):
        self._park_deploy(seeded)
        ap_id = seeded.get("/api/tower/approvals").json()["approvals"][0]["id"]
        r = seeded.post(f"/api/tower/approvals/{ap_id}/approve", json={"operator": "ops"})
        assert r.status_code == 200
        assert r.json()["status"] == "approved"

    def test_deny_skips(self, seeded):
        self._park_deploy(seeded)
        ap_id = seeded.get("/api/tower/approvals").json()["approvals"][0]["id"]
        r = seeded.post(f"/api/tower/approvals/{ap_id}/deny", json={"operator": "ops"})
        assert r.status_code == 200
        assert r.json()["skipped"] is True

    def test_double_resolution_409(self, seeded):
        self._park_deploy(seeded)
        ap_id = seeded.get("/api/tower/approvals").json()["approvals"][0]["id"]
        seeded.post(f"/api/tower/approvals/{ap_id}/approve", json={"operator": "ops"})
        r = seeded.post(f"/api/tower/approvals/{ap_id}/deny", json={"operator": "ops"})
        assert r.status_code == 409


class TestReplayAndAudit:
    def test_replay_returns_trace(self, seeded):
        for _ in range(3):
            seeded.post("/api/tower/agents/restockbot/advance")
        r = seeded.get("/api/tower/agents/restockbot/replay?n=10")
        assert r.status_code == 200
        trace = r.json()["trace"]
        assert trace and all("seq" in t and "text" in t for t in trace)

    def test_audit_export_is_jsonl_stream(self, seeded):
        for _ in range(2):
            seeded.post("/api/tower/agents/restockbot/advance")
        r = seeded.get("/api/tower/audit")
        assert r.status_code == 200
        events = r.json()["events"]
        assert events and all("kind" in e and "seq" in e for e in events)


class TestRogueScenario:
    def test_rogue_injection_leads_to_containment(self, seeded):
        """The full failure test, operator-in-the-loop: inject a corrupted
        objective, deny the rogue demands as they park, and the escalation
        burst auto-pauses the agent — then replay and kill."""
        seeded.post("/api/tower/scenario/rogue", json={"agent_id": "deploybot"})
        for _ in range(12):
            fleet = seeded.get("/api/tower/fleet").json()["agents"]
            if fleet["deploybot"]["status"] in ("paused", "killed"):
                break
            r = seeded.post("/api/tower/agents/deploybot/advance")
            if r.status_code == 409:
                # parked on an over-authority demand: operator denies it, agent retries
                pending = seeded.get("/api/tower/approvals").json()["approvals"]
                if pending:
                    seeded.post(f"/api/tower/approvals/{pending[0]['id']}/deny",
                                json={"operator": "ops"})
                else:
                    break
        fleet = seeded.get("/api/tower/fleet").json()["agents"]
        assert fleet["deploybot"]["status"] in ("paused", "killed")
        assert fleet["deploybot"]["drift"], "rogue burst should flag drift"

    def test_audit_trail_covers_the_whole_incident(self, seeded):
        seeded.post("/api/tower/scenario/rogue", json={"agent_id": "deploybot"})
        for _ in range(12):
            fleet = seeded.get("/api/tower/fleet").json()["agents"]
            if fleet["deploybot"]["status"] in ("paused", "killed"):
                break
            r = seeded.post("/api/tower/agents/deploybot/advance")
            if r.status_code == 409:
                pending = seeded.get("/api/tower/approvals").json()["approvals"]
                if pending:
                    seeded.post(f"/api/tower/approvals/{pending[0]['id']}/deny",
                                json={"operator": "ops"})
                else:
                    break
        seeded.post("/api/tower/agents/deploybot/kill", json={"operator": "ops"})
        kinds = [e["kind"] for e in seeded.get("/api/tower/audit").json()["events"]
                 if e["agent_id"] == "deploybot"]
        # injection → demands → drift → containment → kill, all in one trail
        assert "blocker_raised" in kinds       # the injection marker
        assert "approval_requested" in kinds   # the rogue demands
        assert "drift_flagged" in kinds        # the tower caught it
        assert "intervention_applied" in kinds # auto_pause + kill
