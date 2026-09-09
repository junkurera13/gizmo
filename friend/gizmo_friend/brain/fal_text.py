"""Non-voice inference billed through Fal's OpenRouter endpoint."""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field

import httpx

TEXT_MODEL = "anthropic/claude-haiku-4.5"
TEXT_ENDPOINT = "https://fal.run/openrouter/router/openai/v1/chat/completions"


@dataclass
class FalTextClient:
    api_key: str = field(repr=False)
    model: str = TEXT_MODEL
    _client: httpx.AsyncClient = field(init=False, repr=False)

    def __post_init__(self):
        if self.model.startswith(("google/", "gemini")):
            raise ValueError("Google is reserved for voice; select a non-Google text model")
        self._client = httpx.AsyncClient(timeout=30, follow_redirects=False)

    async def complete(self, system: str, text: str, *, schema: dict | None = None,
                       image: bytes | None = None, timeout: float = 12, max_tokens: int = 1024) -> str:
        if schema:
            system += "\nReturn only a JSON object matching this schema. No markdown.\n" + json.dumps(schema)
        content: object = text
        if image:
            import base64
            content = [{"type": "text", "text": text}, {"type": "image_url", "image_url": {
                "url": "data:image/jpeg;base64," + base64.b64encode(image).decode("ascii"),
            }}]
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}],
            "temperature": 0, "max_tokens": max_tokens,
        }
        if schema:
            payload["response_format"] = {"type": "json_object"}
        async with asyncio.timeout(timeout):
            raw = bytearray()
            async with self._client.stream("POST", TEXT_ENDPOINT, json=payload, headers={
                "Authorization": f"Key {self.api_key}", "X-Fal-No-Retry": "1",
            }) as response:
                response.raise_for_status()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 256 * 1024:
                        raise ValueError("Text response exceeds size limit")
            choice = json.loads(raw)["choices"][0]
            if choice.get("finish_reason") != "stop" or choice["message"].get("refusal"):
                raise ValueError("No complete text response")
            result = choice["message"]["content"]
            if not isinstance(result, str) or not result.strip():
                raise ValueError("Empty text response")
            result = result.strip()
            if schema:
                # Some routed models fence JSON even with json_object enabled.
                lines = result.splitlines()
                if len(lines) >= 3 and lines[0].lower() in ("```", "```json") and lines[-1] == "```":
                    result = "\n".join(lines[1:-1])
                parsed = json.loads(result)
                if not isinstance(parsed, dict):
                    raise ValueError("Expected a JSON object")
                return json.dumps(parsed)
            return result

    async def close(self):
        await self._client.aclose()
