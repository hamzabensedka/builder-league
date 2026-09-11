"""MemoryService: the write, retrieval, and forgetting paths.

Composes TrustCore for two things, through its public application surface:
- revocations are signature-verified (fail-closed) — a forget request must be
  signed by the user it claims to come from;
- every learn / recall / forget appends a receipt to the SAME append-only
  audit log the other cores use (llm_called=False).

No LLM anywhere. The honesty mechanics (confidence, decay, contradiction,
tombstones) are deterministic domain code.
"""

from dataclasses import replace
from typing import Any

from core.memorycore.application.ports import Clock, MemoryStore, TombstoneLog
from core.memorycore.domain.contradiction import ConflictOutcome, resolve_conflict
from core.memorycore.domain.facts import Fact, Provenance, SourceKind, make_fact
from core.memorycore.domain.forgetting import (
    ForgetReason,
    Tombstone,
    cascaded_forgets,
    stale_facts,
)
from core.memorycore.domain.recall import ACT_THRESHOLD, RecallResult, recall
from core.trustcore.application.services import TrustService
from core.trustcore.domain.crypto import verify_payload


class MemoryService:
    def __init__(
        self,
        *,
        store: MemoryStore,
        tombstones: TombstoneLog,
        clock: Clock,
        trust: TrustService,
    ) -> None:
        self._store = store
        self._tombstones = tombstones
        self._clock = clock
        self._trust = trust

    # ------------------------------------------------------------ write path

    def learn(
        self,
        *,
        slot: str,
        value: str,
        source: str,
        kind: SourceKind | str,
        extraction_confidence: float,
        user_id: str,
        agent_id: str,
        task_id: str | None = None,
        ttl_days: int | None = None,
        derived_from: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        """Learn a fact. Same-slot conflicts go through contradiction
        resolution: corroborate, supersede, reject, or flag both."""
        now = self._clock.now()
        fact = make_fact(
            slot=slot,
            value=value,
            provenance=Provenance(
                source=source,
                kind=SourceKind(kind),
                extraction_confidence=extraction_confidence,
            ),
            user_id=user_id,
            agent_id=agent_id,
            task_id=task_id,
            ttl_days=ttl_days,
            learned_at=now,
            derived_from=derived_from,
        )

        forgotten = self._tombstones.reasons()
        existing = [
            f
            for f in self._store.by_slot(user_id=user_id, agent_id=agent_id, slot=slot)
            if f.id not in forgotten
        ]

        outcome: dict[str, Any] = {"outcome": "stored", "fact_id": fact.id}
        if existing:
            # conflict against the strongest live claimant of this slot
            champion = max(existing, key=lambda f: f.effective_confidence(now))
            resolution = resolve_conflict(existing=champion, incoming=fact, now=now)
            outcome["outcome"] = str(resolution.outcome)
            outcome["reason"] = resolution.reason
            if resolution.outcome == ConflictOutcome.CORROBORATE:
                boosted = replace(champion, corroborations=champion.corroborations + 1)
                self._store.save(boosted)
                outcome["fact_id"] = champion.id
                fact = None  # incoming not stored separately
            elif resolution.outcome == ConflictOutcome.SUPERSEDE:
                self._tombstone(champion, ForgetReason.SUPERSEDED, resolution.reason)
                self._store.save(fact)
            elif resolution.outcome == ConflictOutcome.REJECT_INCOMING:
                self._tombstone(fact, ForgetReason.SUPERSEDED, resolution.reason)
                outcome["fact_id"] = champion.id
                fact = None
            else:  # CONTRADICTION — neither trusted
                self._tombstone(champion, ForgetReason.CONTRADICTED, resolution.reason)
                self._tombstone(fact, ForgetReason.CONTRADICTED, resolution.reason)
                outcome["fact_id"] = None
                fact = None
        else:
            self._store.save(fact)

        self._trust.record_event(
            actor=agent_id,
            action="memory.learn",
            note=f"slot={slot} outcome={outcome['outcome']}",
            inputs={
                "slot": slot,
                "value": value,
                "source": source,
                "kind": str(SourceKind(kind)),
                "user_id": user_id,
                "outcome": outcome["outcome"],
            },
        )
        return outcome

    # -------------------------------------------------------- retrieval path

    def recall(
        self,
        *,
        query: str,
        user_id: str,
        agent_id: str,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        """Retrieve with a reliance receipt: what it's relying on, how sure it
        is, and what it doesn't know. The 'I might be wrong' moment lives in
        the `verdict` field."""
        now = self._clock.now()
        result: RecallResult = recall(
            self._store.all(),
            query=query,
            user_id=user_id,
            agent_id=agent_id,
            task_id=task_id,
            now=now,
            tombstones=self._tombstones.reasons(),
        )
        receipt = result.reliance_receipt(now)
        verdict = (
            "confident"
            if result.sure
            else ("unsure" if result.facts else "unknown")
        )
        receipt["verdict"] = verdict
        receipt["threshold"] = ACT_THRESHOLD
        self._trust.record_event(
            actor=agent_id,
            action="memory.recall",
            note=f"query={query!r} verdict={verdict} "
                 f"conf={result.calibrated_confidence:.2f}",
            inputs={
                "query": query,
                "user_id": user_id,
                "verdict": verdict,
                "relied_on": [r["fact_id"] for r in receipt["relied_on"]],
            },
        )
        return receipt

    # -------------------------------------------------------- forgetting path

    def forget(
        self,
        *,
        fact_id: str,
        user_key: str,
        signature: str,
        reason: str = "user revoked",
    ) -> dict[str, Any]:
        """User revocation. FAIL-CLOSED: the request must be signed by the
        user's key over the exact payload {fact_id, reason}. Cascades to
        derived facts. Returns the tombstones written."""
        payload = {"fact_id": fact_id, "reason": reason}
        if not verify_payload(user_key, payload, signature):
            raise ValueError("invalid revocation signature — forget request refused")

        fact = self._store.get(fact_id)
        if fact is None:
            raise ValueError(f"unknown fact {fact_id}")
        doomed = cascaded_forgets(fact_id, self._store.all())
        written = []
        for fid in sorted(doomed):
            f = self._store.get(fid)
            if f is None or fid in self._tombstones.reasons():
                continue
            detail = reason if fid == fact_id else f"derived from revoked fact {fact_id}"
            written.append(self._tombstone(f, ForgetReason.REVOKED, detail).as_dict())
        self._trust.record_event(
            actor=fact.agent_id,
            action="memory.forget",
            note=f"revoked {len(written)} fact(s): {reason}",
            inputs={"fact_id": fact_id, "cascaded": len(written), "user_id": fact.user_id},
        )
        return {"forgotten": written}

    def sweep(self) -> dict[str, Any]:
        """Staleness pass: tombstone TTL-expired and decayed-below-floor facts.
        Explicit forgetting — the sweeper names every fact it kills."""
        now = self._clock.now()
        forgotten = self._tombstones.reasons()
        written = []
        for f in stale_facts(self._store.all(), now=now):
            if f.id in forgotten:
                continue
            detail = (
                "TTL expired"
                if f.is_expired(now)
                else f"decayed to {f.effective_confidence(now):.3f} below usefulness floor"
            )
            written.append(self._tombstone(f, ForgetReason.STALE, detail).as_dict())
        if written:
            self._trust.record_event(
                actor="memorycore",
                action="memory.sweep",
                note=f"swept {len(written)} stale fact(s)",
                inputs={"fact_ids": [w["fact_id"] for w in written]},
            )
        return {"swept": written}

    # ------------------------------------------------------------- read side

    def inspect(self, *, user_id: str, agent_id: str) -> dict[str, Any]:
        """'What do you remember about me?' — every live fact with its tags,
        plus the tombstones showing what was forgotten and why."""
        now = self._clock.now()
        forgotten = self._tombstones.reasons()
        live = [
            f.as_dict(now)
            for f in self._store.all()
            if f.user_id == user_id and f.agent_id == agent_id and f.id not in forgotten
        ]
        live.sort(key=lambda d: (-d["effective_confidence"], d["slot"]))
        tombs = [
            t.as_dict()
            for t in self._tombstones.list(limit=200)
            if (self._store.get(t.fact_id) is not None
                and self._store.get(t.fact_id).user_id == user_id)
        ]
        return {
            "user_id": user_id,
            "agent_id": agent_id,
            "facts": live,
            "tombstones": tombs,
            "now": now.isoformat(),
        }

    def list_events(self, *, limit: int = 100) -> dict[str, Any]:
        return {"tombstones": [t.as_dict() for t in self._tombstones.list(limit=limit)]}

    # ---------------------------------------------------------------- helpers

    def _tombstone(self, fact: Fact, reason: ForgetReason, detail: str) -> Tombstone:
        ts = Tombstone(
            fact_id=fact.id,
            slot=fact.slot,
            value=fact.value,
            reason=reason,
            forgotten_at=self._clock.now(),
            detail=detail,
        )
        self._tombstones.append(ts)
        return ts
