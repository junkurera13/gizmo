"""Leftover Fal image-to-video provider. Not used for Friend or Oddity moving
explanations — those play Cinema (H3 Max Director). Kept for provider unit
tests and historical Show checkpoints.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import httpx

logger = logging.getLogger(__name__)

CLIP_MODEL = "minimax/h3-max/image-to-video"
CLIP_TIMEOUT_SECONDS = 20.0
MAX_CLIP_BYTES = 50 * 1024 * 1024
MOTION_PREFIX = (
    "Keep the exact style, palette and composition of the first frame. "
    "Small, quiet motion only. Lock the camera: no pan, tilt, zoom, rotation or reframing. "
    "Animate only the detail named in the motion brief; all other shapes stay still. "
    "Keep the main subject fully inside the frame for the entire clip. "
    "Limit any whole-subject travel to at most five percent of the frame width or "
    "height from its starting position, even if the motion brief suggests more. "
    "Keep motion within the existing subject's area; do not progressively enlarge "
    "the subject, spread smoke across the scene, or reveal new parts of the scene. "
    "Preserve the original shapes and proportions. No new objects, text, or faces. "
    "Preserve any existing educational labels exactly and keep them stationary. "
    "Use small repeating motion only where it is natural for the subject; never "
    "reverse a physical process just to return to the starting pose. No cuts."
)


@dataclass(frozen=True)
class ConjuredClip:
    motion: str
    mp4: bytes = field(repr=False)
    prompt: str
    model: str
    request_id: str
    source_image_sha256: str
    latency_seconds: float
    expanded_prompt: str | None
    timings: dict[str, float]


class ClipProvider(ABC):
    @abstractmethod
    async def animate(self, still: bytes, motion: str) -> ConjuredClip | None:
        """Return the original MP4, or nothing when unavailable/late/blocked."""

    async def close(self) -> None:
        return


class NullClipProvider(ClipProvider):
    async def animate(self, still: bytes, motion: str) -> ConjuredClip | None:
        return None


def _queue_url(value: object) -> str:
    # Queue response URLs may omit the model's image-to-video suffix. Use the
    # returned URLs, but never forward the API credential to another origin.
    if not isinstance(value, str):
        raise ValueError("Missing queue URL")
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or parsed.netloc != "queue.fal.run"
            or not parsed.path.startswith("/minimax/h3-max/requests/")):
        raise ValueError("Unexpected queue URL")
    return value


@dataclass
class H3MaxClipProvider(ClipProvider):
    api_key: str = field(repr=False)
    motion_prefix: str = MOTION_PREFIX
    # The standalone checkpoint can measure slow generations without imposing
    # the runtime deadline. Production callers retain the plan's 20-second cap.
    timeout_seconds: float = CLIP_TIMEOUT_SECONDS
    poll_interval_seconds: float = 0.5
    _client: httpx.AsyncClient = field(init=False, repr=False)

    def __post_init__(self) -> None:
        # No automatic retries: a second POST can create a second paid video.
        # Auth is per queue request, never attached to media downloads.
        self._client = httpx.AsyncClient(timeout=20.0, follow_redirects=False)

    async def _queue(self, method: str, url: str, **kwargs) -> httpx.Response:
        headers = {"Authorization": f"Key {self.api_key}"}
        if method == "POST":
            headers.update({
                "X-Fal-No-Retry": "1",
                "x-app-fal-disable-fallback": "true",
                "X-Fal-Request-Timeout": str(self.timeout_seconds),
            })
        response = await self._client.request(
            method, url, headers=headers, **kwargs,
        )
        response.raise_for_status()
        return response

    async def _cancel(self, url: str | None) -> None:
        if url is None:
            return
        try:
            async with asyncio.timeout(3):
                await self._queue("PUT", url)
        except Exception:
            logger.warning("Show clip cancellation could not be confirmed")

    async def _download(self, value: object) -> bytes:
        if not isinstance(value, str):
            raise ValueError("Missing video URL")
        parsed = urlsplit(value)
        # fal delivers generated files from its own media hosts. Do not fetch
        # arbitrary hosts or local addresses from a malformed provider response.
        if (parsed.scheme != "https" or parsed.username or parsed.password
                or not (parsed.hostname or "").endswith(".fal.media")):
            raise ValueError("Unexpected video URL")
        chunks = bytearray()
        async with self._client.stream("GET", value) as response:
            response.raise_for_status()
            async for chunk in response.aiter_bytes():
                chunks.extend(chunk)
                if len(chunks) > MAX_CLIP_BYTES:
                    raise ValueError("Video exceeds size limit")
        if len(chunks) < 12 or chunks[4:8] != b"ftyp":
            raise ValueError("Provider did not return an MP4")
        return bytes(chunks)

    async def animate(self, still: bytes, motion: str) -> ConjuredClip | None:
        motion = motion.strip()
        if not still or not motion:
            return None
        prompt = f"{self.motion_prefix}\n\nMotion: {motion}"
        started = time.perf_counter()
        cancel_url = None
        request_id = None
        completed = False
        try:
            async with asyncio.timeout(self.timeout_seconds):
                response = await self._queue(
                    "POST", f"https://queue.fal.run/{CLIP_MODEL}",
                    json={
                        "prompt": prompt,
                        "image_url": "data:image/jpeg;base64," + base64.b64encode(still).decode("ascii"),
                        "duration": 5,
                        "resolution": "480P",
                        "enable_safety_checker": True,
                        "prompt_expansion_mode": "disabled",
                        "sync_mode": False,
                    },
                )
                submitted = response.json()
                request_id = submitted["request_id"]
                cancel_url = _queue_url(submitted["cancel_url"])
                status_url = _queue_url(submitted["status_url"])
                result_url = _queue_url(submitted["response_url"])
                while True:
                    response = await self._queue("GET", status_url, params={"logs": 0})
                    status = response.json()["status"]
                    if status == "COMPLETED":
                        completed = True
                        break
                    if status not in {"IN_QUEUE", "IN_PROGRESS"}:
                        raise ValueError("Unexpected queue status")
                    await asyncio.sleep(self.poll_interval_seconds)
                response = await self._queue("GET", result_url)
                result = response.json()
                expanded = result.get("expanded_prompt")
                if expanded is not None and expanded != prompt:
                    # The controlled motion prompt must survive the expansion-off
                    # setting. Do not silently accept a cinematic rewrite.
                    raise ValueError("Provider rewrote the motion prompt")
                mp4 = await self._download(result["video"]["url"])
                return ConjuredClip(
                    motion=motion, mp4=mp4, prompt=prompt, model=CLIP_MODEL,
                    request_id=request_id,
                    source_image_sha256=hashlib.sha256(still).hexdigest(),
                    latency_seconds=time.perf_counter() - started,
                    expanded_prompt=expanded,
                    timings=result.get("timings") or {},
                )
        except asyncio.CancelledError:
            if not completed:
                await self._cancel(cancel_url)
            raise
        except TimeoutError:
            logger.warning(
                "Show clip dropped: request=%s exceeded %.1f seconds",
                request_id, self.timeout_seconds,
            )
        except Exception as exc:
            # Never log credentials, signed URLs, input bytes, or response bodies.
            logger.warning(
                "Show clip failed: request=%s error=%s status=%s",
                request_id, type(exc).__name__,
                exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None,
            )
        if not completed:
            await self._cancel(cancel_url)
        return None

    async def close(self) -> None:
        await self._client.aclose()


def clip_provider_from_env(api_key: str | None = None) -> ClipProvider:
    key = (api_key or os.environ.get("FAL_KEY") or "").strip()
    if not key:
        logger.warning("SHOW MOTION UNAVAILABLE: FAL_KEY missing; stills only")
        return NullClipProvider()
    return H3MaxClipProvider(api_key=key)
