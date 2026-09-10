"""Oddity-owned Cinema: the same H3 Max Director film Friend uses.

This is additive. Browser `/cinema` still uses `cinema/routes.py` unchanged.
Oddity keeps its device chrome and beat queue, and starts or stops a film
through this wrapper instead of Fal still→short-clip.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from gizmo_friend.brain.visual_director import is_moving_explanation_ask
from gizmo_friend.cinema.runtime import CinemaSession
from gizmo_friend.oddity.director import Beat, Experience

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FilmReady:
    revision: int
    duration: float
    title: str
    narration: str


def route_moving_picture(plan: Experience, utterance: str) -> Experience:
    """At most one Cinema film, and only when motion would help the ask.

    Director `video` is an alias for film. Easy talk and leftover clips become
    stills. Diagrams and the computed orbit experiment stay as planned.
    """
    wants_film = is_moving_explanation_ask(utterance)
    used = False
    beats: list[Beat] = []
    for beat in plan.beats:
        if beat.visual in {"video", "film"}:
            if wants_film and not used:
                beats.append(beat.model_copy(update={"visual": "film"}))
                used = True
            elif beat.subject.strip():
                beats.append(beat.model_copy(update={"visual": "image", "motion": ""}))
            else:
                beats.append(beat.model_copy(update={"visual": "keep", "motion": ""}))
        elif beat.visual == "image" and wants_film and not used:
            beats.append(beat.model_copy(update={"visual": "film"}))
            used = True
        else:
            beats.append(beat)
    return plan.model_copy(update={"beats": beats})


class OddityCinema:
    """Start and stop a CinemaSession on the Oddity glass, without a held-cue body."""

    def __init__(
        self,
        *,
        directory: Path,
        fal_key: str | None = None,
        maker=None,
        stream_factory=None,
        session=None,
    ):
        self.directory = Path(directory)
        self.fal_key = (fal_key if fal_key is not None else os.environ.get("FAL_KEY", "")).strip()
        self._maker = maker
        self._stream_factory = stream_factory
        self.session = session
        self._ready = asyncio.Event()
        self._payload: dict | None = None
        self._failed: dict | None = None

    def available(self) -> bool:
        if self.session is not None or self._maker is not None:
            return True
        return bool(self.fal_key and os.environ.get("GEMINI_API_KEY", "").strip())

    async def start(self, text: str) -> FilmReady | None:
        text = " ".join(text.split())[:1200]
        if not text or not self.available():
            return None
        await self.interrupt()
        self._ready = asyncio.Event()
        self._payload = None
        self._failed = None
        try:
            await self._ensure_session()
            await self.session.ask(text)
            async with asyncio.timeout(90):
                await self._ready.wait()
        except asyncio.CancelledError:
            if self.session:
                await self.session.interrupt()
            raise
        except TimeoutError:
            logger.warning("Oddity cinema timed out waiting for a ready film")
            if self.session:
                await self.session.interrupt()
            return None
        if self._failed or not self._payload:
            return None
        event = self._payload
        return FilmReady(
            revision=int(event.get("revision") or 0),
            duration=float(event.get("duration") or 0),
            title=str(event.get("title") or ""),
            narration=str(event.get("narration") or ""),
        )

    async def offer(self, sdp, revision, *, local: bool = False):
        if self.session is None:
            raise ValueError("Stale film")
        return await self.session.offer(sdp, revision, local=local)

    async def finish(self, revision) -> None:
        if self.session is None:
            return
        await self.session.finish(revision)

    async def interrupt(self) -> None:
        self._failed = {"type": "error", "message": "interrupted"}
        self._ready.set()
        if self.session:
            await self.session.interrupt()

    async def close(self) -> None:
        await self.interrupt()
        session, self.session = self.session, None
        if session:
            await session.close()

    async def _ensure_session(self) -> None:
        if self.session is not None:
            return
        kwargs = {}
        if self._maker is not None:
            kwargs["maker"] = self._maker
        if self._stream_factory is not None:
            kwargs["stream_factory"] = self._stream_factory
        self.session = CinemaSession(
            self.directory / "cinema",
            self.fal_key or "test",
            self._on_event,
            **kwargs,
        )

    async def _on_event(self, event) -> None:
        kind = event.get("type")
        if kind == "ready":
            self._payload = event
            self._ready.set()
            return
        if kind == "error":
            self._failed = event
            self._ready.set()
