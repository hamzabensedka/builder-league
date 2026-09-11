"""In-memory adapters for AdaptiveCore ports + the composition wrappers that
bridge to TrustCore/SimCore/DecisionCore application surfaces.

Same pattern as the other modules: thread-locked, append-only stores so the
clean-clone run needs zero external services. The *Port wrappers are the
documented seam: they translate AdaptiveCore's port protocols onto the real
public services of C1/C2/C8 (never their adapters).
"""

import threading
from typing import Any


class InMemoryRunStore:
    """Run records keyed by id. save() upserts progress; no delete."""

    def __init__(self) -> None:
        self._records: dict[str, dict[str, Any]] = {}
        self._order: list[str] = []
        self._lock = threading.Lock()

    def save(self, record: dict[str, Any]) -> None:
        with self._lock:
            if record["id"] not in self._order:
                self._order.append(record["id"])
            self._records[record["id"]] = record

    def get(self, run_id: str) -> dict[str, Any] | None:
        return self._records.get(run_id)

    def list(self, *, limit: int = 50) -> list[dict[str, Any]]:
        return [self._records[i] for i in self._order[-limit:]][::-1]


class InMemoryRevisionStore(InMemoryRunStore):
    """Append-only revision records ("I changed my mind because…" traces)."""


class InMemoryPlanStore:
    """Plan versions per run. Versions are never mutated once stored —
    status updates flow through Plan.with_steps() which the service saves
    under the same id+version (immutable content, status is operational)."""

    def __init__(self) -> None:
        self._by_run: dict[str, list[Any]] = {}
        self._by_id: dict[str, Any] = {}
        self._lock = threading.Lock()

    def save(self, run_id: str, plan: Any) -> None:
        with self._lock:
            versions = self._by_run.setdefault(run_id, [])
            for i, p in enumerate(versions):
                if p.id == plan.id:
                    versions[i] = plan  # same version, updated step statuses
                    break
            else:
                versions.append(plan)
            self._by_id[plan.id] = plan

    def get(self, plan_id: str) -> Any | None:
        return self._by_id.get(plan_id)

    def for_run(self, run_id: str) -> list[Any]:
        return list(self._by_run.get(run_id, []))


class InMemoryEventStream:
    """Append-only world event stream with monotonic seq."""

    def __init__(self) -> None:
        self._events: list[Any] = []
        self._lock = threading.Lock()

    def append(self, event: Any) -> None:
        with self._lock:
            self._events.append(event)

    def all(self) -> list[Any]:
        return list(self._events)

    def next_seq(self) -> int:
        return len(self._events) + 1


class InMemoryWorldStore:
    """The supplier world: prices, availability, delivery estimates."""

    def __init__(self) -> None:
        self._state: dict[str, Any] = {"suppliers": {}}
        self._lock = threading.Lock()

    def get(self) -> dict[str, Any]:
        return {"suppliers": {k: dict(v) for k, v in self._state["suppliers"].items()}}

    def set_supplier(self, name: str, **fields: Any) -> None:
        with self._lock:
            self._state["suppliers"].setdefault(name, {}).update(fields)


# ---------------------------------------------------------------------------
# Bridges onto the real C1/C2/C8 public application surfaces.
# ---------------------------------------------------------------------------


class SimBudgetPort:
    """SimCore's ledger as AdaptiveCore's BudgetPort — REAL shared state."""

    def __init__(self, sim_service: Any) -> None:
        self._sim = sim_service

    def committed(self) -> float:
        ledger = self._sim._ledger_store.get()  # same-process bridge, documented seam
        return ledger.projected_balance()

    def limit(self) -> float:
        return float(self._sim._limit)  # noqa: SLF001

    def place_hold(self, *, agent_key: str, amount: float, reference: str) -> dict[str, Any]:
        return self._sim.place_hold(agent_key=agent_key, amount=amount, reference=reference)

    def release_hold(self, *, amount: float, reference: str) -> dict[str, Any]:
        """Release the oldest active hold ≥ amount via a compensating refund
        entry (append-only — release is a reversal, never a delete)."""
        ledger = self._sim._ledger_store.get()  # noqa: SLF001
        target = next(
            (e for e in ledger.entries if e.kind == "hold" and e.amount >= amount
             and e.id not in {r.compensates for r in ledger.entries if r.kind == "refund"}),
            None,
        )
        if target is None:
            raise ValueError("no active hold to release")
        entry = ledger.refund(compensates=target.id, agent_key=target.agent_key,
                              reference=reference)
        return entry.as_dict()

    def spend(self, *, agent_key: str, amount: float, reference: str) -> dict[str, Any]:
        entry = self._sim._ledger_store.get().spend(  # noqa: SLF001
            agent_key=agent_key, amount=amount, reference=reference)
        return entry.as_dict()

    def refund(self, *, compensates: str, agent_key: str, reference: str) -> dict[str, Any]:
        entry = self._sim._ledger_store.get().refund(  # noqa: SLF001
            compensates=compensates, agent_key=agent_key, reference=reference)
        return entry.as_dict()

    def invariant_ok(self) -> tuple[bool, list[dict[str, Any]]]:
        from core.simcore.domain.ledger import invariant_violations

        violations = invariant_violations(
            self._sim._ledger_store.get(), limit=float(self._sim._limit))  # noqa: SLF001
        return (not violations, violations)


class TrustAuthorityPort:
    """TrustCore's service as AdaptiveCore's AuthorityPort — real credentials."""

    def __init__(self, trust_service: Any) -> None:
        self._trust = trust_service

    def authority_valid(self, *, agent_key: str, action: str) -> bool:
        profile = self._trust.trust_profile(subject_key=agent_key)
        for c in profile["credentials"]:
            if c["type"] == "AuthorityGrant" and c["valid"]:
                actions = c["scope"].get("actions", [])
                if action in actions:
                    return True
        return False

    def revoke_authority(self, *, agent_key: str, action: str, reason: str) -> str | None:
        profile = self._trust.trust_profile(subject_key=agent_key)
        for c in profile["credentials"]:
            is_grant = c["type"] == "AuthorityGrant" and c["valid"]
            if is_grant and action in c["scope"].get("actions", []):
                self._trust.revoke_credential(credential_id=c["id"], reason=reason)
                return c["id"]
        return None

    def decide_purchase(self, *, requester_key: str, amount: float,
                        description: str) -> dict[str, Any]:
        receipt = self._trust.decide(
            requester_key=requester_key, action="purchase",
            amount=amount, description=description,
        )
        return {"decision": str(receipt.decision), "receipt_id": receipt.id}


class DecisionStepGate:
    """DecisionCore's decide() as the StepGate."""

    def __init__(self, decision_service: Any) -> None:
        self._svc = decision_service

    def decide(self, *, domain: str, action: str, actor_key: str,
               amount: float | None, context: dict[str, Any]) -> dict[str, Any]:
        return self._svc.decide(
            domain=domain, action=action, actor_key=actor_key,
            amount=amount, context=context,
        )


class SimStepPreview:
    """SimCore's simulate() as the StepPreview (fork + diff, never commits)."""

    def __init__(self, sim_service: Any) -> None:
        self._sim = sim_service

    def simulate(self, *, requester_key: str, amount: float,
                 description: str) -> dict[str, Any]:
        return self._sim.simulate(
            requester_key=requester_key, amount=amount, description=description)
