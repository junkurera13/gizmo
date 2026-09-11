"""Oddity-owned Cinema: the same H3 Max Director film Friend uses.

This is additive. Browser `/cinema` still uses `cinema/routes.py` unchanged.
Oddity keeps its device chrome and beat queue, and starts or stops a film
through this wrapper instead of Fal still→short-clip.

The planner's medium decision is authoritative here: there is no utterance
heuristic between the director and Cinema.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from gizmo_friend.cinema.runtime import CinemaSession

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FilmReady:
    revision: int
    duration: float
    title: str
    narration: str
    timings: tuple = ()
    soundtrack: bytes = b""


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

    async def start(
        self,
        text: str,
        *,
        direction: str = "",
        on_pending: Callable[[int], Awaitable[None]] | None = None,
    ) -> FilmReady | None:
        """Plan, voice and host the film; return once Director can be started.

        `on_pending` receives the revision as soon as it exists so a viewer can
        connect its peer while the score is still being written.
        """
        text = " ".join(text.split())[:1200]
        if not text or not self.available():
            return None
        await self.interrupt()
        self._ready = asyncio.Event()
        self._payload = None
        self._failed = None
        try:
            await self._ensure_session()
            await self.session.ask(text, direction=direction)
            if on_pending is not None:
                await on_pending(self.session.revision)
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
        revision = int(event.get("revision") or 0)
        soundtrack = b""
        try:
            soundtrack = (self.directory / "cinema" / f"{revision}.wav").read_bytes()
        except OSError:
            pass
        return FilmReady(
            revision=revision,
            duration=float(event.get("duration") or 0),
            title=str(event.get("title") or ""),
            narration=str(event.get("narration") or ""),
            timings=tuple(event.get("timings") or ()),
            soundtrack=soundtrack,
        )

    async def offer(self, sdp, revision, *, local: bool = False):
        # The viewer connects early; generation starts on `watch`, when the
        # glass actually reaches the film beat.
        if self.session is None:
            raise ValueError("Stale film")
        return await self.session.offer(sdp, revision, local=local, start=False)

    def watch(self, revision) -> bool:
        if self.session is None:
            return False
        return self.session.watch(revision)

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
