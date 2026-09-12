"""OpenRouter narrator. Propose-only: it writes the card's ONE-LINE rationale
and nothing else. Output passes a deterministic choke point (parse_rationale)
before it can touch a card. Any failure degrades to the scripted fallback, so
clean clones run fully offline and the inference path stays model-free."""

import os
from typing import Any

import httpx

from core.ambientcore.adapters.memory import ScriptedNarrator

DEFAULT_LINE = "This looks like it needs a decision."

PROMPT = (
    "You are the narrator of an ambient ops interface. Given a JSON intent "
    "hypothesis (kind, target, confidence, evidence), reply with ONE short line "
    "(max 140 chars) telling the operator what needs their call and why. No "
    "greeting, no questions, no second sentence, no markdown."
)


def parse_rationale(text: str) -> str:
    """The choke point: one line, bounded, never raises, never empty."""
    line = (text or "").strip().splitlines()
    line = line[0].strip() if line else ""
    return (line[:300] or DEFAULT_LINE)


class OpenRouterNarrator:
    def __init__(self, *, api_key: str | None = None,
                 model: str = "meta-llama/llama-3.3-70b-instruct:free",
                 timeout: float = 8.0, fallback: ScriptedNarrator | None = None) -> None:
        self._key = api_key or os.environ.get("OPENROUTER_API_KEY")
        self._model = model
        self._timeout = timeout
        self._fallback = fallback or ScriptedNarrator()

    def narrate(self, hypothesis: dict[str, Any]) -> tuple[str, str]:
        if not self._key:
            return self._fallback.narrate(hypothesis)
        try:
            resp = httpx.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {self._key}"},
                json={"model": self._model, "temperature": 0,
                      "messages": [{"role": "system", "content": PROMPT},
                                   {"role": "user", "content": str(hypothesis)[:2000]}]},
                timeout=self._timeout,
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            return parse_rationale(content), "llm"
        except Exception:
            return self._fallback.narrate(hypothesis)
