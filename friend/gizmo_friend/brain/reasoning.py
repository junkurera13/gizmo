from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass


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
class GeminiReasoningProvider(ReasoningProvider):
    api_key: str
    model: str = "gemini-3.7-flash"

    def __post_init__(self) -> None:
        from google import genai

        self._client = genai.Client(api_key=self.api_key)

    async def reason(self, question: str, memory_context: str = "") -> str | None:
        from google.genai import types

        from gizmo_friend.safety import KID_SAFETY_SETTINGS

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
        response = await self._client.aio.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system,
                safety_settings=KID_SAFETY_SETTINGS,
                thinking_config=types.ThinkingConfig(thinking_level="HIGH"),
                max_output_tokens=2048,
            ),
        )
        text = (response.text or "").strip()
        return text or None

    async def close(self) -> None:
        await self._client.aio.aclose()
        self._client.close()


def reasoning_provider_from_env(api_key: str | None = None) -> ReasoningProvider:
    key = (api_key or os.environ.get("GEMINI_API_KEY") or "").strip()
    if not key:
        return NullReasoningProvider()
    return GeminiReasoningProvider(
        api_key=key,
        model=os.environ.get("GIZMO_REASONING_MODEL", "gemini-3.7-flash"),
    )
