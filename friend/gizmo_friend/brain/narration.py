"""Scripted narration in Gizmo's own voice, for the storytelling conductor.

Gemini Live improvises conversation. A story that must be cut to its pictures
is scripted first and voiced here, with the same prebuilt voice Live uses, so
the kid hears one Gizmo whether he is chatting or telling a chapter.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import httpx

from gizmo_friend.voice import AGENT_VOICE

try:
    import audioop
except ImportError:  # Python 3.13+
    import audioop_lts as audioop  # type: ignore[no-redef]

logger = logging.getLogger(__name__)

NARRATION_MODEL = "gemini-3.1-flash-tts-preview"
NARRATION_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models"
NARRATION_TIMEOUT_SECONDS = 20.0
NARRATION_RATE = 24_000
NARRATION_ATTEMPTS = 4
RETRYABLE_STATUS = {429, 503}
MAX_NARRATION_CHARS = 1200
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
# The delivery note is fixed. The planner writes what he says; this is how.
NARRATION_STYLE = (
    "Read the following as Gizmo, a small dry wizard telling a kid a true story. "
    "Unhurried, low energy, warm underneath. Plain, not theatrical. Do not add words. "
    "Pause briefly at full stops."
)


@dataclass(frozen=True)
class Narration:
    text: str
    pcm: bytes = field(repr=False)  # 24 kHz mono PCM16, the body wire format
    model: str
    latency_seconds: float

    @property
    def duration_seconds(self) -> float:
        return len(self.pcm) / 2 / NARRATION_RATE


class NarrationProvider(ABC):
    @abstractmethod
    async def narrate(self, text: str, *, style: str | None = None) -> Narration | None:
        """Return finished speech for one beat, or nothing when unavailable/late."""

    async def close(self) -> None:
        return


class NullNarrationProvider(NarrationProvider):
    async def narrate(self, text: str, *, style: str | None = None) -> Narration | None:
        del text, style
        return None


def retry_wait_seconds(response: httpx.Response | None, attempt: int) -> float:
    raw = response.headers.get("retry-after") if response is not None else None
    if raw:
        try:
            return min(max(float(raw), 0.0), 8.0)
        except ValueError:
            pass
    return min(0.5 * (2 ** attempt), 8.0)


def pcm_from_part(mime_type: str, data: bytes) -> bytes:
    """Normalize a TTS inline part to the 24 kHz mono PCM16 the body plays."""
    if not mime_type.lower().startswith(("audio/l16", "audio/pcm")):
        raise ValueError("Provider did not return PCM audio")
    match = re.search(r"rate=(\d+)", mime_type)
    rate = int(match.group(1)) if match else NARRATION_RATE
    if len(data) % 2:
        data = data[:-1]
    if rate != NARRATION_RATE:
        data, _ = audioop.ratecv(data, 2, 1, rate, NARRATION_RATE, None)
    return data


@dataclass
class GeminiNarrationProvider(NarrationProvider):
    api_key: str = field(repr=False)
    voice: str = AGENT_VOICE
    model: str = NARRATION_MODEL
    timeout_seconds: float = NARRATION_TIMEOUT_SECONDS
    style: str = NARRATION_STYLE
    _client: httpx.AsyncClient = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._client = httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=False)

    async def narrate(self, text: str, *, style: str | None = None) -> Narration | None:
        text = " ".join(text.split())[:MAX_NARRATION_CHARS]
        if not text:
            return None
        delivery = style or self.style
        payload = {
            "contents": [{"parts": [{"text": f"{delivery}\n\n{text}"}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": self.voice}}},
            },
        }
        started = time.perf_counter()
        for attempt in range(NARRATION_ATTEMPTS):
            wait = None
            retry_status = None
            try:
                async with asyncio.timeout(self.timeout_seconds):
                    raw = bytearray()
                    async with self._client.stream(
                        "POST", f"{NARRATION_ENDPOINT}/{self.model}:generateContent", json=payload,
                        headers={"x-goog-api-key": self.api_key},
                    ) as response:
                        if response.status_code in RETRYABLE_STATUS:
                            retry_status = response.status_code
                            wait = retry_wait_seconds(response, attempt)
                            if attempt + 1 >= NARRATION_ATTEMPTS:
                                response.raise_for_status()
                        else:
                            response.raise_for_status()
                            async for chunk in response.aiter_bytes():
                                raw.extend(chunk)
                                if len(raw) > MAX_RESPONSE_BYTES:
                                    raise ValueError("Narration response exceeds size limit")
                if wait is not None:
                    logger.warning(
                        "Narration %s, retry in %.1fs attempt=%s",
                        retry_status, wait, attempt + 1,
                    )
                    await asyncio.sleep(wait)
                    continue
                result = json.loads(raw)
                parts = result["candidates"][0]["content"]["parts"]
                inline = next(part["inlineData"] for part in parts if "inlineData" in part)
                pcm = pcm_from_part(inline.get("mimeType", ""), base64.b64decode(inline["data"], validate=True))
                if len(pcm) < NARRATION_RATE // 10 * 2:
                    raise ValueError("Narration too short to be speech")
                elapsed = time.perf_counter() - started
                logger.info(
                    "Narration generated: model=%s voice=%s seconds=%.3f audio_seconds=%.2f",
                    self.model, self.voice, elapsed, len(pcm) / 2 / NARRATION_RATE,
                )
                return Narration(text=text, pcm=pcm, model=self.model, latency_seconds=elapsed)
            except asyncio.CancelledError:
                raise
            except TimeoutError:
                logger.warning("Narration dropped: model=%s exceeded %.1f seconds", self.model, self.timeout_seconds)
                return None
            except httpx.HTTPStatusError as error:
                status = error.response.status_code
                if status in RETRYABLE_STATUS and attempt + 1 < NARRATION_ATTEMPTS:
                    wait = retry_wait_seconds(error.response, attempt)
                    logger.warning("Narration %s, retry in %.1fs attempt=%s", status, wait, attempt + 1)
                    await asyncio.sleep(wait)
                    continue
                logger.warning(
                    "Narration failed: model=%s error=%s status=%s", self.model, type(error).__name__, status,
                )
                return None
            except Exception as error:  # noqa: BLE001 - narration must fail soft; the story falls back
                logger.warning(
                    "Narration failed: model=%s error=%s status=%s", self.model, type(error).__name__,
                    error.response.status_code if isinstance(error, httpx.HTTPStatusError) else None,
                )
                return None
        return None

    async def close(self) -> None:
        await self._client.aclose()


def narration_provider_from_env(
    api_key: str | None = None, *, voice: str | None = None, style: str = NARRATION_STYLE,
) -> NarrationProvider:
    key = (api_key or os.environ.get("GEMINI_API_KEY") or "").strip()
    if not key:
        logger.warning("STORY NARRATION UNAVAILABLE: GEMINI_API_KEY missing")
        return NullNarrationProvider()
    return GeminiNarrationProvider(
        api_key=key,
        voice=voice or AGENT_VOICE,
        model=os.environ.get("GIZMO_NARRATION_MODEL", NARRATION_MODEL),
        style=style,
    )
