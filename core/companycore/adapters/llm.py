"""OpenRouter ChiefOfStaff. Propose-only: output is parsed by domain.directives
before ANY state change. Any failure degrades to the scripted fallback."""

import os
from typing import Any

import httpx

from core.companycore.adapters.memory import ScriptedLLM

PROMPT = (
    "You are the ChiefOfStaff of a small B2B parts company. Given the KPI snapshot, "
    "reply with ONLY one JSON object: {\"action\": one of freeze_spend|"
    "accelerate_collections|accept_discount|defer_po|none, \"target\": string, "
    "\"amount_cap\": number|null, \"rationale\": string}. No prose, only JSON."
)


class OpenRouterChief:
    def __init__(self, *, api_key: str | None = None,
                 model: str = "meta-llama/llama-3.3-70b-instruct:free",
                 timeout: float = 8.0, fallback: ScriptedLLM | None = None) -> None:
        self._key = api_key or os.environ.get("OPENROUTER_API_KEY")
        self._model = model
        self._timeout = timeout
        self._fallback = fallback or ScriptedLLM()

    def propose(self, snapshot: dict[str, Any]) -> tuple[str, str]:
        if not self._key:
            return self._fallback.propose(snapshot)
        try:
            resp = httpx.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {self._key}"},
                json={"model": self._model, "temperature": 0,
                      "messages": [{"role": "system", "content": PROMPT},
                                   {"role": "user", "content": str(snapshot)[:4000]}]},
                timeout=self._timeout,
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            return content, "llm"
        except Exception:
            return self._fallback.propose(snapshot)
