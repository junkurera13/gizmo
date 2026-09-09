from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

from gizmo_friend.cinema.plan import FilmMaker
from gizmo_friend.cinema.stream import DirectorStream

logger = logging.getLogger(__name__)


class CinemaSession:
    def __init__(
        self,
        directory: Path,
        key: str,
        emit,
        *,
        maker=None,
        stream_factory=DirectorStream,
    ):
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self.key = key
        self._deliver = emit
        self.emit = self.publish
        self.maker = maker or FilmMaker()
        self.stream_factory = stream_factory
        self.stream = None
        self.work = None
        self.lease = None
        self.revision = 0
        self.request_id = None
        try:
            self.context = json.loads((directory / "context.json").read_text())[-8:]
            if not isinstance(self.context, list):
                self.context = []
        except (OSError, ValueError, TypeError):
            self.context = []
        self.prepared = None
        self.viewer = asyncio.Event()
        self.closed = False
        self.turns = 0
        self.started = 0.0

    async def publish(self, event):
        event = {**event, "request_id": self.request_id}
        record = {**event, "at": round(time.monotonic(), 3)}
        with (self.directory / "events.jsonl").open("a") as log:
            log.write(json.dumps(record) + "\n")
        await self._deliver(event)

    async def ask(self, text, *, request_id=None):
        text = " ".join(text.split())[:1200]
        if not text or self.closed:
            return
        if self.turns >= 8:
            await self.emit(
                {
                    "type": "error",
                    "message": "This film session has reached its limit. Start a new session to continue.",
                }
            )
            return
        await self.interrupt()
        self.request_id = request_id
        self.turns += 1
        revision = self.revision
        self.started = time.monotonic()
        self.context.append({"user": text})
        self.work = asyncio.create_task(self.run(text, revision))

    async def run(self, text, revision):
        stream = self.stream_factory(
            self.key, lambda event: self.provider_event(event, revision)
        )
        self.stream = stream
        opening = asyncio.create_task(stream.connect())
        try:
            await self.emit(
                {
                    "type": "status",
                    "phase": "thinking",
                    "message": "Thinking it through…",
                    "revision": revision,
                }
            )
            plan = await self.maker.plan(text, self.context)
            if revision != self.revision:
                return
            await self.emit({"type": "plan", "title": plan.title, "revision": revision})
            await self.emit(
                {
                    "type": "status",
                    "phase": "preparing",
                    "message": "Bringing it to life…",
                    "revision": revision,
                }
            )
            self.prepared = prepared = await self.maker.prepare(plan)
            await opening
            if revision != self.revision:
                return
            (self.directory / f"{revision}.wav").write_bytes(prepared.wav)
            (self.directory / f"{revision}.json").write_text(
                json.dumps(
                    {
                        "plan": plan.model_dump(),
                        "timings": prepared.timings,
                        "duration": prepared.duration,
                    }
                )
            )
            await self.emit(
                {
                    "type": "ready",
                    "revision": revision,
                    "title": plan.title,
                    "duration": prepared.duration,
                    "narration": plan.narration,
                }
            )
            async with asyncio.timeout(20):
                await self.viewer.wait()
            configuration = {
                "type": "configure",
                "protocol_version": 1,
                "prompt_version": revision,
                "resolution": "480p",
                "aspect_ratio": "16:9",
                "memory": 12,
                "prompt": plan.direction()
                + "\nAudio timeline in seconds: "
                + json.dumps(prepared.timings),
                "audio_url": prepared.audio_url,
            }
            anchor = self.directory / "last-frame.jpg"
            if plan.relation != "new" and anchor.is_file():
                async with asyncio.timeout(10):
                    configuration["image_url"] = await self.maker.upload.upload(
                        anchor.read_bytes(),
                        "image/jpeg",
                        file_name="gizmo-continuation.jpg",
                    )
            stream.send(configuration)
            # A lost browser cannot leave a paid infinite generation session running.
            self.lease = asyncio.create_task(
                self.expire(revision, min(100, prepared.duration + 35))
            )
            async with asyncio.timeout(35):
                await stream.first_frame.wait()
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - report a failed film and close its peer
            logger.warning(
                "Cinema failed: revision=%s error=%s", revision, type(error).__name__
            )
            if revision == self.revision:
                await self.emit(
                    {
                        "type": "error",
                        "message": "The film couldn't start. Try that again.",
                        "revision": revision,
                    }
                )
            await stream.close()
        finally:
            if not opening.done():
                opening.cancel()
            await asyncio.gather(opening, return_exceptions=True)

    async def provider_event(self, event, revision):
        if revision != self.revision or self.closed:
            return
        kind = event.get("type")
        if kind == "first_frame":
            await self.emit(
                {
                    "type": "playing",
                    "revision": revision,
                    "latency": round(time.monotonic() - self.started, 2),
                }
            )
        elif kind in {"error", "transport_failed", "stream_exhausted"}:
            await self.emit(
                {
                    "type": "error",
                    "revision": revision,
                    "message": "The film connection ended. Your question is still here.",
                }
            )
            if self.stream:
                await self.stream.close()
        elif kind == "deadline_missed":
            await self.emit({"type": "buffering", "revision": revision})
        elif kind == "chunk":
            await self.emit(
                {
                    "type": "segment",
                    "revision": revision,
                    "index": event.get("chunk_index"),
                    "generation_seconds": event.get("generation_seconds"),
                }
            )

    async def offer(self, sdp, revision, *, local=False):
        if revision != self.revision or self.stream is None:
            raise ValueError("Stale film")
        result = await self.stream.answer(sdp, "offer", local=local)
        self.viewer.set()
        return result

    async def interrupt(self):
        self.revision += 1
        work, self.work = self.work, None
        if work and work is not asyncio.current_task():
            work.cancel()
            await asyncio.gather(work, return_exceptions=True)
        if self.lease and self.lease is not asyncio.current_task():
            self.lease.cancel()
            await asyncio.gather(self.lease, return_exceptions=True)
        self.lease = None
        stream, self.stream = self.stream, None
        if stream:
            if stream.latest_frame is not None:
                await asyncio.to_thread(
                    stream.latest_frame.to_image().save,
                    self.directory / "last-frame.jpg",
                )
            await stream.close()
        if self.prepared:
            self.context.append(
                {
                    "interrupted_plan": self.prepared.plan.model_dump(),
                    "heard": "Unknown; do not assume it was completed.",
                }
            )
        self.prepared = None
        self.context = self.context[-8:]
        from gizmo_friend.brain.shows import _atomic_write

        _atomic_write(
            self.directory / "context.json", json.dumps(self.context).encode()
        )
        self.viewer = asyncio.Event()

    async def finish(self, revision):
        if revision != self.revision:
            return
        if self.prepared:
            self.context.append(
                {
                    "completed_narration": self.prepared.plan.narration,
                    "thread": self.prepared.plan.thread,
                }
            )
            self.prepared = None
        await self.interrupt()
        await self.emit({"type": "ended", "revision": self.revision})

    async def expire(self, revision, seconds):
        await asyncio.sleep(seconds)
        if revision == self.revision:
            await self.interrupt()
            await self.emit(
                {"type": "ended", "reason": "timeout", "revision": self.revision}
            )

    async def close(self):
        self.closed = True
        await self.interrupt()
        await self.maker.close()
