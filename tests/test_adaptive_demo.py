"""A10 (demo): one-click seed is re-runnable and produces real authority."""

from core.adaptivecore.application.demo import run_adaptive_demo
from core.trustcore.adapters.memory import (
    InMemoryAgentRegistry,
    InMemoryCredentialStore,
    InMemoryReceiptLog,
    SystemClock,
)
from core.trustcore.application.services import TrustService


def _trust():
    return TrustService(registry=InMemoryAgentRegistry(),
                        credentials=InMemoryCredentialStore(),
                        receipts=InMemoryReceiptLog(), clock=SystemClock())


def test_demo_seeds_real_signed_authority():
    trust = _trust()
    result = run_adaptive_demo(trust)
    profile = trust.trust_profile(subject_key=result["agent_key"])
    counts = profile["counts"]
    assert counts["valid_authority_grants"] == 1
    assert counts["valid_completions"] == 4
    # authority covers purchases up to $1,000
    grant = next(c for c in profile["credentials"] if c["type"] == "AuthorityGrant")
    assert grant["scope"]["max_amount"] == 1000
    assert "purchase" in grant["scope"]["actions"]


def test_demo_is_reclickable_fresh_keys():
    trust = _trust()
    r1 = run_adaptive_demo(trust)
    r2 = run_adaptive_demo(trust)
    assert r1["agent_key"] != r2["agent_key"]
    assert trust.trust_profile(subject_key=r2["agent_key"])["counts"]["valid_authority_grants"] == 1


def test_demo_beats_narrate_the_scenarios():
    result = run_adaptive_demo(_trust())
    labels = " ".join(b["label"] for b in result["beats"])
    assert "RestockBot" in labels
    assert "price spike" in labels
    assert "failure test" in labels
