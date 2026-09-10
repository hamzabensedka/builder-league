"""Canonical JSON + Ed25519 signing. Pure domain code: no I/O, no frameworks.

Security rules honored here:
- PyNaCl only; no hand-rolled crypto.
- Canonical JSON (sorted keys, UTF-8, no whitespace) before every sign/verify,
  so logically identical payloads produce byte-identical signatures.
- Fail-closed: any malformed key/signature input returns False or raises
  ValueError at construction — verification itself never raises.
"""

import base64
import binascii
import json
from dataclasses import dataclass
from typing import Any

import nacl.encoding
import nacl.signing


def canonical_json(payload: dict[str, Any]) -> str:
    """Deterministic serialization: sorted keys recursively, no whitespace, UTF-8."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _b64encode(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.b64decode(value.encode("ascii"), validate=True)


@dataclass(frozen=True)
class KeyPair:
    """An Ed25519 keypair. The private half never leaves this object."""

    _signing_key: nacl.signing.SigningKey

    @classmethod
    def generate(cls) -> "KeyPair":
        return cls(nacl.signing.SigningKey.generate())

    @classmethod
    def from_private_b64(cls, private_b64: str) -> "KeyPair":
        try:
            raw = _b64decode(private_b64)
            return cls(nacl.signing.SigningKey(raw))
        except (binascii.Error, nacl.exceptions.ValueError) as exc:
            raise ValueError("invalid Ed25519 private key encoding") from exc

    @property
    def public_key_b64(self) -> str:
        return _b64encode(bytes(self._signing_key.verify_key))

    @property
    def private_key_b64(self) -> str:
        return _b64encode(bytes(self._signing_key))


def sign_payload(keypair: KeyPair, payload: dict[str, Any]) -> str:
    """Sign the canonical form of payload; return base64 signature."""
    message = canonical_json(payload).encode("utf-8")
    signed = keypair._signing_key.sign(message)
    return _b64encode(signed.signature)


def verify_payload(public_key_b64: str, payload: dict[str, Any], signature_b64: str) -> bool:
    """Fail-closed verification: any malformed input or mismatch returns False."""
    try:
        verify_key = nacl.signing.VerifyKey(_b64decode(public_key_b64))
        message = canonical_json(payload).encode("utf-8")
        verify_key.verify(message, _b64decode(signature_b64))
        return True
    except (binascii.Error, nacl.exceptions.BadSignatureError, nacl.exceptions.ValueError):
        return False
