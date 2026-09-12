import httpx

from core.companycore.adapters.llm import OpenRouterChief
from core.companycore.adapters.memory import ScriptedLLM


def test_no_key_falls_back_to_scripted():
    chief = OpenRouterChief(api_key=None, fallback=ScriptedLLM())
    text, brain = chief.propose({"kpis": {"runway_days": 10}})
    assert brain == "scripted"
    assert "freeze_spend" in text


def test_http_error_falls_back(monkeypatch):
    def boom(*a, **k):
        raise httpx.ConnectError("no network")

    monkeypatch.setattr(httpx, "post", boom)
    chief = OpenRouterChief(api_key="sk-test", fallback=ScriptedLLM())
    text, brain = chief.propose({"kpis": {"runway_days": 50}})
    assert brain == "scripted"


def test_success_returns_llm_brain(monkeypatch):
    class Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content":
                '{"action":"accelerate_collections","target":"AR","amount_cap":null,'
                '"rationale":"tighten cash"}'}}]}

    monkeypatch.setattr(httpx, "post", lambda *a, **k: Resp())
    chief = OpenRouterChief(api_key="sk-test", fallback=ScriptedLLM())
    text, brain = chief.propose({"kpis": {"runway_days": 50}})
    assert brain == "llm"
    assert "accelerate_collections" in text
