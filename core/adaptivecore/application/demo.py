"""The C3 one-click demo seed, as an application service.

Seeds RestockBot with real signed authority (purchase ≤ $1,000) plus a track
record, through the same TrustService surface as the C1/C2/C8 demos. Safe to
re-click: fresh keypairs each run. Returns keys + narrated beats for the UI.
"""

from typing import Any

from core.trustcore.application.services import TrustService
from core.trustcore.domain.credentials import CredentialType
from core.trustcore.domain.crypto import KeyPair


def run_adaptive_demo(trust: TrustService) -> dict[str, Any]:
    """Seed the world for the adaptive-agent demo."""
    acme = KeyPair.generate()
    restock = KeyPair.generate()
    trust.register_agent(name="RestockBot", public_key=restock.public_key_b64,
                         owner="Acme Ops")

    trust.issue_credential(
        issuer=acme,
        subject_key=restock.public_key_b64,
        type=CredentialType.AUTHORITY_GRANT,
        claim={"action": "purchase", "max_amount": 1000},
        scope={"actions": ["purchase"], "max_amount": 1000},
    )
    for _ in range(4):
        trust.issue_credential(
            issuer=acme,
            subject_key=restock.public_key_b64,
            type=CredentialType.TASK_COMPLETION,
            claim={"task": "prior restock", "outcome": "completed"},
            scope={"actions": ["purchase"]},
        )

    beats = [
        {"label": "Seeded RestockBot with $1,000 signed purchase authority + 4 completions"},
        {"label": "Pick scenario A (price spike) → run adaptive + baseline side by side"},
        {"label": "Inject the spike mid-run: watch the contradiction fire, the "
                  "'I changed my mind because…' trace, and the revised plan — while the "
                  "blind baseline over-commits past the $1,000 budget (it never sees the event)"},
        {"label": "Scenario C is the failure test: flap the price and watch damping "
                  "contain the oscillation — escalation to a human, receipted"},
    ]
    return {
        "agent_key": restock.public_key_b64,
        "beats": beats,
    }
