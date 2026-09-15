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
        self.jobs: list[asyncio.Task] = []
        self.revision = 0
        self.request_id = None
        try:
            self.context = json.loads((directory / "context.json").read_text())[-8:]
            if not isinstance(self.context, list):
                self.context = []
        except (OSError, ValueError, TypeError):
            self.context = []
        self.prepared = None
        self.pending: str | None = None
        self.presented_revision: int | None = None
        self.viewer = asyncio.Event()
        self.closed = False
        self.turns = 0
        self.started = 0.0
        self.marks: dict[str, float] = {}
        self.local = False
        self.ice_servers: list[dict] = []

    def current(self, revision) -> bool:
        return revision == self.revision and not self.closed

    def mark(self, name: str) -> None:
        self.marks[name] = round(time.monotonic() - self.started, 3)

    def spawn(self, work) -> asyncio.Task:
        task = asyncio.create_task(work)
        self.jobs.append(task)
        return task

    async def publish(self, event):
        event = {**event, "request_id": self.request_id}
        record = {**event, "at": round(time.monotonic(), 3)}
        with (self.directory / "events.jsonl").open("a") as log:
            log.write(json.dumps(record) + "\n")
        await self._deliver(event)

    async def ask(self, text, *, request_id=None, direction="") -> bool:
        text = " ".join(text.split())[:1200]
        if not text or self.closed:
            return False
        if self.turns >= 8:
            await self.emit(
                {
                    "type": "error",
                    "message": "This film session has reached its limit. Start a new session to continue.",
                }
            )
            return False
        await self.interrupt()
        self.request_id = request_id
        self.turns += 1
        revision = self.revision
        self.started = time.monotonic()
        self.marks = {}
        self.context.append({"user": text})
        self.pending = text
        self.work = asyncio.create_task(self.run(text, revision, direction))
        return True

    async def run(self, text, revision, direction=""):
        stream = self.stream_factory(
            self.key, lambda event: self.provider_event(event, revision)
        )
        self.stream = stream
        opening = self.spawn(stream.connect())
        image_upload = None
        audio_upload = None
        try:
            await self.emit(
                {
                    "type": "status",
                    "phase": "thinking",
                    "revision": revision,
                }
            )
            context = [entry for entry in self.context[-8:] if not entry.get("undelivered")]
            if direction:
                plan = await self.maker.plan(text, context, direction=direction)
            else:
                plan = await self.maker.plan(text, context)
            self.mark("plan")
            if not self.current(revision):
                return
            await self.emit(
                {
                    "type": "plan",
                    "title": plan.title,
                    "revision": revision,
                    "ice_servers": list(self.ice_servers),
                }
            )
            # Last-frame continuation is independent of TTS. Do not wait for it
            # before synthesizing, and never start Director on a partial WAV.
            image_upload = self._start_anchor_upload(plan)
            prepared = await self.maker.synthesize(plan)
            self.mark("synthesize")
            if not self.current(revision):
                return
            if not prepared.wav:
                raise RuntimeError("The narration recording is empty.")
            self.prepared = prepared
            audio_upload = self.spawn(self.maker.upload_audio(prepared.wav))
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
            audio_url = await audio_upload
            self.mark("audio_upload")
            if not self.current(revision):
                return
            if not audio_url:
                raise RuntimeError("The narration recording could not be uploaded.")
            prepared.audio_url = audio_url
            # Duration is known from PCM. Ready still waits for the hosted WAV
            # so Director is never asked to generate against a missing soundtrack.
            # Browser ICE starts from the earlier plan event.
            await self.emit(
                {
                    "type": "ready",
                    "revision": revision,
                    "title": plan.title,
                    "duration": prepared.duration,
                    "narration": plan.narration,
                    "timings": prepared.timings,
                }
            )
            async with asyncio.timeout(30):
                await opening
            self.mark("director_peer")
            if not self.current(revision):
                return
            # The browser only sends its offer once the film beat actually plays,
            # after any earlier beats in the turn — that can be minutes.
            async with asyncio.timeout(180):
                await self.viewer.wait()
            self.mark("viewer")
            if not self.current(revision):
                return
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
                "audio_url": audio_url,
            }
            if image_upload is not None:
                try:
                    async with asyncio.timeout(10):
                        image_url = await image_upload
                except Exception:  # noqa: BLE001 - a missing anchor must not kill the film
                    image_url = None
                if image_url:
                    configuration["image_url"] = image_url
            if not self.current(revision):
                return
            self.mark("configure")
            stream.send(configuration)
            # A lost browser cannot leave a paid infinite generation session running.
            self.lease = asyncio.create_task(
                self.expire(revision, min(100, prepared.duration + 35))
            )
            async with asyncio.timeout(35):
                await stream.first_frame.wait()
            self.mark("first_frame")
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - report a failed film and close its peer
            logger.warning(
                "Cinema failed: revision=%s error=%s detail=%s",
                revision,
                type(error).__name__,
                error,
            )
            self._mark_undelivered()
            if self.current(revision):
                await self.emit(
                    {
                        "type": "error",
                        "message": "The film couldn't start. Try that again.",
                        "revision": revision,
                    }
                )
            await stream.close()
        finally:
            await self._cancel_jobs(opening, audio_upload, image_upload)

    def _start_anchor_upload(self, plan):
        anchor = self.directory / "last-frame.jpg"
        if plan.relation == "new" or not anchor.is_file():
            return None
        jpeg = anchor.read_bytes()
        if not jpeg:
            return None

        async def upload():
            async with asyncio.timeout(10):
                return await self.maker.upload.upload(
                    jpeg,
                    "image/jpeg",
                    file_name="gizmo-continuation.jpg",
                )

        return self.spawn(upload())

    async def _cancel_jobs(self, *tasks):
        pending = []
        for task in (*self.jobs, *tasks):
            if (
                task
                and not task.done()
                and task is not asyncio.current_task()
                and task not in pending
            ):
                pending.append(task)
                task.cancel()
        self.jobs = [
            task for task in self.jobs if task not in pending and not task.done()
        ]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    async def provider_event(self, event, revision):
        if not self.current(revision):
            return
        kind = event.get("type")
        if kind == "ice_servers":
            servers = [] if self.local else list(event.get("ice_servers") or [])
            self.ice_servers = servers
            await self.emit({"type": "ice", "servers": servers, "revision": revision})
            return
        if kind == "first_frame":
            logger.info(
                "Cinema first frame: latency=%.2fs phases=%s",
                time.monotonic() - self.started,
                self.marks,
            )
            await self.emit(
                {
                    "type": "playing",
                    "revision": revision,
                    "latency": round(time.monotonic() - self.started, 2),
                    "phases": dict(self.marks),
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

    async def offer(self, sdp, revision, *, local=False, start=True):
        """Attach a viewer. With start=False the peer is connected early and
        generation waits for `watch`, so a screen can finish an opener first
        without losing the live film's opening seconds."""
        if revision != self.revision or self.stream is None:
            raise ValueError("Stale film")
        # Configure must be allowed to start before answer() waits for tracks.
        # Director publishes those tracks after configure; setting the viewer
        # only after a successful answer deadlocks the production hop and the
        # browser then reports a dropped picture.
        if start:
            self.viewer.set()
        result = await self.stream.answer(sdp, "offer", local=local)
        if revision != self.revision or self.stream is None or self.stream.closed:
            raise ValueError("Stale film")
        return result

    def watch(self, revision) -> bool:
        if revision != self.revision or self.stream is None or self.stream.closed:
            return False
        self.viewer.set()
        return True

    def mark_presented(self, revision) -> bool:
        if revision != self.revision or self.prepared is None:
            return False
        self.presented_revision = revision
        return True

    async def interrupt(self):
        active_revision = self.revision
        self.revision += 1
        work, self.work = self.work, None
        if work and work is not asyncio.current_task():
            work.cancel()
            await asyncio.gather(work, return_exceptions=True)
        await self._cancel_jobs()
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
        if self.prepared and self.presented_revision == active_revision:
            self.context.append(
                {
                    "interrupted_plan": self.prepared.plan.model_dump(),
                    "heard": "Unknown; do not assume it was completed.",
                }
            )
            self.pending = None
        else:
            self._mark_undelivered()
        self.prepared = None
        self.presented_revision = None
        self.context = self.context[-8:]
        from gizmo_friend.brain.shows import _atomic_write

        _atomic_write(
            self.directory / "context.json", json.dumps(self.context).encode()
        )
        self.viewer = asyncio.Event()

    def _mark_undelivered(self):
        """A pending ask that never produced a film must not look answerable
        to the next plan — otherwise Cinema re-answers an old question."""
        text, self.pending = self.pending, None
        if not text:
            return
        for entry in reversed(self.context):
            if entry.get("user") == text:
                entry["undelivered"] = "No film was made or played for this ask."
                return

    async def finish(self, revision):
        if revision != self.revision:
            return
        self.pending = None
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
