"""The C2 one-click demo scenario, as an application service.

Seeds three agents (one per domain) with real signed credentials and a track
record, then returns the keys and narrated beats so the UI can drive the
decision console live. Mirrors the C1/C8 demo pattern. Safe to re-click:
fresh keypairs each run.
"""

from typing import Any

from core.trustcore.application.services import TrustService
from core.trustcore.domain.credentials import CredentialType
from core.trustcore.domain.crypto import KeyPair


def run_decision_demo(trust: TrustService) -> dict[str, Any]:
    """Seed the world for the decision-engine demo. Returns keys + beats."""
    acme = KeyPair.generate()
    triage, deploy, mod = KeyPair.generate(), KeyPair.generate(), KeyPair.generate()

    for name, kp, owner in [
        ("TriageBot", triage, "Acme Support"),
        ("DeployBot", deploy, "Acme Platform"),
        ("ModBot", mod, "Acme Trust&Safety"),
    ]:
        trust.register_agent(name=name, public_key=kp.public_key_b64, owner=owner)

    # TriageBot: refund authority ≤ $600 + a track record of 3 completions
    trust.issue_credential(
        issuer=acme,
        subject_key=triage.public_key_b64,
        type=CredentialType.AUTHORITY_GRANT,
        claim={"action": "issue_refund", "max_amount": 600},
        scope={"actions": ["issue_refund"], "max_amount": 600},
    )
    for _ in range(3):
        trust.issue_credential(
            issuer=acme,
            subject_key=triage.public_key_b64,
            type=CredentialType.TASK_COMPLETION,
            claim={"task": "prior refund", "outcome": "completed"},
            scope={"actions": ["issue_refund"]},
        )

    # DeployBot: deploy authority, but only 1 completion (thinner record)
    trust.issue_credential(
        issuer=acme,
        subject_key=deploy.public_key_b64,
        type=CredentialType.AUTHORITY_GRANT,
        claim={"action": "deploy_production"},
        scope={"actions": ["deploy_production"]},
    )
    trust.issue_credential(
        issuer=acme,
        subject_key=deploy.public_key_b64,
        type=CredentialType.TASK_COMPLETION,
        claim={"task": "staging deploy", "outcome": "completed"},
        scope={"actions": ["deploy_production"]},
    )

    # ModBot: moderation authority + 2 completions
    trust.issue_credential(
        issuer=acme,
        subject_key=mod.public_key_b64,
        type=CredentialType.AUTHORITY_GRANT,
        claim={"action": "remove_content"},
        scope={"actions": ["remove_content"]},
    )
    for _ in range(2):
        trust.issue_credential(
            issuer=acme,
            subject_key=mod.public_key_b64,
            type=CredentialType.TASK_COMPLETION,
            claim={"task": "prior removal", "outcome": "completed"},
            scope={"actions": ["remove_content"]},
        )

    beats = [
        {"label": "Seeded TriageBot (refund ≤$600, 3 completions), "
                  "DeployBot (deploy, 1), ModBot (moderate, 2)"},
        {"label": "Try: refund $120 with invoice_id + reason → EXECUTE"},
        {"label": "Try: refund $2400 missing invoice_id → ASK (names the missing field)"},
        {"label": "Try: deploy_production blast $8000, missing change_ticket "
                  "→ ASK/ESCALATE (never execute)"},
        {"label": "Try: same deploy with a forged/absent authority → REFUSE"},
    ]
    return {
        "triage_key": triage.public_key_b64,
        "deploy_key": deploy.public_key_b64,
        "mod_key": mod.public_key_b64,
        "beats": beats,
    }
