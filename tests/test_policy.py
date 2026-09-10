"""TDD: policy domain — allow/refuse/escalate from verified claims. No LLM."""

from core.trustcore.domain.policy import PolicyDecision, evaluate

CLAIM = {"id": "c1", "scope": {"actions": ["purchase"], "max_amount": 1000}}


def decide(action, amount, claims, completions):
    return evaluate(
        action=action,
        amount=amount,
        valid_authority_claims=claims,
        valid_completion_count=completions,
    )


class TestRefuse:
    def test_no_authority_claim_refuses(self):
        result = decide("purchase", 100, [], 5)
        assert result.decision == PolicyDecision.REFUSE

    def test_scope_escape_refuses(self):
        result = decide("purchase", 5000, [CLAIM], 5)
        assert result.decision == PolicyDecision.REFUSE

    def test_wrong_action_refuses(self):
        result = decide("deploy", 100, [CLAIM], 5)
        assert result.decision == PolicyDecision.REFUSE


class TestAllow:
    def test_authority_plus_history_allows(self):
        result = decide("purchase", 800, [CLAIM], 2)
        assert result.decision == PolicyDecision.ALLOW
        assert any("c1" in r for r in result.reasons)

    def test_amount_at_limit_allows(self):
        result = decide("purchase", 1000, [CLAIM], 1)
        assert result.decision == PolicyDecision.ALLOW


class TestEscalate:
    def test_valid_authority_but_zero_history_escalates(self):
        result = decide("purchase", 800, [CLAIM], 0)
        assert result.decision == PolicyDecision.ESCALATE


class TestNoLlm:
    def test_evaluation_is_pure_function_no_io(self):
        # same inputs -> same outputs, twice; nothing hidden in between
        a = decide("purchase", 1, [CLAIM], 1)
        b = decide("purchase", 1, [CLAIM], 1)
        assert a == b
