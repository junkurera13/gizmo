"""XIAO film playback: buffer five seconds of Director, preload, then play PCM.

Uses the existing authenticated Show routes and held-cue firmware contract.
The browser stays the full-resolution reference. Physical synchronization and
PSRAM/audio concurrency must still be accepted on a flashed board.

`DeviceFilmPlayer` is the reusable glass/PCM engine. Friend owns conversation and
invokes it as a capability. `DeviceFilm` remains a standalone socket loop for
desk experiments; `/ws` no longer swaps the whole session into it.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import math
import os
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path

import imageio_ffmpeg
from fastapi import WebSocketDisconnect
from PIL import Image, ImageOps

from gizmo_friend.brain.images import ConjuredStill
from gizmo_friend.brain.shows import ConjuredClip, ShowStore, StoredShow
from gizmo_friend.cinema.routes import FilmBudget
from gizmo_friend.cinema.runtime import CinemaSession
from gizmo_friend.settings import DeviceSettings

FPS = 12
SEGMENT_SECONDS = 5


@dataclass
class DeviceSegment:
    show: StoredShow
    pcm: bytes
    frames: int


def encode_segment(
    images: list[Image.Image], pcm: bytes, store: ShowStore, subject: str
) -> DeviceSegment:
    if not images or not pcm:
        raise ValueError("Empty film segment")
    encoded = io.BytesIO()
    images[0].save(encoded, "JPEG", quality=85, subsampling=2)
    jpeg = encoded.getvalue()
    still = ConjuredStill(
        subject=subject,
        jpeg=jpeg,
        prompt=subject,
        model="minimax/h3-max/director",
        width=320,
        height=240,
        source_width=320,
        source_height=240,
        latency_seconds=0,
    )
    saved = store.save(still, session_id="cinema", motion=subject)
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "segment.mp4"
        writer = imageio_ffmpeg.write_frames(
            str(path), (320, 240), fps=FPS, codec="libx264", ffmpeg_timeout=15
        )
        next(writer)
        try:
            for image in images:
                writer.send(image.tobytes())
        finally:
            writer.close()
        clip = ConjuredClip(
            motion=subject,
            mp4=path.read_bytes(),
            prompt=subject,
            model="minimax/h3-max/director",
            request_id=saved.id,
            source_image_sha256=hashlib.sha256(jpeg).hexdigest(),
            latency_seconds=0,
            expanded_prompt=None,
            timings={},
        )
        store.save_clip(saved.id, clip)
    frames = store.mjpeg(saved.id, width=320, height=240, fps=FPS)
    return DeviceSegment(saved, pcm, frames.frame_count)


class DeviceFilmPlayer:
    """Held-cue MJPEG + original PCM playback for an active CinemaSession."""

    def __init__(
        self,
        cinema,
        store,
        send,
        acks,
        *,
        next_cue=None,
        on_segment=None,
        on_talking=None,
        on_failed=None,
    ):
        self.cinema = cinema
        self.store = store
        self.send = send
        self.acks = acks
        self.next_cue = next_cue
        self.on_segment = on_segment
        self.on_talking = on_talking
        self.on_failed = on_failed
        self.playback = None

    def cue_for(self, revision, index):
        if self.next_cue is not None:
            return self.next_cue()
        return revision * 100 + index + 1

    async def cancel_playback(self):
        playback, self.playback = self.playback, None
        if playback and playback is not asyncio.current_task():
            playback.cancel()
            await asyncio.gather(playback, return_exceptions=True)
        self.acks.clear()

    async def capture(self, track, queue, prepared, revision):
        images = []
        first_time = None
        next_frame = 0
        pcm_offset = 0
        with wave.open(io.BytesIO(prepared.wav), "rb") as audio:
            pcm = audio.readframes(audio.getnframes())
        target_frames = math.ceil(prepared.duration * FPS)
        try:
            while revision == self.cinema.revision and next_frame < target_frames:
                frame = await track.recv()
                if first_time is None:
                    first_time = frame.time
                timestamp = frame.time - first_time
                if timestamp + 0.001 < next_frame / FPS:
                    continue
                image = await asyncio.to_thread(
                    lambda frame=frame: ImageOps.pad(
                        frame.to_image(), (320, 240), color=(5, 17, 31)
                    )
                )
                while (
                    next_frame / FPS <= timestamp + 0.001 and next_frame < target_frames
                ):
                    images.append(image.copy())
                    next_frame += 1
                    if (
                        len(images) == FPS * SEGMENT_SECONDS
                        or next_frame == target_frames
                    ):
                        end = min(len(pcm), next_frame * 48000 // FPS)
                        segment = await asyncio.to_thread(
                            encode_segment,
                            images,
                            pcm[pcm_offset:end],
                            self.store,
                            prepared.plan.title,
                        )
                        images = []
                        pcm_offset = end
                        await queue.put(segment)
            await queue.put(None)
        finally:
            track.stop()

    async def play(self, revision):
        stream = self.cinema.stream
        prepared = self.cinema.prepared
        if stream is None or prepared is None:
            return
        video_ready = getattr(stream, "video_ready", None)
        if video_ready is not None:
            async with asyncio.timeout(20):
                await video_ready.wait()
        if (
            revision != self.cinema.revision
            or stream.closed
            or "video" not in getattr(stream, "tracks", {})
        ):
            return
        queue = asyncio.Queue(maxsize=2)
        capture = asyncio.create_task(
            self.capture(
                stream.relay.subscribe(stream.tracks["video"]),
                queue,
                prepared,
                revision,
            )
        )

        async def preload(index):
            segment = await asyncio.wait_for(queue.get(), 40 if index == 0 else 15)
            if segment is None:
                return None
            cue = self.cue_for(revision, index)
            ready = asyncio.get_running_loop().create_future()
            self.acks[(cue, "motion")] = ready
            event = {
                "type": "glass",
                "viewing": True,
                "still": segment.show.still_url,
                "frames": segment.show.frames_url,
                "cue": cue,
                "subject": prepared.plan.title,
            }
            await self.send({**event, "hold": True})
            if self.on_segment:
                await self.on_segment(segment)
            return segment, event, ready

        pending = None
        try:
            index = 0
            item = await preload(index)
            while item is not None and revision == self.cinema.revision:
                segment, event, ready = item
                if not await asyncio.wait_for(ready, 10):
                    raise RuntimeError("Device could not preload film")
                self.acks.pop((event["cue"], "motion"), None)
                await self.send({**event, "go": True})
                # The next held cue downloads during this segment's narration.
                pending = asyncio.create_task(preload(index + 1))
                if self.on_talking:
                    await self.on_talking()
                started = asyncio.get_running_loop().time()
                for offset in range(0, len(segment.pcm), 11520):
                    wait = (
                        offset / 48000
                        - (asyncio.get_running_loop().time() - started)
                        - 0.48
                    )
                    if wait > 0:
                        await asyncio.sleep(wait)
                    await self.send(
                        {
                            "type": "audio",
                            "pcm": base64.b64encode(
                                segment.pcm[offset : offset + 11520]
                            ).decode(),
                        }
                    )
                await asyncio.sleep(
                    max(
                        0,
                        len(segment.pcm) / 48000
                        - (asyncio.get_running_loop().time() - started),
                    )
                )
                item = await pending
                pending = None
                index += 1
            if revision == self.cinema.revision:
                await self.cinema.finish(revision)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - isolate device/provider failures
            await self.cinema.interrupt()
            if self.on_failed:
                await self.on_failed()
            else:
                await self.send({"type": "interrupted"})
                await self.send(
                    {
                        "type": "error",
                        "message": "Film playback stopped; the last picture is retained.",
                    }
                )
        finally:
            if pending:
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
            capture.cancel()
            await asyncio.gather(capture, return_exceptions=True)
            self.acks.clear()


class DeviceFilm:
    def __init__(self, socket, root, device):
        self.socket = socket
        self.root = root
        self.device = device
        self.settings = DeviceSettings(root / "devices" / device / "settings.json")
        self.store = ShowStore(root / "devices" / device, device_id=device)
        self.cinema = CinemaSession(
            root / "cinema" / device, os.environ["FAL_KEY"], self.event
        )
        self.budget = FilmBudget(root)
        self.lock = asyncio.Lock()
        self.input_task = None
        self.acks = {}
        self.mic = bytearray()
        self.recording = False
        self.powered = True
        self.state = "listening"
        self.player = DeviceFilmPlayer(
            self.cinema,
            self.store,
            self.send,
            self.acks,
            on_talking=self._mark_talking,
        )

    @property
    def playback(self):
        return self.player.playback

    @playback.setter
    def playback(self, value):
        self.player.playback = value

    async def send(self, event):
        async with self.lock:
            await self.socket.send_json(
                {
                    "state": self.state,
                    "power": self.powered,
                    "screen": self.powered,
                    "transport": "director",
                    **event,
                }
            )

    async def _mark_talking(self):
        self.state = "talking"
        await self.send({"type": "state"})

    async def event(self, event):
        if event["type"] == "ready":
            self.playback = asyncio.create_task(self.player.play(event["revision"]))
            self.cinema.viewer.set()
        elif event["type"] in {"error", "buffering"}:
            # Don't let a provider stall advance the independent device PCM clock.
            await self.stop()
            await self.send(
                {
                    "type": "error",
                    "message": event.get(
                        "message", "Film paused while its pictures catch up."
                    ),
                }
            )
        elif event["type"] == "ended":
            self.state = "listening"
            await self.send({"type": "state"})

    async def stop(self):
        await self.player.cancel_playback()
        await self.cinema.interrupt()
        self.state = "listening"
        await self.send({"type": "interrupted"})

    async def ask(self, text):
        if (
            self.powered
            and text.strip()
            and await asyncio.to_thread(self.budget.reserve, self.device)
        ):
            await self.cinema.ask(text)

    async def spoken(self, pcm):
        audio = io.BytesIO()
        with wave.open(audio, "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(24000)
            out.writeframes(pcm)
        try:
            text = await self.cinema.maker.transcribe(audio.getvalue(), "audio/wav")
            await self.ask(text)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - isolate device/provider failures
            await self.send(
                {"type": "error", "message": "I couldn't hear that. Please try again."}
            )

    async def run(self):
        await self.socket.accept()
        await self.send(
            {"type": "hello", "protocol_version": 1, "settings": self.settings.public()}
        )
        await self.send({"type": "glass", "viewing": False})
        try:
            while True:
                message = await self.socket.receive_json()
                kind = message.get("type")
                if kind == "glass_ready":
                    future = self.acks.get((message.get("cue"), message.get("kind")))
                    if future and not future.done():
                        future.set_result(message.get("ok") is True)
                elif kind == "ptt":
                    self.recording = message.get("active") is True
                    if self.recording:
                        if self.input_task:
                            self.input_task.cancel()
                            await asyncio.gather(
                                self.input_task, return_exceptions=True
                            )
                        await self.stop()
                        self.mic.clear()
                    elif self.mic:
                        self.input_task = asyncio.create_task(
                            self.spoken(bytes(self.mic))
                        )
                        self.mic.clear()
                elif kind in {"audio", "mic"} and self.recording:
                    raw = message.get("pcm", "")
                    if isinstance(raw, str) and len(raw) < 100_000:
                        try:
                            pcm = base64.b64decode(raw, validate=True)
                        except ValueError:
                            continue
                        if len(self.mic) + len(pcm) <= 20 * 48000:
                            self.mic.extend(pcm)
                elif kind == "select":
                    if self.settings.select():
                        await self.send(self.settings.snapshot())
                    else:
                        await self.stop()
                        await self.send({"type": "glass", "viewing": False})
                elif kind == "navigate":
                    self.settings.navigate(message.get("direction"))
                    if self.settings.open:
                        await self.stop()
                    await self.send(self.settings.snapshot())
                elif kind == "power":
                    self.powered = message.get("on") is True
                    if not self.powered:
                        await self.stop()
                    await self.send({"type": "state"})
                elif kind == "text" and isinstance(message.get("text"), str):
                    await self.stop()
                    await self.ask(message["text"][:1200])
        except WebSocketDisconnect:
            pass
        finally:
            if self.input_task:
                self.input_task.cancel()
                await asyncio.gather(self.input_task, return_exceptions=True)
            if self.playback:
                self.playback.cancel()
                await asyncio.gather(self.playback, return_exceptions=True)
            await self.cinema.close()
