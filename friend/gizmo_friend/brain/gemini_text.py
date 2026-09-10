"""Non-voice text inference on Gemini. Fal stays reserved for media generation."""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field

from google import genai
from google.genai import types

TEXT_MODEL = "gemini-3.1-flash-lite"


@dataclass
class GeminiTextClient:
    api_key: str = field(repr=False)
    model: str = TEXT_MODEL
    _client: genai.Client = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._client = genai.Client(api_key=self.api_key)

    async def complete(self, system: str, text: str, *, schema: dict | None = None,
                       image: bytes | None = None, timeout: float = 12, max_tokens: int = 1024) -> str:
        if schema:
            system += "\nReturn only a JSON object matching this schema. No markdown.\n" + json.dumps(schema)
        parts: list[types.Part] = []
        if image:
            parts.append(types.Part(inline_data=types.Blob(data=image, mime_type="image/jpeg")))
        parts.append(types.Part(text=text))
        async with asyncio.timeout(timeout):
            response = await self._client.aio.models.generate_content(
                model=self.model,
                contents=[types.Content(role="user", parts=parts)],
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    temperature=0,
                    max_output_tokens=max_tokens,
                    response_mime_type="application/json" if schema else None,
                ),
            )
        result = response.text
        if not isinstance(result, str) or not result.strip():
            raise ValueError("Empty text response")
        result = result.strip()
        if schema:
            lines = result.splitlines()
            if len(lines) >= 3 and lines[0].lower() in ("```", "```json") and lines[-1] == "```":
                result = "\n".join(lines[1:-1])
            parsed = json.loads(result)
            if not isinstance(parsed, dict):
                raise ValueError("Expected a JSON object")
            return json.dumps(parsed)
        return result

    async def close(self) -> None:
        await self._client.aio.aclose()
        self._client.close()
