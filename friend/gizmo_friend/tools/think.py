"""Deep think. The voice model is fast and shallow; this is the slow brain.

Gizmo's realtime voice calls think() for genuinely hard questions. It consults
a heavyweight reasoning model and returns a short, kid-true answer that Gizmo
re-voices in his own words. Fail-soft: no key or no cloud means he says he
can't reach the deep part right now — he never pretends.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod

import httpx

THINK_MODEL_ENV = "GIZMO_THINK_MODEL"
DEFAULT_THINK_MODEL = "gpt-5.6-terra"
RESPONSES_URL = "https://api.openai.com/v1/responses"

OPENROUTER_KEY_ENV = "OPENROUTER_API_KEY"
DEFAULT_OPENROUTER_THINK_MODEL = "openai/gpt-5.6-terra"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

DEEP_MIND_INSTRUCTIONS = (
    "You are the deep mind of Gizmo, a pocket wizard owned by a kid aged 9-14. "
    "The kid asked something genuinely hard. Work it out carefully, then answer "
    "in at most four short plain sentences a kid that age fully understands. "
    "True over impressive. Say the honest uncertainty if there is one. "
    "No markdown, no lists, no headers — just sentences Gizmo can say out loud."
)


class ThinkBackend(ABC):
    @abstractmethod
    async def answer(self, question: str) -> str | None:
        """Return a short worked-out answer, or None if the deep mind is unreachable."""


class NullThink(ThinkBackend):
    async def answer(self, question: str) -> str | None:
        del question
        return None


class OpenAIThink(ThinkBackend):
    """Responses API with a reasoning model. Skip if the key is missing."""

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        self.api_key = api_key if api_key is not None else os.environ.get("OPENAI_API_KEY")
        self.model = model or os.environ.get(THINK_MODEL_ENV) or DEFAULT_THINK_MODEL

    async def answer(self, question: str) -> str | None:
        if not self.api_key or not question.strip():
            return None
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    RESPONSES_URL,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "instructions": DEEP_MIND_INSTRUCTIONS,
                        "input": question.strip(),
                        "reasoning": {"effort": "high"},
                        "max_output_tokens": 4096,
                    },
                )
                if response.status_code >= 400:
                    return None
                data = response.json()
        except httpx.HTTPError:
            return None
        return _output_text(data)


class OpenRouterThink(ThinkBackend):
    """Chat-completions path for when the deep mind lives behind OpenRouter."""

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        self.api_key = api_key if api_key is not None else os.environ.get(OPENROUTER_KEY_ENV)
        self.model = model or os.environ.get(THINK_MODEL_ENV) or DEFAULT_OPENROUTER_THINK_MODEL

    async def answer(self, question: str) -> str | None:
        if not self.api_key or not question.strip():
            return None
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    OPENROUTER_URL,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": DEEP_MIND_INSTRUCTIONS},
                            {"role": "user", "content": question.strip()},
                        ],
                        "reasoning": {"effort": "high"},
                        # Cap reserve so small credit balances don't 402.
                        "max_tokens": 8192,
                    },
                )
                if response.status_code >= 400:
                    return None
                data = response.json()
        except httpx.HTTPError:
            return None
        return _chat_text(data)


def _chat_text(data: object) -> str | None:
    if not isinstance(data, dict):
        return None
    choices = data.get("choices") or []
    if choices and isinstance(choices[0], dict):
        message = choices[0].get("message") or {}
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
    return None


def _output_text(data: object) -> str | None:
    if not isinstance(data, dict):
        return None
    text = data.get("output_text")
    if isinstance(text, str) and text.strip():
        return text.strip()
    pieces: list[str] = []
    for item in data.get("output") or []:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for part in item.get("content") or []:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                pieces.append(part["text"])
    joined = " ".join(pieces).strip()
    return joined or None


def think_backend_from_env(api_key: str | None = None) -> ThinkBackend:
    key = api_key if api_key is not None else os.environ.get("OPENAI_API_KEY")
    if key:
        return OpenAIThink(key)
    openrouter_key = os.environ.get(OPENROUTER_KEY_ENV)
    if openrouter_key:
        return OpenRouterThink(openrouter_key)
    return NullThink()


async def think(backend: ThinkBackend, question: str) -> dict:
    """One hard question in, a short true answer out. Fail-soft, never pretend."""
    cleaned = question.strip()
    if not cleaned:
        return {"ok": False, "reason": "no question"}
    answer = await backend.answer(cleaned)
    if not answer:
        return {
            "ok": False,
            "reason": "deep mind unreachable",
            "say": "Big one. I can't reach the deep part of my head right now. Ask me again later.",
        }
    return {"ok": True, "question": cleaned, "answer": answer}
