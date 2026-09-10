"""W3C-VC-shaped credentials: signed claims with expiry, revocation, and scope.

Pure domain code. A Credential is an immutable value object; the signature
covers EVERY field (including revocation fields), so any mutation invalidates
the signature — tamper, replay-with-different-subject, and unsigned revocation
edits all fail as INVALID_SIGNATURE.
"""

import enum
import uuid
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from core.trustcore.domain.crypto import KeyPair, sign_payload, verify_payload


class CredentialType(enum.StrEnum):
    TASK_COMPLETION = "TaskCompletion"
    AUTHORITY_GRANT = "AuthorityGrant"
    CAPABILITY_ATTESTATION = "CapabilityAttestation"
    VOUCH = "Vouch"


class VerificationFailure(enum.StrEnum):
    INVALID_SIGNATURE = "invalid_signature"
    EXPIRED = "expired"
    REVOKED = "revoked"


@dataclass(frozen=True)
class Credential:
    id: str
    issuer_key: str          # Ed25519 public key (base64) of the issuer
    subject_key: str         # Ed25519 public key (base64) of the subject agent
    type: CredentialType
    claim: dict[str, Any]    # e.g. {"action": "purchase", "max_amount": 1000}
    scope: dict[str, Any]    # e.g. {"actions": ["purchase"], "max_amount": 1000}
    issued_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    revocation_reason: str | None
    signature: str           # Ed25519 over canonical JSON of signed_payload()

    def signed_payload(self) -> dict[str, Any]:
        """Everything the signature commits to. Signature itself excluded."""
        return {
            "id": self.id,
            "issuer_key": self.issuer_key,
            "subject_key": self.subject_key,
            "type": str(self.type),
            "claim": self.claim,
            "scope": self.scope,
            "issued_at": self.issued_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "revoked_at": self.revoked_at.isoformat() if self.revoked_at else None,
            "revocation_reason": self.revocation_reason,
        }


def new_unsigned_credential(
    *,
    issuer_key: str,
    subject_key: str,
    type: CredentialType,
    claim: dict[str, Any],
    scope: dict[str, Any],
    issued_at: datetime,
    expires_at: datetime,
) -> Credential:
    return Credential(
        id=str(uuid.uuid4()),
        issuer_key=issuer_key,
        subject_key=subject_key,
        type=type,
        claim=claim,
        scope=scope,
        issued_at=issued_at,
        expires_at=expires_at,
        revoked_at=None,
        revocation_reason=None,
        signature="",
    )


def sign_credential(issuer: KeyPair, credential: Credential) -> Credential:
    """Issuer signs the credential; returns a new immutable Credential."""
    if credential.issuer_key != issuer.public_key_b64:
        raise ValueError("issuer keypair does not match credential issuer_key")
    return replace(credential, signature=sign_payload(issuer, credential.signed_payload()))


def revoke(credential: Credential, *, at: datetime, reason: str) -> Credential:
    """Mark a credential revoked. NOTE: the signature is invalidated by this;
    the issuer must re-sign (sign_credential) for the revocation itself to be
    verifiable — an unsigned revocation edit is indistinguishable from tamper."""
    return replace(credential, revoked_at=at, revocation_reason=reason)


def verify_credential(credential: Credential, *, now: datetime) -> list[VerificationFailure]:
    """Return all verification failures; empty list means fully valid."""
    failures: list[VerificationFailure] = []
    if not verify_payload(credential.issuer_key, credential.signed_payload(), credential.signature):
        failures.append(VerificationFailure.INVALID_SIGNATURE)
    if credential.revoked_at is not None and now >= credential.revoked_at:
        failures.append(VerificationFailure.REVOKED)
    if now >= credential.expires_at:
        failures.append(VerificationFailure.EXPIRED)
    return failures


def matches_scope(scope: dict[str, Any], *, action: str, amount: float | None) -> bool:
    """Deterministic scope check. Empty scope matches nothing (fail-closed)."""
    allowed_actions = scope.get("actions") or []
    if action not in allowed_actions:
        return False
    max_amount = scope.get("max_amount")
    return not (amount is not None and max_amount is not None and amount > float(max_amount))
