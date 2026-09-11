"""TowerCore InterventionGate: per-agent control state machine + approval queue."""

import pytest

from core.towercore.domain.gate import (
    AgentHalted,
    Approval,
    InterventionGate,
)


class TestControlState:
    def test_new_agent_is_active(self):
        g = InterventionGate()
        assert g.state("a1") == "active"
        g.check("a1")  # does not raise

    def test_pause_blocks_steps(self):
        g = InterventionGate()
        g.pause("a1")
        assert g.state("a1") == "paused"
        with pytest.raises(AgentHalted):
            g.check("a1")

    def test_resume_restores_active(self):
        g = InterventionGate()
        g.pause("a1")
        g.resume("a1")
        g.check("a1")  # no raise

    def test_kill_is_terminal(self):
        g = InterventionGate()
        g.kill("a1")
        assert g.state("a1") == "killed"
        with pytest.raises(AgentHalted):
            g.check("a1")
        # kill cannot be undone — no resurrection path
        with pytest.raises(ValueError, match="terminal"):
            g.resume("a1")
        with pytest.raises(ValueError, match="terminal"):
            g.pause("a1")

    def test_kill_from_paused(self):
        g = InterventionGate()
        g.pause("a1")
        g.kill("a1")
        assert g.state("a1") == "killed"

    def test_agents_are_independent(self):
        g = InterventionGate()
        g.kill("a1")
        g.check("a2")  # unaffected

    def test_states_snapshot(self):
        g = InterventionGate()
        g.pause("a1")
        g.kill("a2")
        snap = g.states()
        assert snap == {"a1": "paused", "a2": "killed"}


class TestApprovalQueue:
    def test_request_approval_parks_action(self):
        g = InterventionGate()
        ap = g.request_approval(
            agent_id="a1", action="issue_refund", amount=2400.0,
            reason="escalate: missing invoice_id", payload={"invoice": None},
        )
        assert isinstance(ap, Approval)
        assert ap.status == "pending"
        assert g.state("a1") == "awaiting_approval"
        with pytest.raises(AgentHalted):
            g.check("a1")

    def test_approve_releases_agent(self):
        g = InterventionGate()
        ap = g.request_approval(agent_id="a1", action="deploy_production",
                                amount=8000.0, reason="escalate", payload={})
        resolved = g.approve(ap.id, operator="ops@acme")
        assert resolved.status == "approved"
        assert resolved.operator == "ops@acme"
        assert g.state("a1") == "active"
        g.check("a1")  # released

    def test_deny_blocks_and_releases(self):
        g = InterventionGate()
        ap = g.request_approval(agent_id="a1", action="issue_refund",
                                amount=2400.0, reason="ask", payload={})
        resolved = g.deny(ap.id, operator="ops@acme")
        assert resolved.status == "denied"
        assert g.state("a1") == "active"

    def test_double_resolution_rejected(self):
        g = InterventionGate()
        ap = g.request_approval(agent_id="a1", action="x", amount=1.0,
                                reason="ask", payload={})
        g.approve(ap.id, operator="op")
        with pytest.raises(ValueError, match="not pending"):
            g.deny(ap.id, operator="op")

    def test_unknown_approval_rejected(self):
        g = InterventionGate()
        with pytest.raises(ValueError, match="unknown approval"):
            g.approve("nope", operator="op")

    def test_pending_queue_lists_only_pending(self):
        g = InterventionGate()
        a = g.request_approval(agent_id="a1", action="x", amount=1.0,
                               reason="ask", payload={})
        g.request_approval(agent_id="a2", action="y", amount=2.0,
                           reason="escalate", payload={})
        g.approve(a.id, operator="op")
        pending = g.pending_approvals()
        assert len(pending) == 1
        assert pending[0].action == "y"

    def test_approval_as_dict(self):
        g = InterventionGate()
        ap = g.request_approval(agent_id="a1", action="deploy_production",
                                amount=8000.0, reason="escalate: blast radius",
                                payload={"version": "v12"})
        d = ap.as_dict()
        assert d["action"] == "deploy_production"
        assert d["amount"] == 8000.0
        assert d["status"] == "pending"
        assert d["payload"] == {"version": "v12"}

    def test_kill_agent_with_pending_approval(self):
        """Killing an agent auto-denies its pending approvals (fail-closed:
        a killed agent's parked action can never be released)."""
        g = InterventionGate()
        ap = g.request_approval(agent_id="a1", action="x", amount=1.0,
                                reason="ask", payload={})
        g.kill("a1")
        assert g.get_approval(ap.id).status == "denied"
        assert g.pending_approvals() == []
        with pytest.raises(ValueError, match="not pending"):
            g.approve(ap.id, operator="op")
