"""Use-case services: IssueCredential, RevokeCredential, DecideTask, TrustProfile.

Orchestrate domain logic through ports. No framework imports, no I/O details.
Every decision appends a Receipt (append-only audit).
"""

import uuid
from typing import Any

from core.trustcore.application.ports import (
    AgentRegistry,
    Clock,
    CredentialStore,
    Receipt,
    ReceiptLog,
)
from core.trustcore.domain.credentials import (
    Credential,
    CredentialType,
    matches_scope,
    new_unsigned_credential,
    sign_credential,
    verify_credential,
)
from core.trustcore.domain.crypto import KeyPair
from core.trustcore.domain.policy import PolicyDecision, evaluate


class TrustService:
    def __init__(
        self,
        *,
        registry: AgentRegistry,
        credentials: CredentialStore,
        receipts: ReceiptLog,
        clock: Clock,
    ) -> None:
        self._registry = registry
        self._credentials = credentials
        self._receipts = receipts
        self._clock = clock

    # --- identity ---------------------------------------------------------

    def register_agent(self, *, name: str, public_key: str, owner: str) -> str:
        return self._registry.register(name=name, public_key=public_key, owner=owner)

    # --- credentials --------------------------------------------------------

    def issue_credential(
        self,
        *,
        issuer: KeyPair,
        subject_key: str,
        type: CredentialType,
        claim: dict[str, Any],
        scope: dict[str, Any],
        ttl_days: int = 30,
    ) -> Credential:
        now = self._clock.now()
        from datetime import timedelta

        unsigned = new_unsigned_credential(
            issuer_key=issuer.public_key_b64,
            subject_key=subject_key,
            type=type,
            claim=claim,
            scope=scope,
            issued_at=now,
            expires_at=now + timedelta(days=ttl_days),
        )
        cred = sign_credential(issuer, unsigned)
        self._credentials.save(cred)
        return cred

    def register_signed_credential(self, credential: Credential) -> Credential:
        """Store a credential signed client-side. Signature is verified at the
        boundary — the service never trusts an unverifiable claim."""
        from core.trustcore.domain.credentials import VerificationFailure

        failures = verify_credential(credential, now=self._clock.now())
        if VerificationFailure.INVALID_SIGNATURE in failures:
            raise ValueError("credential signature does not verify")
        self._credentials.save(credential)
        return credential

    def get_credential(self, credential_id: str) -> Credential | None:
        return self._credentials.get(credential_id)

    def list_credentials(self) -> list[Credential]:
        """All stored credentials (read-only). Added for SimCore's fork: a
        simulation must deep-copy the REAL signed credentials, not lossy
        reconstructions — verification is fail-closed on bad signatures."""
        seen: dict[str, Credential] = {}
        for agent in self.list_agents():
            for c in self._credentials.for_subject(agent["public_key"]):
                seen[c.id] = c
        return list(seen.values())

    def revoke_credential(
        self, *, credential_id: str, reason: str, resigned: "Credential | None" = None
    ) -> None:
        """Revoke. If `resigned` (issuer re-signed revoked credential) is given,
        store it so the revoked credential stays verifiable; otherwise mark
        revoked directly (verification will then report invalid+revoked —
        still refuses, fail-closed, just a less clean signal)."""
        from dataclasses import replace

        cred = self._credentials.get(credential_id)
        if cred is None:
            raise ValueError(f"unknown credential {credential_id}")
        if resigned is not None:
            self._credentials.save(resigned)
        else:
            revoked = replace(cred, revoked_at=self._clock.now(), revocation_reason=reason)
            self._credentials.save(revoked)

    def list_agents(self) -> list[dict[str, Any]]:
        return self._registry.list_agents()

    def find_agent_id(self, public_key: str) -> str | None:
        """Public lookup used by DecisionCore's history signal to match an
        actor's decision receipts (receipts store agent_id, not the key)."""
        return self._registry.find_by_key(public_key)

    # --- the trust-gated decision -------------------------------------------

    def decide(
        self,
        *,
        requester_key: str,
        action: str,
        amount: float | None,
        description: str = "",
    ) -> Receipt:
        """Verify requester's credentials and allow/refuse/escalate. Always receipts."""
        now = self._clock.now()
        creds = self._credentials.for_subject(requester_key)

        valid_authority: list[dict[str, Any]] = []
        valid_completions = 0
        failures: list[dict[str, Any]] = []
        for c in creds:
            problems = verify_credential(c, now=now)
            if problems:
                failures.append({"credential_id": c.id, "failures": [str(p) for p in problems]})
                continue
            if c.type == CredentialType.AUTHORITY_GRANT:
                valid_authority.append({"id": c.id, "scope": c.scope})
            elif c.type == CredentialType.TASK_COMPLETION:
                valid_completions += 1

        result = evaluate(
            action=action,
            amount=amount,
            valid_authority_claims=valid_authority,
            valid_completion_count=valid_completions,
        )

        # Refusal reasoning: lead with the POLICY reason (why the action itself
        # was refused — e.g. no authority claim covers this action/amount). Only
        # when the policy produced no reason do we surface a suspicious-material
        # failure. We still append failing-credential detail for the audit trail,
        # but a stale forged credential on record must never mask the real,
        # primary reason for THIS refusal.
        reasoning = "; ".join(result.reasons)
        if failures and result.decision == PolicyDecision.REFUSE:
            failure_note = "; ".join(
                f"credential {f['credential_id']}: {', '.join(f['failures'])}" for f in failures
            )
            reasoning = f"{reasoning} ({failure_note})" if reasoning else failure_note

        receipt = Receipt(
            id=str(uuid.uuid4()),
            ts=now,
            agent_id=self._registry.find_by_key(requester_key) or "unregistered",
            action=action,
            inputs={"requester_key": requester_key, "amount": amount, "description": description},
            signals={
                "credentials_checked": len(creds),
                "valid_authority": len(valid_authority),
                "valid_completions": valid_completions,
                "failures": failures,
            },
            decision=result.decision,
            reasoning=reasoning,
            llm_called=False,
        )
        self._receipts.append(receipt)
        return receipt

    # --- read side (inspector UI) ---------------------------------------------

    def trust_profile(self, *, subject_key: str) -> dict[str, Any]:
        """Every number traceable to a signed claim. NO aggregate score."""
        now = self._clock.now()
        creds = self._credentials.for_subject(subject_key)
        profile_creds = []
        for c in creds:
            problems = verify_credential(c, now=now)
            profile_creds.append(
                {
                    "id": c.id,
                    "type": str(c.type),
                    "issuer_key": c.issuer_key,
                    "claim": c.claim,
                    "scope": c.scope,
                    "issued_at": c.issued_at.isoformat(),
                    "expires_at": c.expires_at.isoformat(),
                    "revoked_at": c.revoked_at.isoformat() if c.revoked_at else None,
                    "valid": not problems,
                    "failures": [str(p) for p in problems],
                }
            )
        return {
            "subject_key": subject_key,
            "credentials": profile_creds,
            "counts": {
                "valid_authority_grants": sum(
                    1
                    for c in profile_creds
                    if c["valid"] and c["type"] == str(CredentialType.AUTHORITY_GRANT)
                ),
                "valid_completions": sum(
                    1
                    for c in profile_creds
                    if c["valid"] and c["type"] == str(CredentialType.TASK_COMPLETION)
                ),
                "invalid_or_revoked": sum(1 for c in profile_creds if not c["valid"]),
            },
        }

    def list_receipts(self, *, limit: int = 50) -> list[Receipt]:
        return self._receipts.list(limit=limit)

    def record_event(
        self,
        *,
        actor: str,
        action: str,
        note: str,
        inputs: dict[str, Any] | None = None,
        decision: PolicyDecision = PolicyDecision.ALLOW,
    ) -> Receipt:
        """Append an audit receipt for a NON-decision event (e.g. SimCore's
        escalate/rollback steps). Keeps one append-only forensic trail across
        modules without exposing the receipt store itself."""
        receipt = Receipt(
            id=str(uuid.uuid4()),
            ts=self._clock.now(),
            agent_id=actor,
            action=action,
            inputs=inputs or {},
            signals={},
            decision=decision,
            reasoning=note,
            llm_called=False,
        )
        self._receipts.append(receipt)
        return receipt

    def scope_check(self, credential: Credential, *, action: str, amount: float | None) -> bool:
        return matches_scope(credential.scope, action=action, amount=amount)
