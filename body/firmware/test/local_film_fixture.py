"""Deterministic film server for physical XIAO acceptance and demo playback.

This deliberately speaks the production Friend wire contract while using no
Gemini, Fal, H3, or Railway. Point the device's F URL at this Mac, press and
release PTT, and the fixture sends six held five-second MJPEG cues plus paced
24 kHz PCM. A moving scan bar and an audible tick share each whole-second
boundary so a phone video can reveal drift, tearing, stalls, or catch-up.

Pass --demo-pompeii to replace the diagnostic pattern with the bundled,
finished 37-second Pompeii film and narration.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import io
import math
import socket
import sys
import tempfile
import time
import wave
from array import array
from dataclasses import dataclass
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response
from PIL import Image, ImageDraw, ImageFont

from gizmo_friend.brain.show_media import encode_mjpeg


WIDTH = 320
HEIGHT = 240
FPS = 8
SECONDS = 30
SEGMENT_SECONDS = 5
# Keep in sync with firmware include/gizmo/screens.h. Film playback repaints
# only the area above this static strip after its first full-screen frame.
CAPTION_BAND_HEIGHT = 24
WIRE_RATE = 24_000
PCM_CHUNK_BYTES = 11_520
ROOT = Path(__file__).resolve().parents[3]
POMPEII_VIDEO = ROOT / "friend/gizmo_friend/static/demo-pompeii-polished.mp4"
POMPEII_AUDIO = ROOT / "friend/gizmo_friend/static/demo-pompeii.wav"


@dataclass(frozen=True)
class Segment:
    show_id: str
    still: bytes
    motion: bytes
    frame_count: int
    pcm: bytes


@dataclass(frozen=True)
class Fixture:
    fps: int
    seconds: float
    segment_seconds: int
    segments: tuple[Segment, ...]
    label: str
    caption: str


def _font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow before scalable load_default
        return ImageFont.load_default()


def _jpeg(image: Image.Image) -> bytes:
    encoded = io.BytesIO()
    image.save(
        encoded,
        "JPEG",
        quality=65,
        subsampling=2,
        progressive=False,
        optimize=False,
    )
    return encoded.getvalue()


def _frame(index: int, fps: int, seconds: int) -> bytes:
    second = index // fps
    phase = index % fps
    palettes = (
        ((8, 34, 57), (46, 211, 183), (255, 222, 89)),
        ((43, 24, 72), (238, 93, 145), (111, 222, 255)),
        ((15, 55, 42), (137, 223, 88), (255, 174, 71)),
        ((61, 25, 20), (255, 108, 74), (255, 227, 130)),
        ((21, 35, 75), (93, 154, 255), (223, 132, 255)),
        ((58, 42, 11), (255, 190, 55), (119, 239, 208)),
    )
    background, accent, highlight = palettes[(second // SEGMENT_SECONDS) % len(palettes)]
    image = Image.new("RGB", (WIDTH, HEIGHT), background)
    draw = ImageDraw.Draw(image)

    # High-contrast horizontal structure makes partial panel refreshes obvious.
    for y in range(0, 192, 24):
        shade = tuple(min(255, value + (12 if (y // 24) % 2 else 0)) for value in background)
        draw.rectangle((0, y, WIDTH, y + 23), fill=shade)

    sweep = int((phase / fps) * (WIDTH + 36)) - 18
    draw.rectangle((sweep, 0, sweep + 18, 191), fill=highlight)
    orbit_x = int(WIDTH / 2 + math.sin(index * 0.19) * 105)
    orbit_y = int(88 + math.cos(index * 0.13) * 52)
    draw.ellipse((orbit_x - 18, orbit_y - 18, orbit_x + 18, orbit_y + 18), fill=accent)
    draw.ellipse((orbit_x - 6, orbit_y - 6, orbit_x + 6, orbit_y + 6), fill=highlight)

    # The bottom 48 px matches the production caption band. The number changes
    # at the same instant as the audio tick, making A/V drift visible on video.
    draw.rectangle((0, 192, WIDTH, HEIGHT), fill=(5, 17, 31))
    label = f"LOCAL FILM  {second + 1:02d}/{seconds:02d}"
    draw.text((12, 202), label, fill=(245, 247, 250), font=_font(22))
    progress = int(WIDTH * (index + 1) / (seconds * fps))
    draw.rectangle((0, 236, progress, 239), fill=accent)
    return _jpeg(image)


def _soundtrack(seconds: int) -> bytes:
    samples = array("h")
    for sample_index in range(seconds * WIRE_RATE):
        t = sample_index / WIRE_RATE
        within_second = t - math.floor(t)
        base = 1_650 * math.sin(2 * math.pi * 196 * t)
        # A crisp but not harsh marker starts exactly at each visual second.
        tick = 7_000 * math.sin(2 * math.pi * 880 * t) if within_second < 0.075 else 0
        samples.append(int(base + tick))
    if sys.byteorder != "little":
        samples.byteswap()
    return samples.tobytes()


def build_fixture(*, fps: int = FPS, seconds: int = SECONDS) -> Fixture:
    if fps <= 0 or seconds <= 0 or seconds % SEGMENT_SECONDS:
        raise ValueError("fps and seconds must be positive; seconds must divide into 5-second cues")
    soundtrack = _soundtrack(seconds)
    frames = [_frame(index, fps, seconds) for index in range(seconds * fps)]
    segments = []
    frames_per_segment = fps * SEGMENT_SECONDS
    pcm_per_segment = WIRE_RATE * 2 * SEGMENT_SECONDS
    for index in range(seconds // SEGMENT_SECONDS):
        first = index * frames_per_segment
        last = first + frames_per_segment
        show_id = f"{index + 1:032x}"
        selected = frames[first:last]
        segments.append(
            Segment(
                show_id=show_id,
                still=selected[0],
                motion=b"".join(selected),
                frame_count=len(selected),
                pcm=soundtrack[index * pcm_per_segment : (index + 1) * pcm_per_segment],
            )
        )
    return Fixture(
        fps,
        float(seconds),
        SEGMENT_SECONDS,
        tuple(segments),
        "30-second diagnostic",
        "LOCAL FILM",
    )


def _split_mjpeg(data: bytes) -> list[bytes]:
    frames = []
    cursor = 0
    while cursor < len(data):
        start = data.find(b"\xff\xd8", cursor)
        if start < 0:
            break
        end = data.find(b"\xff\xd9", start + 2)
        if end < 0:
            raise ValueError("prebuilt video ends inside a JPEG frame")
        frames.append(data[start : end + 2])
        cursor = end + 2
    if cursor != len(data):
        raise ValueError("prebuilt MJPEG contains bytes outside JPEG frames")
    return frames


def build_prebuilt_fixture(
    video: Path,
    audio: Path,
    *,
    label: str,
    caption: str = "",
    fps: int = FPS,
) -> Fixture:
    """Convert a finished film once, then serve it in device-sized held cues."""
    if not video.is_file() or not audio.is_file():
        raise FileNotFoundError(f"missing prebuilt demo media: {video} / {audio}")
    with tempfile.TemporaryDirectory(prefix="gizmo-demo-") as temporary:
        encoded = Path(temporary) / "film.mjpeg"
        encoded_count = encode_mjpeg(
            video,
            encoded,
            width=WIDTH,
            height=HEIGHT,
            fps=fps,
            content_height=HEIGHT - CAPTION_BAND_HEIGHT,
        )
        frames = _split_mjpeg(encoded.read_bytes())
    if encoded_count != len(frames):
        raise ValueError(
            f"FFmpeg reported {encoded_count} frames but {len(frames)} were parsed"
        )

    with wave.open(str(audio), "rb") as source:
        if (
            source.getnchannels() != 1
            or source.getsampwidth() != 2
            or source.getframerate() != WIRE_RATE
            or source.getcomptype() != "NONE"
        ):
            raise ValueError("prebuilt narration must be mono 16-bit 24 kHz PCM WAV")
        pcm = source.readframes(source.getnframes())

    sample_count = len(pcm) // 2
    usable_frames = min(len(frames), round(sample_count * fps / WIRE_RATE))
    if usable_frames < 1:
        raise ValueError("prebuilt demo has no overlapping audio and video")
    frames = frames[:usable_frames]
    frames_per_segment = fps * SEGMENT_SECONDS
    segments = []
    for index, first in enumerate(range(0, len(frames), frames_per_segment)):
        selected = frames[first : first + frames_per_segment]
        sample_first = round(first * WIRE_RATE / fps)
        sample_last = min(
            sample_count,
            round((first + len(selected)) * WIRE_RATE / fps),
        )
        segments.append(
            Segment(
                show_id=f"{index + 1:032x}",
                still=selected[0],
                motion=b"".join(selected),
                frame_count=len(selected),
                pcm=pcm[sample_first * 2 : sample_last * 2],
            )
        )
    return Fixture(
        fps,
        sample_count / WIRE_RATE,
        SEGMENT_SECONDS,
        tuple(segments),
        label,
        caption,
    )


def check_fixture(fixture: Fixture) -> None:
    expected_frames = fixture.fps * fixture.segment_seconds
    expected_pcm = WIRE_RATE * 2 * fixture.segment_seconds
    for index, segment in enumerate(fixture.segments):
        is_last = index == len(fixture.segments) - 1
        assert 0 < segment.frame_count <= expected_frames
        assert 0 < len(segment.pcm) <= expected_pcm and not len(segment.pcm) % 2
        if not is_last:
            assert segment.frame_count == expected_frames
            assert len(segment.pcm) == expected_pcm
        duration_error = abs(
            segment.frame_count / fixture.fps
            - len(segment.pcm) / (WIRE_RATE * 2)
        )
        assert duration_error <= 1 / fixture.fps
        assert segment.still.startswith(b"\xff\xd8") and segment.still.endswith(b"\xff\xd9")
        cursor = 0
        decoded = 0
        while cursor < len(segment.motion):
            assert segment.motion[cursor : cursor + 2] == b"\xff\xd8"
            end = segment.motion.find(b"\xff\xd9", cursor + 2)
            assert end >= 0
            with Image.open(io.BytesIO(segment.motion[cursor : end + 2])) as image:
                assert image.size == (WIDTH, HEIGHT)
                assert image.mode == "RGB"
            decoded += 1
            cursor = end + 2
        assert decoded == segment.frame_count


def _local_ip() -> str:
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 9))
        return str(probe.getsockname()[0])
    except OSError:
        return "<this-mac-ip>"
    finally:
        probe.close()


class FixtureSession:
    def __init__(self, websocket: WebSocket, fixture: Fixture, device: str):
        self.websocket = websocket
        self.fixture = fixture
        self.device = device
        self.send_lock = asyncio.Lock()
        self.ready: dict[tuple[int, str], asyncio.Future[bool]] = {}
        self.film: asyncio.Task | None = None
        self.prepare_task: asyncio.Task | None = None
        self.prepared: tuple[Segment, int, str, str] | None = None
        self.epoch = time.monotonic()

    def log(self, message: str) -> None:
        elapsed = time.monotonic() - self.epoch
        print(f"fixture: +{elapsed:7.3f}s device={self.device} {message}", flush=True)

    async def send(self, event: dict) -> None:
        async with self.send_lock:
            await self.websocket.send_json(event)

    async def state(self, state: str) -> None:
        await self.send({"type": "state", "state": state})

    async def cancel(self) -> None:
        film, self.film = self.film, None
        if film and film is not asyncio.current_task():
            film.cancel()
            await asyncio.gather(film, return_exceptions=True)
        prepare, self.prepare_task = self.prepare_task, None
        if prepare and prepare is not asyncio.current_task():
            prepare.cancel()
            await asyncio.gather(prepare, return_exceptions=True)
        self.prepared = None
        for future in self.ready.values():
            if not future.done():
                future.cancel()
        self.ready.clear()

    def prepare_first(self) -> None:
        if self.prepare_task is not None or self.prepared is not None:
            return

        async def prepare() -> None:
            try:
                self.log("PREPARE first cue while PTT is held")
                self.prepared = await self.preload(0)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self.log(f"PREPARE FAILED {type(error).__name__}: {error}")
            finally:
                if self.prepare_task is asyncio.current_task():
                    self.prepare_task = None

        self.prepare_task = asyncio.create_task(prepare())

    def paths(self, segment: Segment) -> tuple[str, str]:
        base = f"/shows/{self.device}/{segment.show_id}"
        return base + ".jpg", base + ".mjpeg"

    async def preload(self, index: int):
        if index >= len(self.fixture.segments):
            return None
        segment = self.fixture.segments[index]
        cue = index + 1
        still, motion = self.paths(segment)
        future = asyncio.get_running_loop().create_future()
        self.ready[(cue, "motion")] = future
        self.log(f"HOLD cue={cue} frames={segment.frame_count} bytes={len(segment.motion)}")
        await self.send(
            {
                "type": "glass",
                "viewing": True,
                "still": still,
                "frames": motion,
                "cue": cue,
                "hold": True,
                "text": self.fixture.caption,
            }
        )
        ok = await asyncio.wait_for(future, timeout=20)
        self.ready.pop((cue, "motion"), None)
        if not ok:
            raise RuntimeError(f"device rejected motion cue {cue}")
        self.log(f"READY cue={cue}")
        return segment, cue, still, motion

    async def send_pcm(self, pcm: bytes) -> None:
        started = asyncio.get_running_loop().time()
        for offset in range(0, len(pcm), PCM_CHUNK_BYTES):
            # Match production: maintain about 480 ms of lead without dumping
            # the full soundtrack into the ESP32 at once.
            wait = offset / (WIRE_RATE * 2) - (
                asyncio.get_running_loop().time() - started
            ) - 0.48
            if wait > 0:
                await asyncio.sleep(wait)
            await self.send(
                {
                    "type": "audio",
                    "pcm": base64.b64encode(pcm[offset : offset + PCM_CHUNK_BYTES]).decode(),
                }
            )
        remaining = len(pcm) / (WIRE_RATE * 2) - (
            asyncio.get_running_loop().time() - started
        )
        if remaining > 0:
            await asyncio.sleep(remaining)

    async def play(self) -> None:
        try:
            self.epoch = time.monotonic()
            self.log(
                f"START label={self.fixture.label!r} seconds={self.fixture.seconds:.2f} "
                f"fps={self.fixture.fps}"
            )
            await self.state("thinking")
            item = self.prepared
            if item is None and self.prepare_task is not None:
                prepare = self.prepare_task
                await prepare
                item = self.prepared
            self.prepared = None
            if item is None:
                item = await self.preload(0)
            index = 0
            while item is not None:
                segment, cue, still, motion = item
                self.log(f"GO cue={cue}")
                await self.send(
                    {
                        "type": "glass",
                        "viewing": True,
                        "still": still,
                        "frames": motion,
                        "cue": cue,
                        "go": True,
                        "text": self.fixture.caption,
                    }
                )
                await self.state("talking")
                pending = asyncio.create_task(self.preload(index + 1))
                await self.send_pcm(segment.pcm)
                item = await pending
                index += 1
            await asyncio.sleep(0.6)
            await self.state("listening")
            await self.send({"type": "glass", "viewing": False, "text": ""})
            self.log("COMPLETE")
        except asyncio.CancelledError:
            self.log("CANCELLED")
            raise
        except Exception as error:  # physical fixture must fail loudly and retain evidence
            self.log(f"FAILED {type(error).__name__}: {error}")
            await self.state("listening")
            await self.send({"type": "glass", "viewing": False, "text": ""})
        finally:
            self.ready.clear()
            if self.film is asyncio.current_task():
                self.film = None


def create_app(fixture: Fixture) -> FastAPI:
    app = FastAPI(title="Gizmo local film fixture")
    by_id = {segment.show_id: segment for segment in fixture.segments}

    @app.get("/health")
    async def health():
        return JSONResponse(
            {
                "ok": True,
                "fixture": True,
                "label": fixture.label,
                "seconds": fixture.seconds,
                "fps": fixture.fps,
            }
        )

    def media(show_id: str) -> Segment:
        segment = by_id.get(show_id)
        if segment is None:
            raise HTTPException(status_code=404)
        return segment

    @app.get("/shows/{device}/{show_id}.jpg")
    async def still(device: str, show_id: str, w: int = Query(WIDTH), h: int = Query(HEIGHT)):
        del device
        if (w, h) != (WIDTH, HEIGHT):
            raise HTTPException(status_code=400, detail="fixture is 320x240")
        return Response(media(show_id).still, media_type="image/jpeg")

    @app.get("/shows/{device}/{show_id}.mjpeg")
    async def motion(
        device: str,
        show_id: str,
        w: int = Query(WIDTH),
        h: int = Query(HEIGHT),
        fps: int = Query(FPS),
    ):
        del device
        if (w, h, fps) != (WIDTH, HEIGHT, fixture.fps):
            raise HTTPException(status_code=400, detail="fixture geometry/fps mismatch")
        segment = media(show_id)
        return Response(
            segment.motion,
            media_type="video/x-motion-jpeg",
            headers={
                "X-Gizmo-Frame-Count": str(segment.frame_count),
                "X-Gizmo-Frame-Rate": str(fixture.fps),
                "X-Gizmo-Frame-Width": str(WIDTH),
                "X-Gizmo-Frame-Height": str(HEIGHT),
            },
        )

    @app.websocket("/ws")
    async def friend(websocket: WebSocket):
        await websocket.accept()
        device = websocket.headers.get("x-gizmo-device", "fixture-device")[:31]
        session = FixtureSession(websocket, fixture, device)
        session.log("CONNECTED")
        await session.send({"type": "hello", "protocol_version": 1, "state": "listening"})
        await session.send({"type": "glass", "viewing": False, "text": ""})
        try:
            while True:
                event = await websocket.receive_json()
                kind = event.get("type")
                if kind == "glass_ready":
                    key = (int(event.get("cue", 0)), str(event.get("kind", "")))
                    future = session.ready.get(key)
                    if future and not future.done():
                        future.set_result(event.get("ok") is True)
                elif kind == "ptt":
                    if event.get("active") is True:
                        await session.cancel()
                        await session.send({"type": "interrupted"})
                        await session.send({"type": "glass", "viewing": False, "text": ""})
                        await session.state("listening")
                        session.prepare_first()
                    elif session.film is None:
                        session.film = asyncio.create_task(session.play())
                elif kind == "select":
                    await session.cancel()
                    await session.send({"type": "glass", "viewing": False, "text": ""})
                    await session.state("listening")
                elif kind == "power":
                    await session.state("booting")
                    await asyncio.sleep(0.1)
                    await session.state("listening")
                # Mic audio and unrelated controls are intentionally ignored.
        except WebSocketDisconnect:
            session.log("DISCONNECTED")
        finally:
            await session.cancel()

    return app


def check_app(fixture: Fixture) -> None:
    """Exercise the real HTTP headers and enough WS flow to reach first audio."""
    from fastapi.testclient import TestClient

    device = "fixture-device"
    segment = fixture.segments[0]
    base = f"/shows/{device}/{segment.show_id}"
    with TestClient(create_app(fixture)) as client:
        assert client.get("/health").status_code == 200
        still = client.get(base + ".jpg", params={"w": WIDTH, "h": HEIGHT})
        assert still.status_code == 200 and still.headers["content-type"] == "image/jpeg"
        motion = client.get(
            base + ".mjpeg",
            params={"w": WIDTH, "h": HEIGHT, "fps": fixture.fps},
        )
        assert motion.status_code == 200
        assert motion.headers["content-type"] == "video/x-motion-jpeg"
        assert int(motion.headers["x-gizmo-frame-count"]) == segment.frame_count
        with client.websocket_connect(
            "/ws", headers={"X-Gizmo-Device": device}
        ) as websocket:
            assert websocket.receive_json()["type"] == "hello"
            assert websocket.receive_json()["type"] == "glass"
            websocket.send_json({"type": "ptt", "active": True})
            assert websocket.receive_json() == {"type": "interrupted"}
            hidden = websocket.receive_json()
            assert hidden["type"] == "glass" and hidden["viewing"] is False
            assert websocket.receive_json() == {"type": "state", "state": "listening"}
            hold = websocket.receive_json()
            assert hold["type"] == "glass" and hold["hold"] is True and hold["cue"] == 1
            websocket.send_json(
                {"type": "glass_ready", "cue": 1, "kind": "motion", "ok": True}
            )
            websocket.send_json({"type": "ptt", "active": False})
            assert websocket.receive_json() == {"type": "state", "state": "thinking"}
            go = websocket.receive_json()
            assert go["type"] == "glass" and go["go"] is True and go["cue"] == 1
            assert websocket.receive_json() == {"type": "state", "state": "talking"}
            audio = websocket.receive_json()
            assert audio["type"] == "audio" and base64.b64decode(audio["pcm"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--fps", type=int, default=FPS)
    parser.add_argument("--seconds", type=int, default=SECONDS)
    parser.add_argument(
        "--demo-pompeii",
        action="store_true",
        help="play the bundled 37-second Pompeii film instead of the diagnostic pattern",
    )
    parser.add_argument("--check", action="store_true", help="validate generated bytes and exit")
    args = parser.parse_args()

    if args.demo_pompeii:
        fixture = build_prebuilt_fixture(
            POMPEII_VIDEO,
            POMPEII_AUDIO,
            label="The Day the Mountain Woke",
            fps=args.fps,
        )
    else:
        fixture = build_fixture(fps=args.fps, seconds=args.seconds)
    check_fixture(fixture)
    check_app(fixture)
    total_bytes = sum(len(segment.motion) for segment in fixture.segments)
    total_frames = sum(segment.frame_count for segment in fixture.segments)
    print(
        f"fixture: verified {fixture.label!r}, {fixture.seconds:.2f}s, {fixture.fps}fps, "
        f"{len(fixture.segments)} cues, {total_frames} frames, {total_bytes} MJPEG bytes",
        flush=True,
    )
    if args.check:
        return
    address = _local_ip()
    print(f"fixture: set Gizmo serial URL to Fhttp://{address}:{args.port}", flush=True)
    if args.demo_pompeii:
        print(
            "fixture: hold PTT and ask, 'Gizmo, what happened to Pompeii a long time ago?'",
            flush=True,
        )
        print("fixture: the first cue preloads while PTT is held; release to play", flush=True)
    else:
        print("fixture: then press and release PTT; no speech is required", flush=True)
    uvicorn.run(create_app(fixture), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
