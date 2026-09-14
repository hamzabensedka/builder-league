"""InterventionGate — the control plane's teeth.

Per-agent control state machine: ACTIVE -> PAUSED -> ACTIVE, * -> KILLED
(terminal). Agents MUST call check() before every step; a halted agent raises
AgentHalted, so pause and kill are enforced at the execution path, not
advisory flags a runaway loop can ignore.

The approval queue parks risky actions: the agent blocks in
AWAITING_APPROVAL until a human approves (release) or denies (skip). Kill
auto-denies pending approvals — a killed agent's parked action can never be
released. Fail-closed everywhere.
"""

import itertools
from dataclasses import dataclass
from typing import Any

ACTIVE = "active"
PAUSED = "paused"
AWAITING = "awaiting_approval"
KILLED = "killed"


class AgentHalted(Exception):
    """Raised by check() when the agent is paused, awaiting approval, or killed."""

    def __init__(self, agent_id: str, state: str) -> None:
        self.agent_id = agent_id
        self.state = state
        super().__init__(f"agent {agent_id} is {state}: step blocked by operator")


@dataclass(frozen=True)
class Approval:
    id: str
    agent_id: str
    action: str
    amount: float | None
    reason: str
    payload: dict[str, Any]
    status: str = "pending"  # pending | approved | denied
    operator: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "action": self.action,
            "amount": self.amount,
            "reason": self.reason,
            "payload": self.payload,
            "status": self.status,
            "operator": self.operator,
        }


class InterventionGate:
    def __init__(self) -> None:
        self._states: dict[str, str] = {}
        self._approvals: dict[str, Approval] = {}
        self._ids = itertools.count(1)

    # --- control state machine ------------------------------------------------

    def state(self, agent_id: str) -> str:
        return self._states.get(agent_id, ACTIVE)

    def states(self) -> dict[str, str]:
        return dict(self._states)

    def check(self, agent_id: str) -> None:
        """The enforcement point. Agents call this before every step."""
        s = self.state(agent_id)
        if s != ACTIVE:
            raise AgentHalted(agent_id, s)

    def pause(self, agent_id: str) -> str:
        self._require_not_killed(agent_id)
        self._states[agent_id] = PAUSED
        return PAUSED

    def force_pause(self, agent_id: str) -> str:
        """Containment path: pause regardless of a parked approval. Used by the
        anomaly detector when a rogue agent must stop NOW; the pending approval
        stays queued so the operator still sees what the agent was attempting."""
        self._require_not_killed(agent_id)
        self._states[agent_id] = PAUSED
        return PAUSED

    def resume(self, agent_id: str) -> str:
        self._require_not_killed(agent_id)
        # resuming an agent with a pending approval returns it to the queue
        if any(a.agent_id == agent_id and a.status == "pending"
               for a in self._approvals.values()):
            self._states[agent_id] = AWAITING
        else:
            self._states[agent_id] = ACTIVE
        return self._states[agent_id]

    def kill(self, agent_id: str) -> str:
        """Terminal. Auto-denies pending approvals (fail-closed)."""
        self._states[agent_id] = KILLED
        for ap_id, ap in list(self._approvals.items()):
            if ap.agent_id == agent_id and ap.status == "pending":
                self._approvals[ap_id] = self._resolve(ap, "denied", "system:kill")
        return KILLED

    def _require_not_killed(self, agent_id: str) -> None:
        if self.state(agent_id) == KILLED:
            raise ValueError(f"agent {agent_id} is killed — terminal, cannot transition")

    # --- approval queue ---------------------------------------------------------

    def request_approval(
        self, *, agent_id: str, action: str, amount: float | None,
        reason: str, payload: dict[str, Any],
    ) -> Approval:
        self._require_not_killed(agent_id)
        ap = Approval(
            id=f"ap-{next(self._ids)}",
            agent_id=agent_id, action=action, amount=amount,
            reason=reason, payload=payload,
        )
        self._approvals[ap.id] = ap
        self._states[agent_id] = AWAITING
        return ap

    def approve(self, approval_id: str, *, operator: str) -> Approval:
        ap = self._require_pending(approval_id)
        resolved = self._resolve(ap, "approved", operator)
        self._approvals[ap.id] = resolved
        self._states[ap.agent_id] = ACTIVE
        return resolved

    def deny(self, approval_id: str, *, operator: str) -> Approval:
        ap = self._require_pending(approval_id)
        resolved = self._resolve(ap, "denied", operator)
        self._approvals[ap.id] = resolved
        self._states[ap.agent_id] = ACTIVE
        return resolved

    def pending_approvals(self) -> list[Approval]:
        return [a for a in self._approvals.values() if a.status == "pending"]

    def reset(self) -> None:
        """Clear all control state and pending approvals (demo re-seed path).

        Kill is terminal for a RUN, but the demo must be re-runnable: a fresh
        seed starts every agent back at ACTIVE with an empty approval queue."""
        self._states.clear()
        self._approvals.clear()

    def get_approval(self, approval_id: str) -> Approval | None:
        return self._approvals.get(approval_id)

    def _require_pending(self, approval_id: str) -> Approval:
        ap = self._approvals.get(approval_id)
        if ap is None:
            raise ValueError(f"unknown approval {approval_id}")
        if ap.status != "pending":
            raise ValueError(f"approval {approval_id} is not pending ({ap.status})")
        return ap

    @staticmethod
    def _resolve(ap: Approval, status: str, operator: str) -> Approval:
        from dataclasses import replace

        return replace(ap, status=status, operator=operator)
