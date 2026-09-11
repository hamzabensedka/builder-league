"""Seed the fleet with REAL signed credentials — the tower's demo fixture.

Mirrors the C1/C2/C8 demo pattern: fresh keypairs each run, issuers sign
client-side, the server stores only verifiable claims. Each fleet agent gets
authority scoped to exactly its job, so over-reach (the rogue scenario) is
refused by TrustCore for real.
"""

from typing import Any

from core.towercore.application.ports import AuthorityGate
from core.trustcore.domain.credentials import CredentialType
from core.trustcore.domain.crypto import KeyPair


def seed_fleet(trust: AuthorityGate) -> dict[str, Any]:
    acme = KeyPair.generate()
    keys: dict[str, str] = {}

    specs = [
        ("restockbot", "RestockBot", "Acme Supply Chain",
         {"action": "purchase", "max_amount": 500},
         {"actions": ["purchase"], "max_amount": 500}, 2),
        ("refundbot", "RefundBot", "Acme Finance",
         {"action": "issue_refund", "max_amount": 600},
         {"actions": ["issue_refund"], "max_amount": 600}, 3),
        ("deploybot", "DeployBot", "Acme Platform",
         {"action": "deploy_production"},
         {"actions": ["deploy_production"]}, 1),
    ]

    for agent_id, name, owner, claim, scope, completions in specs:
        kp = KeyPair.generate()
        trust.register_agent(name=name, public_key=kp.public_key_b64, owner=owner)
        keys[agent_id] = kp.public_key_b64
        trust.issue_credential(
            issuer=acme, subject_key=kp.public_key_b64,
            type=CredentialType.AUTHORITY_GRANT, claim=claim, scope=scope,
        )
        for _ in range(completions):
            trust.issue_credential(
                issuer=acme, subject_key=kp.public_key_b64,
                type=CredentialType.TASK_COMPLETION,
                claim={"task": f"prior {claim['action']}", "outcome": "completed"},
                scope={"actions": [claim["action"]]},
            )

    beats = [
        {"label": "Fleet enrolled: RestockBot (purchase ≤$500), RefundBot "
                  "(refund ≤$600), DeployBot (deploy, no amount scope)"},
        {"label": "Advance any agent — watch steps, costs, and decisions stream in live"},
        {"label": "Refund T-102 ($2400, missing invoice) parks in the approval queue"},
        {"label": "Deploy v12 has no change ticket → ESCALATE → approval queue"},
        {"label": "Failure test: 'Inject rogue objective' → DeployBot goes rogue, "
                  "denials burst, tower auto-pauses; replay, then KILL"},
    ]
    return {"keys": keys, "beats": beats}
