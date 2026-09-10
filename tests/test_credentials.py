"""TDD: credentials domain — VC-shaped issue/verify/revoke + scope matching.

Attack cases from the approved plan §5 are tests here: tamper, replay
(subject mismatch), expiry, revocation, scope escape. Written before
implementation (RED first).
"""

from datetime import UTC, datetime, timedelta

from core.trustcore.domain.credentials import (
    Credential,
    CredentialType,
    VerificationFailure,
    matches_scope,
    revoke,
    sign_credential,
    verify_credential,
)
from core.trustcore.domain.crypto import KeyPair

NOW = datetime(2026, 9, 11, 12, 0, 0, tzinfo=UTC)


def make_credential(
    issuer: KeyPair,
    subject: KeyPair,
    *,
    ctype: CredentialType = CredentialType.AUTHORITY_GRANT,
    claim: dict | None = None,
    scope: dict | None = None,
    expires_at: datetime | None = None,
) -> Credential:
    unsigned = Credential(
        id="cred-1",
        issuer_key=issuer.public_key_b64,
        subject_key=subject.public_key_b64,
        type=ctype,
        claim=claim if claim is not None else {"action": "purchase", "max_amount": 1000},
        scope=scope if scope is not None else {"actions": ["purchase"], "max_amount": 1000},
        issued_at=NOW,
        expires_at=expires_at if expires_at is not None else NOW + timedelta(days=30),
        revoked_at=None,
        revocation_reason=None,
        signature="",
    )
    return sign_credential(issuer, unsigned)


class TestSignAndVerify:
    def test_valid_credential_verifies(self):
        issuer, subject = KeyPair.generate(), KeyPair.generate()
        cred = make_credential(issuer, subject)
        assert verify_credential(cred, now=NOW) == []

    def test_tampered_claim_fails(self):
        issuer, subject = KeyPair.generate(), KeyPair.generate()
        cred = make_credential(issuer, subject)
        tampered = Credential(
            **{**cred.__dict__, "claim": {"action": "purchase", "max_amount": 999999}}
        )
        assert VerificationFailure.INVALID_SIGNATURE in verify_credential(tampered, now=NOW)

    def test_wrong_issuer_key_fails(self):
        issuer, subject, attacker = KeyPair.generate(), KeyPair.generate(), KeyPair.generate()
        cred = make_credential(issuer, subject)
        forged = Credential(**{**cred.__dict__, "issuer_key": attacker.public_key_b64})
        assert VerificationFailure.INVALID_SIGNATURE in verify_credential(forged, now=NOW)

    def test_expired_credential_fails(self):
        issuer, subject = KeyPair.generate(), KeyPair.generate()
        cred = make_credential(issuer, subject, expires_at=NOW - timedelta(seconds=1))
        assert VerificationFailure.EXPIRED in verify_credential(cred, now=NOW)

    def test_revoked_credential_fails(self):
        issuer, subject = KeyPair.generate(), KeyPair.generate()
        cred = make_credential(issuer, subject)
        later = NOW + timedelta(hours=2)
        revoked = revoke(cred, at=NOW + timedelta(hours=1), reason="owner revoked")
        failures = verify_credential(revoked, now=later)
        assert VerificationFailure.REVOKED in failures

    def test_signature_covers_revocation_fields(self):
        # revoking re-signs (issuer authorizes the revocation); an unsigned
        # revocation edit is just a tampered credential
        issuer, subject = KeyPair.generate(), KeyPair.generate()
        cred = make_credential(issuer, subject)
        sneaky = Credential(
            **{
                **cred.__dict__,
                "revoked_at": None,
                "claim": {"action": "purchase", "max_amount": 5},
            }
        )
        assert VerificationFailure.INVALID_SIGNATURE in verify_credential(sneaky, now=NOW)

    def test_subject_binding_is_part_of_signed_payload(self):
        # replay defense: a credential for subject A cannot verify as subject B
        issuer, subject_a, subject_b = KeyPair.generate(), KeyPair.generate(), KeyPair.generate()
        cred = make_credential(issuer, subject_a)
        replayed = Credential(**{**cred.__dict__, "subject_key": subject_b.public_key_b64})
        assert VerificationFailure.INVALID_SIGNATURE in verify_credential(replayed, now=NOW)


class TestRevoke:
    def test_revoke_records_timestamp_and_reason(self):
        issuer, subject = KeyPair.generate(), KeyPair.generate()
        cred = make_credential(issuer, subject)
        revoked = revoke(cred, at=NOW, reason="compromised")
        assert revoked.revoked_at == NOW
        assert revoked.revocation_reason == "compromised"


class TestScopeMatching:
    def test_action_in_scope_and_amount_within_limit(self):
        cred_scope = {"actions": ["purchase"], "max_amount": 1000}
        assert matches_scope(cred_scope, action="purchase", amount=800) is True

    def test_scope_escape_amount_exceeds_limit(self):
        # plan §5 attack 3: valid credential, action out of scope by amount
        cred_scope = {"actions": ["purchase"], "max_amount": 50}
        assert matches_scope(cred_scope, action="purchase", amount=800) is False

    def test_action_not_in_scope(self):
        cred_scope = {"actions": ["purchase"], "max_amount": 1000}
        assert matches_scope(cred_scope, action="deploy", amount=10) is False

    def test_no_amount_required_means_action_only(self):
        cred_scope = {"actions": ["read"]}
        assert matches_scope(cred_scope, action="read", amount=None) is True

    def test_empty_scope_matches_nothing(self):
        assert matches_scope({}, action="purchase", amount=1) is False
