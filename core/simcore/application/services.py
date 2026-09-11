"""SimService: simulate → present diff → execute → post-check → rollback.

Orchestrates fork/pipeline/diff through ports. No framework imports. No LLM
on any path — simulation, execution, post-check and rollback are pure Python
plus the existing deterministic TrustCore policy.

Key design: simulate() runs the REAL pipeline against a forked TrustService
built from a deep-copied snapshot, so the preview uses identical logic to
execution. execute() runs the same pipeline against live stores.
"""

import copy
import uuid
from datetime import UTC, datetime
from typing import Any

from core.simcore.application.pipeline import run_purchase
from core.simcore.domain.diff import diff_snapshots
from core.simcore.domain.fork import snapshot_parts, snapshot_store
from core.simcore.domain.ledger import BudgetLedger, LedgerEntry, invariant_violations
from core.trustcore.application.services import TrustService
from core.trustcore.domain.credentials import CredentialType


def _default_trust_factory() -> tuple:
    """Fresh empty in-memory trust stores. Imported here (composition detail)
    rather than at module top so the application layer's adapter imports stay
    localized and swappable; import-linter contract allows adapters above
    application, and this factory IS the documented seam the root injects."""
    from core.trustcore.adapters.memory import (
        InMemoryAgentRegistry,
        InMemoryCredentialStore,
        InMemoryReceiptLog,
        SystemClock,
    )

    return (
        InMemoryAgentRegistry(),
        InMemoryCredentialStore(),
        InMemoryReceiptLog(),
        SystemClock(),
    )


def _entry_from_dict(d: dict[str, Any]) -> LedgerEntry:
    return LedgerEntry(
        id=d["id"],
        ts=datetime.fromisoformat(d["ts"]),
        kind=d["kind"],
        agent_key=d["agent_key"],
        amount=d["amount"],
        currency=d["currency"],
        reference=d["reference"],
        compensates=d.get("compensates"),
    )


class SimService:
    def __init__(
        self,
        *,
        trust: TrustService,
        ledger_store: Any,  # LedgerStore port: .get() -> BudgetLedger
        simulations: Any,  # SimulationStore port: save/get/list
        limit: float,
        trust_factory: Any = None,  # () -> (registry, creds, receipts, clock)
    ) -> None:
        self._trust = trust
        self._ledger_store = ledger_store
        self._sims = simulations
        self._limit = limit
        # Injected by the composition root; default keeps tests/simple wiring
        # working while preserving the layering contract.
        self._trust_factory = trust_factory or _default_trust_factory

    # --- simulate -----------------------------------------------------------

    def _fork_trust(self) -> TrustService:
        """A TrustService whose stores contain deep copies of live state.

        Built through the trustcore adapter FACTORY (application layer never
        imports adapters — import-linter enforced); the factory is injected
        by the composition root (api/main.py)."""
        fork = self._trust_factory()  # -> (registry, creds, receipts, clock)
        registry, creds, receipts, clock = fork
        for agent in self._trust.list_agents():
            registry.register(
                name=agent["name"], public_key=agent["public_key"], owner=agent["owner"]
            )
        # Real signed credentials, copied verbatim — a simulation re-verifies
        # the same signatures the live path would. Fail-closed is preserved.
        for cred in self._trust.list_credentials():
            creds.save(copy.deepcopy(cred))
        for r in reversed(self._trust.list_receipts(limit=10_000)):
            receipts.append(copy.deepcopy(r))
        return TrustService(
            registry=registry, credentials=creds, receipts=receipts, clock=clock
        )

    def _fork_ledger(self) -> BudgetLedger:
        live = self._ledger_store.get()
        return BudgetLedger(entries=copy.deepcopy(live.entries))

    def simulate(self, *, requester_key: str, amount: float, description: str) -> dict[str, Any]:
        """Run the real pipeline on a fork; produce the diff + rollback preview.

        Live stores are NEVER mutated (fork isolation is by deepcopy)."""
        sim_id = str(uuid.uuid4())
        before = snapshot_store(self._trust, self._ledger_store)

        fork_trust = self._fork_trust()
        fork_ledger = self._fork_ledger()
        outcome = run_purchase(
            trust=fork_trust,
            ledger=fork_ledger,
            requester_key=requester_key,
            amount=amount,
            description=description,
            reference=f"sim:{sim_id}",
        )

        # build the "after" snapshot from the FORKED stores directly (no
        # adapter imports in this layer) and diff it against the live before
        after = snapshot_parts(
            agents=fork_trust.list_agents(),
            credentials=[
                c.signed_payload() | {"signature": c.signature}
                for c in fork_trust.list_credentials()
            ],
            ledger_entries=[e.as_dict() for e in fork_ledger.entries],
            receipts=fork_trust.list_receipts(limit=10_000),
        )
        fork_diff = diff_snapshots(before, after)

        entry = outcome["ledger_entry"]
        rollback_entries = []
        if entry:
            rollback_entries.append(
                {
                    "kind": "refund",
                    "amount": entry["amount"],
                    "compensates": "<spend entry created at execution>",
                    "note": "compensating reversal — appended, never an undo/delete",
                }
            )
            rollback_entries.append(
                {
                    "kind": "revoke_authority",
                    "note": (
                        "optionally revoke the AuthorityGrant that allowed this "
                        "purchase (signed revocation via /api/trust/revoke)"
                    ),
                }
            )

        record = {
            "id": sim_id,
            "created_at": datetime.now(UTC).isoformat(),
            "intent": {
                "requester_key": requester_key,
                "action": "purchase",
                "amount": amount,
                "description": description,
            },
            "status": "pending",
            "fork_diff": fork_diff,
            "rollback_preview": {
                "strategy": "compensating_action",
                "entries": rollback_entries,
            },
            "predicted_effects": {
                "decision": outcome["decision"],
                "balance_after": fork_ledger.projected_balance(),
                "limit": self._limit,
                "scope_usage_pct": round(
                    100 * fork_ledger.projected_balance() / self._limit, 1
                ),
                "reasoning": outcome["reasoning"],
            },
            "decision_receipt_id": None,
            "post_check": None,
            "events": [{"ts": datetime.now(UTC).isoformat(), "event": "simulated"}],
        }
        self._sims.save(record)
        return record

    def get(self, sim_id: str) -> dict[str, Any] | None:
        return self._sims.get(sim_id)

    def list(self, *, limit: int = 50) -> list[dict[str, Any]]:
        return self._sims.list(limit=limit)

    # --- decide on the human's call ------------------------------------------

    def reject(self, sim_id: str) -> dict[str, Any]:
        record = self._require(sim_id)
        if record["status"] != "pending":
            raise ValueError(f"simulation {sim_id} is not pending")
        record["status"] = "rejected"
        record["events"].append({"ts": datetime.now(UTC).isoformat(), "event": "rejected"})
        self._sims.save(record)
        return record

    def execute(self, sim_id: str) -> dict[str, Any]:
        """Approve & execute: run the SAME pipeline against live stores, then
        re-check invariants. Violation → escalated + rollback offered."""
        record = self._require(sim_id)
        if record["status"] != "pending":
            raise ValueError(f"simulation {sim_id} is not pending")

        intent = record["intent"]
        outcome = run_purchase(
            trust=self._trust,
            ledger=self._ledger_store.get(),
            requester_key=intent["requester_key"],
            amount=intent["amount"],
            description=intent["description"],
            reference=f"exec:{sim_id}",
        )
        record["decision_receipt_id"] = outcome["receipt_id"]
        record["executed_entry"] = outcome["ledger_entry"]
        record["events"].append({"ts": datetime.now(UTC).isoformat(), "event": "executed"})

        # post-execution safety net: pure invariant check on live state
        violations = invariant_violations(self._ledger_store.get(), limit=self._limit)
        record["post_check"] = {
            "ok": not violations,
            "violations": violations,
            "checked_at": datetime.now(UTC).isoformat(),
        }
        if violations:
            record["status"] = "escalated"
            record["events"].append(
                {
                    "ts": datetime.now(UTC).isoformat(),
                    "event": "escalated",
                    "detail": (
                        "post-execution invariant violated: "
                        f"excess {violations[0]['excess']}"
                    ),
                }
            )
            self._audit(
                sim_id, "escalate", f"invariant violated after execution: {violations[0]}"
            )
        else:
            record["status"] = "executed"
        self._sims.save(record)
        return record

    def rollback(self, sim_id: str) -> dict[str, Any]:
        """Compensating reversal: append a refund for the executed spend and
        revoke the authority that enabled it. Append-only — no undo."""
        record = self._require(sim_id)
        if record["status"] not in ("executed", "escalated"):
            raise ValueError(f"simulation {sim_id} has no executed action to roll back")

        entry = record.get("executed_entry")
        if entry:
            self._ledger_store.get().refund(
                compensates=entry["id"],
                agent_key=record["intent"]["requester_key"],
                reference=f"rollback:{sim_id}",
            )
        # revoke the requester's purchase authority (best effort — the grant
        # may legitimately not exist, e.g. the action was refused)
        for agent in self._trust.list_agents():
            if agent["public_key"] == record["intent"]["requester_key"]:
                profile = self._trust.trust_profile(subject_key=agent["public_key"])
                for c in profile["credentials"]:
                    if c["type"] == str(CredentialType.AUTHORITY_GRANT) and c["valid"]:
                        self._trust.revoke_credential(
                            credential_id=c["id"],
                            reason=f"rollback of simulation {sim_id}",
                        )

        record["status"] = "rolled_back"
        record["post_check"] = {
            "ok": not invariant_violations(self._ledger_store.get(), limit=self._limit),
            "violations": invariant_violations(self._ledger_store.get(), limit=self._limit),
            "checked_at": datetime.now(UTC).isoformat(),
        }
        record["events"].append({"ts": datetime.now(UTC).isoformat(), "event": "rolled_back"})
        self._audit(sim_id, "rollback", f"compensating refund appended for {sim_id}")
        self._sims.save(record)
        return record

    # --- failure-test hook (real write by a separate actor) -------------------

    def place_hold(self, *, agent_key: str, amount: float, reference: str) -> dict[str, Any]:
        """A real concurrent hold on the shared budget — the side effect a
        stale simulation cannot predict. This is a genuine ledger write."""
        entry = self._ledger_store.get().hold(
            agent_key=agent_key, amount=amount, reference=reference
        )
        self._audit(None, "hold", f"concurrent hold {amount} by {agent_key[:12]}…")
        return entry.as_dict()

    # --- internals -------------------------------------------------------------

    def _require(self, sim_id: str) -> dict[str, Any]:
        record = self._sims.get(sim_id)
        if record is None:
            raise ValueError(f"unknown simulation {sim_id}")
        return record

    def _audit(self, sim_id: str | None, action: str, note: str) -> None:
        """Every simulate/execute/escalate/rollback step leaves a receipt in
        the same append-only log as C1 decisions — one forensic trail."""
        from core.trustcore.domain.policy import PolicyDecision

        self._trust.record_event(
            actor="simcore",
            action=action,
            note=note,
            inputs={"simulation_id": sim_id, "mode": "audit"},
            decision=PolicyDecision.ESCALATE if action == "escalate" else PolicyDecision.ALLOW,
        )
