"""Friend-owned Cinema: the same H3 Max Director film, played on the body.

This is additive. Browser `/cinema` still uses `cinema/routes.py` unchanged.
GizmoSession keeps conversation, memory, PTT, and settings, and starts or stops
a film through this capability instead of swapping the whole `/ws` session.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from gizmo_friend.cinema.device import DeviceFilmPlayer
from gizmo_friend.cinema.routes import FilmBudget
from gizmo_friend.cinema.runtime import CinemaSession

logger = logging.getLogger(__name__)


class FriendCinema:
    """Start and stop a CinemaSession on the existing Friend glass/audio contract."""

    def __init__(
        self,
        *,
        directory: Path,
        device_id: str,
        store,
        emit,
        budget: FilmBudget | None = None,
        fal_key: str | None = None,
        maker=None,
        stream_factory=None,
        next_cue=None,
        on_segment=None,
        on_talking=None,
        on_idle=None,
        on_failed=None,
        session=None,
    ):
        self.directory = Path(directory)
        self.device_id = device_id
        self.store = store
        self._emit = emit
        self.budget = budget or FilmBudget(self.directory.parent)
        self.fal_key = (fal_key if fal_key is not None else os.environ.get("FAL_KEY", "")).strip()
        self._maker = maker
        self._stream_factory = stream_factory
        self.next_cue = next_cue
        self.on_segment = on_segment
        self.on_talking = on_talking
        self.on_idle = on_idle
        self.on_failed = on_failed
        self.session = session
        self.player = None
        self.acks: dict[tuple[int, str], asyncio.Future] = {}
        self._active = False

    @property
    def active(self) -> bool:
        playing = bool(self.player and self.player.playback and not self.player.playback.done())
        return self._active or playing

    def available(self) -> bool:
        if self.session is not None or self._maker is not None:
            return True
        return bool(self.fal_key and os.environ.get("GEMINI_API_KEY", "").strip())

    def on_glass_ready(self, cue, kind, ok) -> None:
        future = self.acks.get((cue, kind))
        if future and not future.done():
            future.set_result(ok is True)

    async def start(self, text: str) -> dict:
        text = " ".join(text.split())[:1200]
        if not text:
            return {"ok": False, "reason": "empty"}
        if not self.available():
            return {"ok": False, "reason": "unavailable"}
        if not await asyncio.to_thread(self.budget.reserve, self.device_id):
            return {"ok": False, "reason": "quiet day"}
        await self._ensure_session()
        await self.player.cancel_playback()
        self._active = True
        try:
            await self.session.ask(text)
        except Exception:
            self._active = False
            raise
        return {"ok": True, "status": "preparing"}

    async def stop(self) -> None:
        was_active = self.active
        self._active = False
        if self.player:
            await self.player.cancel_playback()
        if self.session:
            await self.session.interrupt()
        if was_active:
            logger.info("Friend cinema stopped device=%s", self.device_id)

    async def close(self) -> None:
        await self.stop()
        session, self.session = self.session, None
        self.player = None
        if session:
            await session.close()

    async def _ensure_session(self) -> None:
        if self.session is None:
            kwargs = {}
            if self._maker is not None:
                kwargs["maker"] = self._maker
            if self._stream_factory is not None:
                kwargs["stream_factory"] = self._stream_factory
            self.session = CinemaSession(
                self.directory, self.fal_key or "test", self._on_cinema_event, **kwargs
            )
        if self.player is None:
            self.player = DeviceFilmPlayer(
                self.session,
                self.store,
                self._emit,
                self.acks,
                next_cue=self.next_cue,
                on_segment=self.on_segment,
                on_talking=self.on_talking,
                on_failed=self._failed,
            )

    async def _failed(self) -> None:
        self._active = False
        if self.on_failed:
            await self.on_failed()
        else:
            await self._emit({"type": "interrupted"})
            await self._emit(
                {
                    "type": "error",
                    "message": "Film playback stopped; the last picture is retained.",
                }
            )
        if self.on_idle:
            await self.on_idle()

    async def _on_cinema_event(self, event) -> None:
        kind = event.get("type")
        if kind == "status" and event.get("phase") in {"thinking", "preparing"}:
            if self.player is not None:
                await self.player.show_conjuring()
            return
        if kind == "ready":
            if self.player is None or self.session is None:
                return
            self.player.playback = asyncio.create_task(self.player.play(event["revision"]))
            self.session.viewer.set()
            return
        if kind == "buffering":
            # Generation warmup misses playback deadlines before the first
            # chunk lands; the browser shows a spinner. On the body the
            # preload timeouts in DeviceFilmPlayer decide real stalls.
            logger.info("Friend cinema buffering device=%s", self.device_id)
            return
        if kind == "error":
            await self.stop()
            await self._emit(
                {
                    "type": "error",
                    "message": event.get(
                        "message", "Film paused while its pictures catch up."
                    ),
                }
            )
            if self.on_idle:
                await self.on_idle()
            return
        if kind == "ended":
            self._active = False
            if self.on_idle:
                await self.on_idle()
