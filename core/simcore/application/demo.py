"""The C8 one-click demo scenario, as an application service.

Seeds a fresh buyer with real signed authority + history, then returns the
keys and a narration so the UI can drive the simulate → review → execute →
(fail) → rollback cycle live. Mirrors C1's run_demo_scenario pattern.
"""

from typing import Any

from core.simcore.application.services import SimService
from core.trustcore.domain.credentials import CredentialType
from core.trustcore.domain.crypto import KeyPair


def run_sim_demo(sim: SimService) -> dict[str, Any]:
    """Seed the world for the simulate-before-you-act demo. Safe to re-click:
    fresh keypairs each run. Returns keys + seeded facts for the UI."""
    trust = sim._trust  # noqa: SLF001 — demo is same-layer application code

    acme, buyer, vendor = KeyPair.generate(), KeyPair.generate(), KeyPair.generate()
    trust.register_agent(name="BuyerBot", public_key=buyer.public_key_b64, owner="Acme")
    trust.register_agent(name="VendorBot", public_key=vendor.public_key_b64, owner="Vendor Inc")

    trust.issue_credential(
        issuer=acme,
        subject_key=buyer.public_key_b64,
        type=CredentialType.AUTHORITY_GRANT,
        claim={"action": "purchase", "max_amount": 1000},
        scope={"actions": ["purchase"], "max_amount": 1000},
    )
    trust.issue_credential(
        issuer=vendor,
        subject_key=buyer.public_key_b64,
        type=CredentialType.TASK_COMPLETION,
        claim={"task": "prior purchase", "outcome": "completed"},
        scope={"actions": ["purchase"]},
    )

    beats = [
        {"label": "Seeded BuyerBot with $1,000 purchase authority (signed by Acme) + 1 completion"},
        {"label": "Next: click 'Simulate purchase' — the approval screen is the before/after diff"},
        {"label": "Then 'Inject concurrent hold' before approving to trigger the failure test"},
    ]
    return {
        "buyer_key": buyer.public_key_b64,
        "vendor_key": vendor.public_key_b64,
        "limit": sim._limit,  # noqa: SLF001
        "beats": beats,
    }
