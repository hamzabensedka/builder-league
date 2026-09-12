"""TDD: the OpenRouter narrator. Propose-only, single line, parsed through a
deterministic choke point. Any failure degrades to the scripted fallback."""

from core.ambientcore.adapters.llm import OpenRouterNarrator, parse_rationale
from core.ambientcore.adapters.memory import ScriptedNarrator

HYP = {"kind": "deploy_needs_review", "target": "deploybot", "confidence": 0.8,
       "evidence": ["approval_requested: deploy_production ($1200)"], "demoted": False}


def test_no_key_falls_back_to_scripted():
    n = OpenRouterNarrator(api_key=None, fallback=ScriptedNarrator())
    line, brain = n.narrate(HYP)
    assert brain == "scripted"
    assert "parked" in line or "decision" in line


def test_http_error_falls_back(monkeypatch):
    import httpx

    def boom(*a, **k):
        raise httpx.ConnectError("no network")

    monkeypatch.setattr(httpx, "post", boom)
    n = OpenRouterNarrator(api_key="sk-test", fallback=ScriptedNarrator())
    line, brain = n.narrate(HYP)
    assert brain == "scripted"


def test_success_returns_llm_brain(monkeypatch):
    import httpx

    class Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content":
                "v12 carries no change ticket — review the diff before it ships."}}]}

    monkeypatch.setattr(httpx, "post", lambda *a, **k: Resp())
    n = OpenRouterNarrator(api_key="sk-test", fallback=ScriptedNarrator())
    line, brain = n.narrate(HYP)
    assert brain == "llm"
    assert "v12" in line


def test_choke_point_strips_multiline_and_garbage():
    # the narrator's output is parsed to ONE line, bounded length, never raises
    assert parse_rationale("line one\nline two") == "line one"
    assert parse_rationale("") == "This looks like it needs a decision."
    assert len(parse_rationale("x" * 900)) <= 300
    # whitespace-only content degrades to the default line
    assert parse_rationale("   \n  ") == "This looks like it needs a decision."


def test_choke_point_on_llm_output_integration(monkeypatch):
    import httpx

    class Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "first\nsecond\nthird"}}]}

    monkeypatch.setattr(httpx, "post", lambda *a, **k: Resp())
    n = OpenRouterNarrator(api_key="sk-test", fallback=ScriptedNarrator())
    line, brain = n.narrate(HYP)
    assert brain == "llm"
    assert line == "first"
