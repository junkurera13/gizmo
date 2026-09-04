"""Bounded macOS I/O adapters for the body protocol reference client."""

from __future__ import annotations

import asyncio
import contextlib
import io
import os
import tempfile
from pathlib import Path
from typing import Awaitable, Callable
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import httpx
from PIL import Image, ImageOps


AUDIO_RATE = 24_000
AUDIO_CHANNELS = 1
CAMERA_MAX_WIDTH = 640
CAMERA_MAX_HEIGHT = 480
CAMERA_MAX_BYTES = 128 * 1024


class HardwareIOError(RuntimeError):
    pass


def bundled_ffmpeg() -> str:
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as error:  # noqa: BLE001 - present one actionable adapter error
        raise HardwareIOError("imageio-ffmpeg is required for the macOS adapters") from error


async def _stop_process(process: asyncio.subprocess.Process | None) -> None:
    if process is None or process.returncode is not None:
        return
    with contextlib.suppress(ProcessLookupError):
        process.terminate()
    try:
        await asyncio.wait_for(process.wait(), timeout=1)
    except asyncio.TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            process.kill()
        await process.wait()


class FFmpegMicrophone:
    """Streams real AVFoundation input as 24 kHz mono PCM16 little-endian."""

    def __init__(self, ffmpeg: str, device_index: int = 0, chunk_bytes: int = 4_800) -> None:
        self.ffmpeg = ffmpeg
        self.device_index = device_index
        self.chunk_bytes = chunk_bytes - (chunk_bytes % 2)
        self.process: asyncio.subprocess.Process | None = None
        self.task: asyncio.Task[None] | None = None
        self.ready: asyncio.Future[None] | None = None

    async def start(self, on_pcm: Callable[[bytes], Awaitable[None]]) -> None:
        if self.task is not None:
            return
        self.process = await asyncio.create_subprocess_exec(
            self.ffmpeg,
            "-nostdin", "-hide_banner", "-loglevel", "error",
            "-f", "avfoundation", "-i", f":{self.device_index}",
            "-ac", str(AUDIO_CHANNELS), "-ar", str(AUDIO_RATE),
            "-c:a", "pcm_s16le", "-f", "s16le", "pipe:1",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self.ready = asyncio.get_running_loop().create_future()
        self.task = asyncio.create_task(self._pump(on_pcm))
        try:
            await asyncio.wait_for(asyncio.shield(self.ready), timeout=2)
        except BaseException:
            await self.stop()
            raise

    async def _pump(self, on_pcm: Callable[[bytes], Awaitable[None]]) -> None:
        assert self.process is not None and self.process.stdout is not None
        process = self.process
        try:
            while True:
                chunk = await process.stdout.read(self.chunk_bytes)
                if not chunk:
                    break
                if len(chunk) % 2:
                    chunk += await process.stdout.readexactly(1)
                if self.ready is not None and not self.ready.done():
                    self.ready.set_result(None)
                await on_pcm(chunk)
        except (asyncio.CancelledError, asyncio.IncompleteReadError):
            pass
        finally:
            if self.ready is not None and not self.ready.done():
                detail = "microphone did not deliver PCM"
                if process.stderr is not None:
                    error = await process.stderr.read()
                    lines = error.decode("utf-8", errors="replace").strip().splitlines()
                    if lines:
                        detail = lines[-1]
                self.ready.set_exception(HardwareIOError(detail))

    async def stop(self) -> None:
        task, process = self.task, self.process
        self.task, self.process, self.ready = None, None, None
        if task is not None:
            task.cancel()
        await _stop_process(process)
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)


def _bounded_jpeg(raw: bytes) -> tuple[bytes, tuple[int, int]]:
    with Image.open(io.BytesIO(raw)) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
    image.thumbnail((CAMERA_MAX_WIDTH, CAMERA_MAX_HEIGHT), Image.Resampling.LANCZOS)
    for quality in (75, 65, 55, 45, 35):
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=quality, optimize=True)
        encoded = output.getvalue()
        if len(encoded) <= CAMERA_MAX_BYTES:
            return encoded, image.size
    raise HardwareIOError("camera JPEG could not fit the 128 KiB protocol ceiling")


class FFmpegCamera:
    """Captures one warmed-up AVFoundation JPEG for each PTT hold."""

    def __init__(self, ffmpeg: str, device_index: int = 0) -> None:
        self.ffmpeg = ffmpeg
        self.device_index = device_index
        self.process: asyncio.subprocess.Process | None = None

    async def capture(self) -> tuple[bytes, tuple[int, int]]:
        if self.process is not None:
            raise HardwareIOError("camera capture is already active")
        process = await asyncio.create_subprocess_exec(
            self.ffmpeg,
            "-nostdin", "-hide_banner", "-loglevel", "error",
            "-f", "avfoundation", "-framerate", "30", "-video_size", "640x480",
            "-i", f"{self.device_index}:none",
            "-vf", "select='gte(t,0.4)'", "-fps_mode", "vfr", "-frames:v", "1",
            "-c:v", "mjpeg", "-q:v", "5", "-f", "image2pipe", "pipe:1",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self.process = process
        try:
            raw, error = await asyncio.wait_for(process.communicate(), timeout=5)
        except asyncio.TimeoutError as error:
            await _stop_process(process)
            raise HardwareIOError("camera did not deliver a frame within 5 seconds") from error
        except asyncio.CancelledError:
            await _stop_process(process)
            raise
        finally:
            self.process = None
        if process.returncode != 0 or not raw:
            detail = error.decode("utf-8", errors="replace").strip().splitlines()
            raise HardwareIOError(detail[-1] if detail else "camera did not deliver a frame")
        return await asyncio.to_thread(_bounded_jpeg, raw)

    async def cancel(self) -> None:
        await _stop_process(self.process)


class FFmpegSpeaker:
    """Plays response PCM through AudioToolbox with a strict application queue bound."""

    def __init__(self, ffmpeg: str, device_index: int = -1, max_buffer_bytes: int = 96_000) -> None:
        self.ffmpeg = ffmpeg
        self.device_index = device_index
        self.max_buffer_bytes = max_buffer_bytes
        self.queue: asyncio.Queue[bytes] = asyncio.Queue()
        self.queued_bytes = 0
        self.dropped_bytes = 0
        self.process: asyncio.subprocess.Process | None = None
        self.task: asyncio.Task[None] | None = None

    def enqueue(self, pcm: bytes) -> bool:
        if not pcm or len(pcm) % 2:
            return False
        if len(pcm) > self.max_buffer_bytes or self.queued_bytes + len(pcm) > self.max_buffer_bytes:
            self.dropped_bytes += len(pcm)
            return False
        self.queued_bytes += len(pcm)
        self.queue.put_nowait(pcm)
        if self.task is None:
            self.task = asyncio.create_task(self._play())
        return True

    async def _play(self) -> None:
        command = [
            self.ffmpeg,
            "-nostdin", "-hide_banner", "-loglevel", "error",
            "-f", "s16le", "-ar", str(AUDIO_RATE), "-ac", str(AUDIO_CHANNELS),
            "-i", "pipe:0", "-c:a", "pcm_s16le", "-f", "audiotoolbox",
        ]
        if self.device_index >= 0:
            command.extend(("-audio_device_index", str(self.device_index)))
        command.append("")
        try:
            self.process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            assert self.process.stdin is not None
            while True:
                pcm = await self.queue.get()
                self.queued_bytes -= len(pcm)
                self.process.stdin.write(pcm)
                await self.process.stdin.drain()
        except (asyncio.CancelledError, BrokenPipeError, ConnectionResetError):
            pass
        finally:
            process, self.process = self.process, None
            if process is not None and process.stdin is not None:
                process.stdin.close()
            await _stop_process(process)
            self.task = None

    async def interrupt(self) -> None:
        while not self.queue.empty():
            with contextlib.suppress(asyncio.QueueEmpty):
                self.queue.get_nowait()
        self.queued_bytes = 0
        task, self.task = self.task, None
        if task is not None:
            task.cancel()
        await _stop_process(self.process)
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)

    async def shutdown(self) -> None:
        await self.interrupt()


class GlassMediaFetcher:
    """Fetches same-origin, authenticated stills and finite MJPEG loops to bounded storage."""

    def __init__(
        self,
        base_url: str,
        device_id: str,
        token: str,
        *,
        width: int,
        height: int,
        fps: int,
        max_bytes: int = 4 * 1024 * 1024,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.device_id = device_id
        self.token = token
        self.width, self.height, self.fps = width, height, fps
        self.max_bytes = max_bytes
        self.directory = tempfile.TemporaryDirectory(prefix="gizmo-body-media-")
        self.client = httpx.AsyncClient(timeout=20, follow_redirects=False)

    @property
    def enabled(self) -> bool:
        return self.width > 0 and self.height > 0

    def _url(self, value: str, kind: str) -> str:
        resolved = urljoin(f"{self.base_url}/", value)
        expected, actual = urlsplit(self.base_url), urlsplit(resolved)
        if (actual.scheme, actual.hostname, actual.port) != (expected.scheme, expected.hostname, expected.port):
            raise HardwareIOError("refusing to send the device credential to cross-origin glass media")
        query = dict(parse_qsl(actual.query, keep_blank_values=True))
        query.update({"w": str(self.width), "h": str(self.height)})
        if kind == "frames":
            query["fps"] = str(self.fps)
        return urlunsplit((actual.scheme, actual.netloc, actual.path, urlencode(query), ""))

    async def _download(self, value: str, kind: str, expected_type: str) -> tuple[Path, httpx.Headers, int]:
        headers = {
            "X-Gizmo-Device": self.device_id,
            "X-Gizmo-Protocol": "1",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        total = 0
        target = Path(self.directory.name) / ("show.jpg" if kind == "still" else "show.mjpeg")
        async with self.client.stream("GET", self._url(value, kind), headers=headers) as response:
            response.raise_for_status()
            content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
            if content_type != expected_type:
                raise HardwareIOError(f"unexpected {kind} content type {content_type!r}")
            with target.open("wb") as handle:
                os.chmod(target, 0o600)
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > self.max_bytes:
                        raise HardwareIOError(f"{kind} exceeds the {self.max_bytes}-byte body cache bound")
                    handle.write(chunk)
            return target, response.headers, total

    async def fetch(self, event: dict[str, object]) -> list[dict[str, object]]:
        if not self.enabled or event.get("viewing") is False:
            return []
        fetched: list[dict[str, object]] = []
        still = event.get("still")
        if isinstance(still, str):
            path, _, size = await self._download(still, "still", "image/jpeg")
            with Image.open(path) as image:
                dimensions = image.size
            if dimensions != (self.width, self.height):
                raise HardwareIOError(f"still dimensions {dimensions} do not match requested panel size")
            fetched.append({"kind": "still", "bytes": size, "width": dimensions[0], "height": dimensions[1]})
        frames = event.get("frames")
        if isinstance(frames, str):
            path, headers, size = await self._download(frames, "frames", "video/x-motion-jpeg")
            frame_count = int(headers.get("x-gizmo-frame-count", "0"))
            metadata = {
                "kind": "frames",
                "bytes": size,
                "frames": frame_count,
                "width": int(headers.get("x-gizmo-frame-width", "0")),
                "height": int(headers.get("x-gizmo-frame-height", "0")),
                "fps": int(headers.get("x-gizmo-frame-rate", "0")),
            }
            if metadata["width"] != self.width or metadata["height"] != self.height or metadata["fps"] != self.fps:
                raise HardwareIOError("MJPEG metadata does not match the requested panel profile")
            starts = ends = 0
            previous = b""
            with path.open("rb") as handle:
                while chunk := handle.read(64 * 1024):
                    scan = previous + chunk
                    starts += scan.count(b"\xff\xd8")
                    ends += scan.count(b"\xff\xd9")
                    previous = scan[-1:]
            if frame_count <= 0 or starts != frame_count or ends != frame_count:
                raise HardwareIOError("MJPEG frame sequence is incomplete")
            fetched.append(metadata)
        return fetched

    async def close(self) -> None:
        await self.client.aclose()
        self.directory.cleanup()
