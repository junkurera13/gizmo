"""Camera-demo playback: the real body film protocol over canned local media.

Enabled with GIZMO_DEMO_MOMENT=<id> (e.g. "antarctica"). /ws swaps the live
GizmoSession for DeviceDemo, a scripted loop: power -> boot -> home, first PTT
release -> thinking -> the moment's pre-rendered film, second PTT release ->
thinking -> the follow-up film. Nothing calls Gemini or fal, so a recorded take
cannot stall.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import math
import subprocess
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps

from gizmo_friend.brain.shows import ShowStore
from gizmo_friend.cinema.device import (
    AUDIO_PACKET_BYTES,
    CAPTION_RENDER_LEAD_SECONDS,
    DEVICE_AUDIO_LEAD_SECONDS,
    DEVICE_HEIGHT,
    DEVICE_WIDTH,
    CAPTION_BAND_HEIGHT,
    FPS,
    PCM_BYTES_PER_SECOND,
    SEGMENT_SECONDS,
    caption_at,
    caption_updates,
    device_caption_timings,
    encode_segment,
)
from gizmo_friend.settings import DeviceSettings

logger = logging.getLogger(__name__)

STATIC = Path(__file__).resolve().parents[1] / "static"
BOOT_SECONDS = 3.8


@dataclass(frozen=True)
class DemoStep:
    think_seconds: float
    video: str
    audio: str
    title: str
    beats: tuple[tuple[float, str], ...]


DEMO_MOMENTS: dict[str, tuple[DemoStep, ...]] = {
    "antarctica": (
        DemoStep(
            think_seconds=10.0,
            video="demo-antarctica.mp4",
            audio="demo-antarctica-gizmo.wav",
            title="Antarctica",
            beats=(
                (0.0, "Antarctica is the icy continent at the very bottom of Earth."),
                (5.3, "On a globe, it wraps around the South Pole."),
                (9.1, "Most of it is covered by a huge sheet of ice,"),
                (12.45, "with bright glaciers, tall mountains, and deep blue cracks."),
                (18.1, "Along the coast, you can see floating icebergs and penguins,"),
                (22.4, "while the middle is a cold, windy white desert."),
            ),
        ),
        DemoStep(
            think_seconds=5.0,
            video="demo-antarctica-followup.mp4",
            audio="demo-antarctica-followup-gizmo.wav",
            title="Penguins beyond Antarctica",
            beats=(
                (
                    0.0,
                    "Yes! Penguins also live in South America, southern Africa, Australia, "
                    "New Zealand, and the Galapagos Islands. Not every penguin lives somewhere icy.",
                ),
            ),
        ),
    ),
}


def _decode_frames(video: Path, workdir: Path) -> list[Image.Image]:
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y", "-i", str(video),
            "-vf", f"fps={FPS}", "-q:v", "3", str(workdir / "f%04d.jpg"),
        ],
        check=True,
    )
    images = []
    for frame_path in sorted(workdir.glob("f*.jpg")):
        with Image.open(frame_path) as raw:
            canvas = Image.new("RGB", (DEVICE_WIDTH, DEVICE_HEIGHT), (5, 17, 31))
            canvas.paste(
                ImageOps.fit(
                    raw.convert("RGB"),
                    (DEVICE_WIDTH, DEVICE_HEIGHT - CAPTION_BAND_HEIGHT),
                ),
                (0, 0),
            )
            images.append(canvas)
    return images


def _read_pcm(audio: Path) -> bytes:
    with wave.open(str(audio), "rb") as source:
        if (
            source.getframerate() != 24_000
            or source.getnchannels() != 1
            or source.getsampwidth() != 2
        ):
            raise ValueError(f"{audio.name} must be 24kHz pcm_s16le mono")
        return source.readframes(source.getnframes())


def encode_step(step: DemoStep, store: ShowStore) -> list:
    """Decode one canned step into held-cue segments the body already speaks."""
    with tempfile.TemporaryDirectory(prefix="gizmo-demo-") as tmp:
        images = _decode_frames(STATIC / step.video, Path(tmp))
    if not images:
        raise ValueError(f"No frames decoded from {step.video}")
    pcm = _read_pcm(STATIC / step.audio)
    # The narration clock drives playback; pad a short tail of video silence.
    needed = math.ceil(len(images) * PCM_BYTES_PER_SECOND / FPS)
    if len(pcm) < needed:
        pcm += b"\x00" * (needed - len(pcm))
    segments = []
    cue_frames = FPS * SEGMENT_SECONDS
    for index in range(0, len(images), cue_frames):
        chunk = images[index : index + cue_frames]
        audio_slice = pcm[index * 6000 : (index + len(chunk)) * 6000]
        segments.append(encode_segment(chunk, audio_slice, store, step.title))
    return segments


def step_timings(step: DemoStep) -> list[dict]:
    timings = []
    for index, (start, text) in enumerate(step.beats):
        end = (
            step.beats[index + 1][0]
            if index + 1 < len(step.beats)
            else start + 30.0
        )
        timings.append({"start": start, "end": end, "narration": text})
    return timings


class DeviceDemo:
    """Scripted /ws session: power, home, PTT, thinking, then canned films."""

    def __init__(self, socket, root: Path, device: str, moment: str):
        self.socket = socket
        self.root = root
        self.device = device
        self.steps = list(DEMO_MOMENTS[moment])
        self.settings = DeviceSettings(root / "devices" / device / "settings.json")
        self.store = ShowStore(root / "devices" / device, device_id=device)
        self.lock = asyncio.Lock()
        self.acks: dict[tuple[int, str], asyncio.Future] = {}
        self.mic = bytearray()
        self.recording = False
        self.powered = True
        self.state = "listening"
        self.playback: asyncio.Task | None = None
        self.step_index = 0
        self._segments: dict[int, list] = {}

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

    async def _segments_for(self, index: int) -> list:
        cached = self._segments.get(index)
        if cached is None:
            cached = await asyncio.to_thread(
                encode_step, self.steps[index], self.store
            )
            self._segments[index] = cached
        return cached

    async def _play_step(self, index: int) -> None:
        step = self.steps[index]
        self.state = "thinking"
        await self.send({"type": "state"})
        segments, _ = await asyncio.gather(
            self._segments_for(index),
            asyncio.sleep(step.think_seconds),
        )
        captions = device_caption_timings(step_timings(step))
        position = 0.0
        pending = None
        caption_task = None
        cue_base = (index + 1) * 100

        async def preload(number: int):
            if number >= len(segments):
                return None
            segment = segments[number]
            cue = cue_base + number + 1
            ready = asyncio.get_running_loop().create_future()
            self.acks[(cue, "motion")] = ready
            event = {
                "type": "glass",
                "viewing": True,
                "still": segment.show.still_url,
                "frames": segment.show.frames_url,
                "cue": cue,
                "subject": step.title,
            }
            await self.send({**event, "hold": True})
            return segment, event, ready

        try:
            item = await preload(0)
            number = 0
            while item is not None:
                segment, event, ready = item
                if not await asyncio.wait_for(ready, 10):
                    raise RuntimeError("Device could not preload film")
                self.acks.pop((event["cue"], "motion"), None)
                segment_seconds = len(segment.pcm) / PCM_BYTES_PER_SECOND
                segment_end = position + segment_seconds
                caption = caption_at(
                    captions,
                    min(
                        segment_end - 1 / PCM_BYTES_PER_SECOND,
                        position + CAPTION_RENDER_LEAD_SECONDS,
                    ),
                )
                updates = caption_updates(captions, position, segment_end)
                await self.send({**event, "go": True, "text": caption})
                self.state = "talking"
                await self.send({"type": "state"})
                position = segment_end
                started = asyncio.get_running_loop().time()

                async def update_captions() -> None:
                    for due, text in updates:
                        wait = due - (asyncio.get_running_loop().time() - started)
                        if wait > 0:
                            await asyncio.sleep(wait)
                        await self.send({"type": "line", "text": text})

                caption_task = asyncio.create_task(update_captions())
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
                pending = asyncio.create_task(preload(number + 1))
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
                        segment_seconds
                        - (asyncio.get_running_loop().time() - started),
                    )
                )
                await caption_task
                caption_task = None
                item = await pending
                pending = None
                number += 1
        finally:
            if caption_task:
                caption_task.cancel()
                await asyncio.gather(caption_task, return_exceptions=True)
            if pending:
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
            self.acks.clear()
        self.state = "listening"
        await self.send({"type": "glass", "viewing": False, "text": ""})
        await self.send({"type": "state"})

    async def _warm(self) -> None:
        """Encode every step right after connect so thinking time stays pure."""
        for index in range(len(self.steps)):
            await self._segments_for(index)

    async def _cancel_playback(self) -> None:
        playback, self.playback = self.playback, None
        if playback and playback is not asyncio.current_task():
            playback.cancel()
            await asyncio.gather(playback, return_exceptions=True)
        self.acks.clear()

    async def _next_step(self) -> None:
        index = min(self.step_index, len(self.steps) - 1)
        try:
            await self._play_step(index)
        except asyncio.CancelledError:
            # Interrupted take replays the same step on the next press.
            raise
        except Exception as error:  # noqa: BLE001 - never die mid-take
            logger.warning("Demo step failed: error=%s", type(error).__name__)
            self.state = "listening"
            await self.send({"type": "glass", "viewing": False, "text": ""})
            await self.send({"type": "state"})
            return
        # A completed cycle wraps so every full pass is film one + film two.
        self.step_index = (self.step_index + 1) % len(self.steps)

    async def run(self):
        await self.socket.accept()
        await self.send(
            {
                "type": "hello",
                "protocol_version": 1,
                "state": self.state,
                "power": self.powered,
                "screen": self.powered,
                "settings": self.settings.public(),
            }
        )
        await self.send({"type": "glass", "viewing": False, "text": ""})
        warm = asyncio.create_task(self._warm())
        try:
            while True:
                message = await self.socket.receive_json()
                kind = message.get("type")
                if kind == "glass_ready":
                    future = self.acks.get((message.get("cue"), message.get("kind")))
                    if future and not future.done():
                        future.set_result(message.get("ok") is True)
                elif kind == "power":
                    on = message.get("on") is True
                    if on and not self.powered:
                        self.powered = True
                        self.state = "booting"
                        await self.send({"type": "state"})
                        await asyncio.sleep(BOOT_SECONDS)
                        if self.powered:
                            self.state = "listening"
                            await self.send({"type": "state"})
                    elif not on and self.powered:
                        self.powered = False
                        await self._cancel_playback()
                        self.state = "powered_off"
                        await self.send({"type": "glass", "viewing": False, "text": ""})
                        await self.send({"type": "state"})
                elif kind == "ptt":
                    active = message.get("active") is True
                    if not self.powered:
                        continue
                    if active:
                        self.recording = True
                        self.mic.clear()
                        await self._cancel_playback()
                        self.state = "listening"
                        await self.send({"type": "interrupted"})
                        await self.send(
                            {"type": "glass", "viewing": False, "text": ""}
                        )
                        await self.send({"type": "state"})
                    else:
                        self.recording = False
                        self.mic.clear()
                        self.playback = asyncio.create_task(self._next_step())
                elif kind in {"audio", "mic"} and self.recording:
                    raw = message.get("pcm", "")
                    if isinstance(raw, str) and len(raw) < 100_000:
                        try:
                            pcm = base64.b64decode(raw, validate=True)
                        except ValueError:
                            continue
                        if len(self.mic) + len(pcm) <= 20 * 48000:
                            self.mic.extend(pcm)
                elif kind == "text":
                    if self.powered and not self.recording:
                        self.playback = asyncio.create_task(self._next_step())
                elif kind == "select":
                    if self.settings.select():
                        await self.send(self.settings.snapshot())
                    else:
                        await self._cancel_playback()
                        self.state = "listening"
                        await self.send({"type": "glass", "viewing": False, "text": ""})
                        await self.send({"type": "state"})
                elif kind == "navigate":
                    self.settings.navigate(message.get("direction"))
                    if self.settings.open:
                        await self._cancel_playback()
                    await self.send(self.settings.snapshot())
        finally:
            warm.cancel()
            await asyncio.gather(warm, return_exceptions=True)
            await self._cancel_playback()
