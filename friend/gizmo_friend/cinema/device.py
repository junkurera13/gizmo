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
import logging
import math
import os
import wave
from dataclasses import dataclass

from fastapi import WebSocketDisconnect
from PIL import Image, ImageOps

from gizmo_friend.brain.images import ConjuredStill
from gizmo_friend.brain.shows import ShowStore, StoredShow
from gizmo_friend.cinema.routes import FilmBudget
from gizmo_friend.cinema.runtime import CinemaSession
from gizmo_friend.settings import DeviceSettings

FPS = 8
SEGMENT_SECONDS = 5
PCM_BYTES_PER_SECOND = 24_000 * 2
AUDIO_PACKET_BYTES = 11_520
# Prime enough narration before asking the ESP32 to begin the next HTTPS cue
# fetch. The physical device has a three-second live PCM ring; roughly one
# second covers the measured 0.7-0.8 second packet stalls. A longer burst made
# friend-net preempt the JPEG decoder enough to repeat several visible frames.
DEVICE_AUDIO_LEAD_SECONDS = 0.96
DEVICE_WIDTH = 320
DEVICE_HEIGHT = 240
CAPTION_BAND_HEIGHT = 24
# High enough for deliberate limited animation on the ILI9341, with a 125 ms
# frame budget the physical ESP can sustain while the next cue downloads.
DEVICE_JPEG_QUALITY = 65
# Keep every five-second cue below the measured device download budget. The
# physical XIAO played 8 fps cues up to roughly 287 KiB without dropping a
# frame; 256 KiB leaves room for Railway and Wi-Fi variance before the next GO.
MAX_DEVICE_SEGMENT_BYTES = 256 * 1024
# A cue can meet its total budget while one unusually detailed JPEG still
# takes longer than the 125 ms display interval to decode. The accepted local
# film peaked near 7 KiB per frame, so bound both the cue and each frame.
MAX_DEVICE_FRAME_BYTES = 7 * 1024
MIN_DEVICE_JPEG_QUALITY = 1
# aiortc drops the first Director NALs; those packets replay as one frozen
# picture. Wait for a second distinct frame before the 5s clock starts.
WARMUP_DISTINCT_FRAMES = 2

logger = logging.getLogger(__name__)


def frame_image(frame) -> Image.Image:
    """Fit the film above a bottom caption bar, matching the emulator layout."""
    canvas = Image.new("RGB", (DEVICE_WIDTH, DEVICE_HEIGHT), (5, 17, 31))
    canvas.paste(
        ImageOps.fit(
            frame.to_image(),
            (DEVICE_WIDTH, DEVICE_HEIGHT - CAPTION_BAND_HEIGHT),
        ),
        (0, 0),
    )
    return canvas


def jpeg_frame(image: Image.Image, *, quality: int = DEVICE_JPEG_QUALITY) -> bytes:
    encoded = io.BytesIO()
    image.save(encoded, "JPEG", quality=quality, subsampling=2)
    return encoded.getvalue()


def encode_jpeg_frames(
    images: list[Image.Image],
    *,
    max_bytes: int = MAX_DEVICE_SEGMENT_BYTES,
    max_frame_bytes: int = MAX_DEVICE_FRAME_BYTES,
) -> tuple[list[bytes], int]:
    """Use the highest shared quality that fits the cue and decoder budgets."""
    if not images:
        raise ValueError("Empty film segment")
    if max_bytes <= 0 or max_frame_bytes <= 0:
        raise ValueError("Device film byte budgets must be positive")

    def fits(candidate: list[bytes]) -> bool:
        return (
            sum(map(len, candidate)) <= max_bytes
            and max(map(len, candidate)) <= max_frame_bytes
        )

    frames = [jpeg_frame(image) for image in images]
    if fits(frames):
        return frames, DEVICE_JPEG_QUALITY

    selected = None
    low = MIN_DEVICE_JPEG_QUALITY
    high = DEVICE_JPEG_QUALITY - 1
    while low <= high:
        quality = (low + high) // 2
        candidate = [jpeg_frame(image, quality=quality) for image in images]
        if fits(candidate):
            selected = candidate, quality
            low = quality + 1
        else:
            high = quality - 1
    if selected is None:
        raise ValueError("Device film segment is too detailed for its byte budget")
    return selected


def frame_digest(image: Image.Image) -> bytes:
    return hashlib.md5(image.tobytes()).digest()


@dataclass
class DeviceSegment:
    show: StoredShow
    pcm: bytes
    frames: int
    jpeg_quality: int
    mjpeg_bytes: int
    max_jpeg_bytes: int


def encode_segment(
    images: list[Image.Image], pcm: bytes, store: ShowStore, subject: str
) -> DeviceSegment:
    if not images or not pcm:
        raise ValueError("Empty film segment")
    frames, quality = encode_jpeg_frames(images)
    motion = b"".join(frames)
    jpeg = frames[0]
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
    stored = store.put_mjpeg(
        saved.id, motion, frame_count=len(frames), width=320, height=240, fps=FPS
    )
    logger.info(
        "Device film cue encoded frames=%d quality=%d bytes=%d max_frame_bytes=%d budget=%d",
        stored.frame_count,
        quality,
        len(motion),
        max(map(len, frames)),
        MAX_DEVICE_SEGMENT_BYTES,
    )
    return DeviceSegment(
        saved,
        pcm,
        stored.frame_count,
        quality,
        len(motion),
        max(map(len, frames)),
    )


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
        on_presenting=None,
        on_failed=None,
    ):
        self.cinema = cinema
        self.store = store
        self.send = send
        self.acks = acks
        self.next_cue = next_cue
        self.on_segment = on_segment
        self.on_talking = on_talking
        self.on_presenting = on_presenting
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
        last_digest = None
        distinct = 0
        key_frame_seen = False
        with wave.open(io.BytesIO(prepared.wav), "rb") as audio:
            pcm = audio.readframes(audio.getnframes())
        target_frames = math.ceil(prepared.duration * FPS)
        try:
            while revision == self.cinema.revision and next_frame < target_frames:
                frame = await track.recv()
                if getattr(frame, "is_corrupt", False):
                    continue
                if first_time is None and not key_frame_seen:
                    if not getattr(frame, "key_frame", True):
                        continue
                    key_frame_seen = True
                image = await asyncio.to_thread(frame_image, frame)
                digest = frame_digest(image)
                changed = digest != last_digest
                last_digest = digest
                if first_time is None:
                    if changed:
                        distinct += 1
                    if distinct < WARMUP_DISTINCT_FRAMES:
                        continue
                    first_time = frame.time
                timestamp = frame.time - first_time
                if timestamp + 0.001 < next_frame / FPS:
                    continue
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
        position = 0.0
        try:
            index = 0
            item = await preload(index)
            while item is not None and revision == self.cinema.revision:
                segment, event, ready = item
                if not await asyncio.wait_for(ready, 10):
                    raise RuntimeError("Device could not preload film")
                self.acks.pop((event["cue"], "motion"), None)
                caption = ""
                for timing in prepared.timings or []:
                    if timing.get("start", 0.0) <= position < timing.get("end", 0.0):
                        caption = str(timing.get("narration", ""))[:150]
                        break
                await self.send({**event, "go": True, "text": caption})
                # Do not discard the buffered Live fallback until the device has
                # actually accepted the command that starts the prepared film.
                self.cinema.mark_presented(revision)
                if self.on_presenting:
                    await self.on_presenting()
                position += len(segment.pcm) / PCM_BYTES_PER_SECOND
                if self.on_talking:
                    await self.on_talking()
                started = asyncio.get_running_loop().time()

                # WebSocket events are ordered. Put a narration cushion into
                # the device's existing PCM rings before HOLD starts the next
                # HTTPS download; previously HOLD went first, so TLS bursts
                # could interrupt the very first audio packets of every cue.
                prefill_packets = math.ceil(
                    DEVICE_AUDIO_LEAD_SECONDS
                    * PCM_BYTES_PER_SECOND
                    / AUDIO_PACKET_BYTES
                )
                prefill_end = min(
                    len(segment.pcm), prefill_packets * AUDIO_PACKET_BYTES
                )
                for offset in range(0, prefill_end, AUDIO_PACKET_BYTES):
                    await self.send(
                        {
                            "type": "audio",
                            "pcm": base64.b64encode(
                                segment.pcm[offset : offset + AUDIO_PACKET_BYTES]
                            ).decode(),
                        }
                    )

                # The next held cue downloads while the protected narration
                # lead drains. Capture itself has continued in parallel.
                pending = asyncio.create_task(preload(index + 1))
                for offset in range(prefill_end, len(segment.pcm), AUDIO_PACKET_BYTES):
                    wait = (
                        offset / PCM_BYTES_PER_SECOND
                        - (asyncio.get_running_loop().time() - started)
                        - DEVICE_AUDIO_LEAD_SECONDS
                    )
                    if wait > 0:
                        await asyncio.sleep(wait)
                    await self.send(
                        {
                            "type": "audio",
                            "pcm": base64.b64encode(
                                segment.pcm[offset : offset + AUDIO_PACKET_BYTES]
                            ).decode(),
                        }
                    )
                await asyncio.sleep(
                    max(
                        0,
                        len(segment.pcm) / PCM_BYTES_PER_SECOND
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
        elif event["type"] == "buffering":
            # Warmup deadline misses are normal; preload timeouts catch real stalls.
            logger.info("Device film buffering device=%s", self.device)
        elif event["type"] == "error":
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
        elif event["type"] == "status":
            if event.get("phase") in {"thinking", "preparing"}:
                # The body's own working animation covers the wait.
                self.state = "thinking"
                await self.send({"type": "state"})
        elif event["type"] == "ended":
            self.state = "listening"
            await self.send({"type": "glass", "viewing": False, "text": ""})
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
            await self.cinema.ask(text, direction=text)

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
        await self.send({"type": "glass", "viewing": False, "text": ""})
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
                        await self.send({"type": "glass", "viewing": False, "text": ""})
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
