"""TowerCore fleet: three scripted agents doing real work through real cores."""

import pytest

from core.towercore.application.agents import FLEET
from core.towercore.domain.gate import AgentHalted
from tests.tower_support import boot_tower


class TestFleetShape:
    def test_three_agents_different_jobs(self):
        jobs = {a.job for a in FLEET}
        assert len(FLEET) == 3
        assert jobs == {"procurement", "finance", "releases"}


class TestRestockBot:
    def test_purchases_within_authority(self):
        tower, _ = boot_tower()
        tower.seed_demo()
        tower.advance("restockbot")  # check stock
        tower.advance("restockbot")  # size order
        result = tower.advance("restockbot")  # purchase: real TrustCore + SimCore
        assert result["kind"] == "action_executed"
        # the purchase hit the real SimCore ledger
        assert result["payload"]["action"] == "purchase"

    def test_emits_events_every_step(self):
        tower, _ = boot_tower()
        tower.seed_demo()
        before = len(tower.stream.for_agent("restockbot"))
        tower.advance("restockbot")
        events = tower.stream.for_agent("restockbot")
        assert len(events) > before
        # the first event of a fresh advance is the step itself
        new_kinds = {e.kind for e in events[before:]}
        assert "step_started" in new_kinds

    def test_cost_recorded_per_step(self):
        tower, _ = boot_tower()
        tower.seed_demo()
        tower.advance("restockbot")
        tower.advance("restockbot")
        view = tower.fleet_snapshot()["restockbot"]
        assert view["cost_usd"] > 0
        assert view["cost_basis"] == "metered_estimate"


class TestRefundBot:
    def test_clean_refund_executes(self):
        tower, _ = boot_tower()
        tower.seed_demo()
        tower.advance("refundbot")  # pop ticket
        result = tower.advance("refundbot")  # decide on clean ticket
        assert result["kind"] == "action_executed"
        assert result["payload"]["outcome"] == "execute"

    def test_risky_refund_parks_in_approval_queue(self):
        tower, _ = boot_tower()
        tower.seed_demo()
        for _ in range(6):
            tower.advance("refundbot")
            if tower.fleet_snapshot()["refundbot"]["status"] == "awaiting_approval":
                break
        pending = tower.pending_approvals()
        assert pending, "risky refund should park for approval"
        assert pending[0].action == "issue_refund"


class TestDeployBot:
    def test_deploy_without_ticket_escalates_to_queue(self):
        tower, _ = boot_tower()
        tower.seed_demo()
        tower.advance("deploybot")  # pick release (v12, no change ticket)
        tower.advance("deploybot")  # verify ticket
        result = tower.advance("deploybot")  # deploy → escalate (missing change_ticket)
        assert result["kind"] == "approval_requested"
        assert "change_ticket" in result["payload"]["reason"]


class TestInterventions:
    def test_pause_blocks_next_step(self):
        tower, _ = boot_tower()
        tower.seed_demo()
        tower.pause("restockbot", operator="ops")
        with pytest.raises(AgentHalted):
            tower.advance("restockbot")

    def test_kill_is_enforced_on_the_path(self):
        tower, _ = boot_tower()
        tower.seed_demo()
        tower.kill("deploybot", operator="ops")
        with pytest.raises(AgentHalted):
            tower.advance("deploybot")
        assert tower.fleet_snapshot()["deploybot"]["status"] == "killed"

    def test_interventions_are_receipted(self):
        tower, _ = boot_tower()
        tower.seed_demo()
        tower.pause("restockbot", operator="ops@acme")
        kinds = [e.kind for e in tower.stream.for_agent("restockbot")]
        assert "intervention_applied" in kinds

    def test_approve_releases_parked_action(self):
        tower, _ = boot_tower()
        tower.seed_demo()
        for _ in range(3):  # pick_release, verify_ticket, deploy → parks
            tower.advance("deploybot")
        ap = tower.pending_approvals()[0]
        tower.approve(ap.id, operator="ops")
        assert tower.gate.state("deploybot") == "active"
        result = tower.advance("deploybot")  # agent resumes its loop
        assert result["kind"] in ("action_executed", "blocker_raised")

    def test_deny_skips_action(self):
        tower, _ = boot_tower()
        tower.seed_demo()
        for _ in range(3):  # → parks on v12 deploy
            tower.advance("deploybot")
        ap = tower.pending_approvals()[0]
        resolved = tower.deny(ap.id, operator="ops")
        assert resolved["skipped"] is True
        assert tower.gate.state("deploybot") == "active"
        # the denied deploy never executed: no action_executed for deploy v12
        deployed = [e for e in tower.stream.for_agent("deploybot")
                    if e.kind == "action_executed"
                    and e.payload.get("action") == "deploy_production"]
        assert deployed == []
