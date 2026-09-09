from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from gizmo_friend.brain.fal_text import FalTextClient


class ReasoningProvider(ABC):
    @abstractmethod
    async def reason(self, question: str, memory_context: str = "") -> str | None:
        """Return private analysis for Gemini Live to turn into the spoken answer."""

    async def close(self) -> None:
        return


class NullReasoningProvider(ReasoningProvider):
    async def reason(self, question: str, memory_context: str = "") -> str | None:
        del question, memory_context
        return None


@dataclass
class FalReasoningProvider(ReasoningProvider):
    api_key: str = field(repr=False)
    model: str = "anthropic/claude-sonnet-4.6"

    def __post_init__(self) -> None:
        self._client = FalTextClient(self.api_key, model=self.model)

    async def reason(self, question: str, memory_context: str = "") -> str | None:
        prompt = question.strip()
        if not prompt:
            return None
        system = (
            "You are Gizmo's private reasoning engine. Solve the question carefully and return "
            "a concise factual brief to the realtime agent. Do not address the user, perform the "
            "Gizmo personality, or mention this tool. State uncertainty explicitly."
        )
        if memory_context:
            system += f"\n\nRelevant user memory, only when useful:\n{memory_context}"
        return await self._client.complete(system, prompt, timeout=15, max_tokens=2048)

    async def close(self) -> None:
        await self._client.close()


def reasoning_provider_from_env(api_key: str | None = None) -> ReasoningProvider:
    key = (api_key or os.environ.get("FAL_KEY") or "").strip()
    if not key:
        return NullReasoningProvider()
    return FalReasoningProvider(
        api_key=key,
        model=os.environ.get("GIZMO_REASONING_MODEL", "anthropic/claude-sonnet-4.6"),
    )
