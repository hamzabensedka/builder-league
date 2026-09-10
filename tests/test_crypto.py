"""TDD: crypto domain module — canonical JSON + Ed25519 sign/verify.

These tests define the contract for core.trustcore.domain.crypto.
Written before any implementation exists (RED first).
"""

import pytest

from core.trustcore.domain.crypto import (
    KeyPair,
    canonical_json,
    sign_payload,
    verify_payload,
)


class TestCanonicalJson:
    def test_key_order_is_irrelevant(self):
        a = {"b": 1, "a": 2}
        b = {"a": 2, "b": 1}
        assert canonical_json(a) == canonical_json(b)

    def test_nested_objects_and_arrays_are_canonical(self):
        payload = {"z": [{"y": 1, "x": 2}], "a": {"c": 3, "b": 4}}
        result = canonical_json(payload)
        # outer keys sorted: a before z; inner keys sorted too
        assert result == '{"a":{"b":4,"c":3},"z":[{"x":2,"y":1}]}'

    def test_no_whitespace_and_utf8(self):
        payload = {"msg": "café — 100€"}
        result = canonical_json(payload)
        assert " " not in result.split(":", 1)[0]  # no space after key
        assert "café" in result  # UTF-8 preserved, not escaped to <E9>

    def test_whitespace_inside_strings_is_preserved(self):
        assert canonical_json({"a": "x y"}) == '{"a":"x y"}'


class TestSignVerify:
    def test_roundtrip(self):
        kp = KeyPair.generate()
        payload = {"action": "purchase", "max_amount": 1000}
        sig = sign_payload(kp, payload)
        assert verify_payload(kp.public_key_b64, payload, sig) is True

    def test_tampered_payload_fails_verification(self):
        kp = KeyPair.generate()
        payload = {"action": "purchase", "max_amount": 1000}
        sig = sign_payload(kp, payload)
        tampered = {"action": "purchase", "max_amount": 999999}
        assert verify_payload(kp.public_key_b64, tampered, sig) is False

    def test_wrong_key_fails_verification(self):
        signer = KeyPair.generate()
        attacker = KeyPair.generate()
        payload = {"claim": "i am acme"}
        sig = sign_payload(signer, payload)
        assert verify_payload(attacker.public_key_b64, payload, sig) is False

    def test_garbage_signature_fails_closed_not_exception(self):
        kp = KeyPair.generate()
        # fail-closed: malformed signature must return False, never raise
        assert verify_payload(kp.public_key_b64, {"a": 1}, "not-a-real-sig") is False

    def test_garbage_public_key_fails_closed(self):
        kp = KeyPair.generate()
        payload = {"a": 1}
        sig = sign_payload(kp, payload)
        assert verify_payload("bogus-key", payload, sig) is False

    def test_keypair_serializes_and_restores(self):
        kp = KeyPair.generate()
        restored = KeyPair.from_private_b64(kp.private_key_b64)
        assert restored.public_key_b64 == kp.public_key_b64

    def test_sign_is_deterministic_for_same_payload(self):
        # canonical JSON means the same logical payload signs identically
        kp = KeyPair.generate()
        sig_a = sign_payload(kp, {"b": 1, "a": 2})
        sig_b = sign_payload(kp, {"a": 2, "b": 1})
        assert sig_a == sig_b


class TestKeyPairGuards:
    def test_from_private_b64_rejects_garbage(self):
        with pytest.raises(ValueError):
            KeyPair.from_private_b64("definitely-not-a-key")
