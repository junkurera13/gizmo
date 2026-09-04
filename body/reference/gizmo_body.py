#!/usr/bin/env python3
"""Laptop reference for Gizmo body protocol v1, including bounded real I/O."""

from __future__ import annotations

import argparse
import asyncio
import base64
import binascii
import contextlib
import json
import os
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException

from io_macos import (
    FFmpegCamera,
    FFmpegMicrophone,
    FFmpegSpeaker,
    GlassMediaFetcher,
    HardwareIOError,
    bundled_ffmpeg,
)


PROTOCOL_VERSION = 1
WAKE_AUDIO_BYTES = 10 * 24_000 * 2


class ProtocolError(RuntimeError):
    pass


def endpoint(base_url: str, path: str, *, websocket: bool = False) -> str:
    parsed = urlsplit(base_url.rstrip("/"))
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ProtocolError("brain URL must be an HTTP or HTTPS URL")
    if parsed.username or parsed.password:
        raise ProtocolError("brain URL must not contain credentials")
    is_local = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    if not is_local and parsed.scheme != "https":
        raise ProtocolError("remote brains require HTTPS/WSS")
    scheme = ({"http": "ws", "https": "wss"}[parsed.scheme] if websocket else parsed.scheme)
    joined_path = f"{parsed.path.rstrip('/')}/{path.lstrip('/')}"
    return urlunsplit((scheme, parsed.netloc, joined_path, "", ""))


class BodyClient:
    def __init__(self, base_url: str, device_id: str, token: str = "") -> None:
        if not device_id or len(device_id) > 64 or any(
            not (character.isalnum() or character in "-_.") for character in device_id
        ):
            raise ProtocolError("device id must be 1–64 letters, numbers, '-', '_' or '.'")
        self.base_url = base_url
        self.device_id = device_id
        self.token = token
        self.socket: Any = None
        self.hello: dict[str, Any] | None = None
        self.initial_glass: dict[str, Any] | None = None

    async def inspect_health(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.get(endpoint(self.base_url, "/health"))
            response.raise_for_status()
            health = response.json()
        if not isinstance(health, dict):
            raise ProtocolError("brain health response must be an object")
        advertised = health.get("body_protocol", {}).get("version")
        if advertised != PROTOCOL_VERSION:
            raise ProtocolError(
                f"brain protocol {advertised!r} is incompatible with body protocol {PROTOCOL_VERSION}"
            )
        return health

    async def connect(self) -> tuple[dict[str, Any], dict[str, Any]]:
        await self.inspect_health()
        host = urlsplit(self.base_url).hostname
        if host not in {"127.0.0.1", "localhost", "::1"} and not self.token:
            raise ProtocolError("remote brains require GIZMO_DEVICE_TOKEN")
        headers = {
            "X-Gizmo-Device": self.device_id,
            "X-Gizmo-Protocol": str(PROTOCOL_VERSION),
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        self.socket = await connect(
            endpoint(self.base_url, "/ws", websocket=True),
            additional_headers=headers,
            compression=None,
            open_timeout=8,
            close_timeout=2,
            ping_interval=20,
            ping_timeout=20,
            max_queue=16,
        )
        hello = await self.receive()
        if hello.get("type") != "hello" or hello.get("protocol_version") != PROTOCOL_VERSION:
            await self.close()
            raise ProtocolError("brain hello did not confirm body protocol v1")
        glass = await self.receive()
        if glass.get("type") != "glass":
            await self.close()
            raise ProtocolError("brain did not send the initial glass snapshot")
        self.hello, self.initial_glass = hello, glass
        return hello, glass

    async def send(self, event: dict[str, Any]) -> None:
        if self.socket is None:
            raise ProtocolError("body is not connected")
        await self.socket.send(json.dumps(event, separators=(",", ":")))

    async def receive(self) -> dict[str, Any]:
        if self.socket is None:
            raise ProtocolError("body is not connected")
        message = await self.socket.recv()
        try:
            if isinstance(message, bytes):
                message = message.decode("utf-8")
            event = json.loads(message)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ProtocolError("brain sent invalid JSON") from error
        if not isinstance(event, dict):
            raise ProtocolError("brain sent a non-object event")
        return event

    async def close(self) -> None:
        socket, self.socket = self.socket, None
        if socket is not None:
            await socket.close()


class WakeAudioBuffer:
    """Keeps the first ten seconds captured while a wake/reconnect is opening."""

    def __init__(self, capacity: int = WAKE_AUDIO_BYTES) -> None:
        self.capacity = capacity
        self.data = bytearray()
        self.dropped_bytes = 0

    def append(self, pcm: bytes) -> None:
        available = self.capacity - len(self.data)
        self.data.extend(pcm[:available])
        self.dropped_bytes += max(0, len(pcm) - available)

    def clear(self) -> None:
        self.data.clear()
        self.dropped_bytes = 0


class BodyRuntime:
    """Keeps physical I/O alive across a replaceable brain connection."""

    def __init__(
        self,
        args: argparse.Namespace,
        microphone: FFmpegMicrophone,
        camera: FFmpegCamera,
        speaker: FFmpegSpeaker,
        glass: GlassMediaFetcher,
    ) -> None:
        self.args = args
        self.microphone, self.camera, self.speaker, self.glass = microphone, camera, speaker, glass
        self.client: BodyClient | None = None
        self.send_lock = asyncio.Lock()
        self.connected = asyncio.Event()
        self.stopping = False
        self.ptt_held = False
        self.ptt_announced = False
        self.hold = 0
        self.wake_audio = WakeAudioBuffer()
        self.connections_opened = 0
        self.buffered_audio_bytes = 0
        self.reconnected_audio_bytes = 0
        self.camera_task: asyncio.Task[None] | None = None
        self.glass_task: asyncio.Task[None] | None = None

    def report(self, event: dict[str, Any]) -> None:
        print(json.dumps(printable(event), ensure_ascii=False), flush=True)

    async def run(self) -> None:
        delay = 0.25
        try:
            while not self.stopping:
                client = BodyClient(self.args.url, self.args.device_id, self.args.token)
                try:
                    hello, initial_glass = await client.connect()
                    await self._activate(client)
                    self.report(hello)
                    await self._handle(initial_glass)
                    delay = 0.25
                    while not self.stopping:
                        await self._handle(await client.receive())
                except asyncio.CancelledError:
                    raise
                except (OSError, ProtocolError, WebSocketException, httpx.HTTPError, ConnectionError) as error:
                    if not self.stopping:
                        self.report({"type": "connection", "status": "reconnecting", "message": str(error)})
                finally:
                    await self._deactivate(client)
                if not self.stopping:
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, 4)
        finally:
            await self._shutdown_io()

    async def _activate(self, client: BodyClient) -> None:
        restart_camera = False
        async with self.send_lock:
            self.client = client
            self.connections_opened += 1
            self.ptt_announced = False
            if self.ptt_held:
                await client.send({"type": "ptt", "active": True})
                self.ptt_announced = True
                await self._flush_wake_audio(client, reconnect=self.connections_opened > 1)
                restart_camera = True
            self.connected.set()
        if restart_camera:
            self._start_camera(self.hold)

    async def _deactivate(self, client: BodyClient) -> None:
        async with self.send_lock:
            if self.client is client:
                self.client = None
                self.ptt_announced = False
                self.connected.clear()
        await self._cancel_camera()
        await self.speaker.interrupt()
        with contextlib.suppress(Exception):
            await client.close()

    async def _send(self, event: dict[str, Any]) -> bool:
        async with self.send_lock:
            if self.client is None:
                return False
            try:
                await self.client.send(event)
                return True
            except (OSError, WebSocketException, ConnectionError):
                return False

    async def _flush_wake_audio(self, client: BodyClient, *, reconnect: bool = False) -> None:
        while self.wake_audio.data:
            chunk = bytes(self.wake_audio.data[:4_800])
            await client.send({"type": "audio", "pcm": base64.b64encode(chunk).decode("ascii")})
            del self.wake_audio.data[:len(chunk)]
            if reconnect:
                self.reconnected_audio_bytes += len(chunk)

    async def _on_pcm(self, pcm: bytes) -> None:
        if not self.ptt_held:
            return
        async with self.send_lock:
            client = self.client
            if client is None or not self.ptt_announced:
                before = len(self.wake_audio.data)
                self.wake_audio.append(pcm)
                self.buffered_audio_bytes += len(self.wake_audio.data) - before
                return
            try:
                await client.send({"type": "audio", "pcm": base64.b64encode(pcm).decode("ascii")})
            except (OSError, WebSocketException, ConnectionError):
                before = len(self.wake_audio.data)
                self.wake_audio.append(pcm)
                self.buffered_audio_bytes += len(self.wake_audio.data) - before

    async def begin_ptt(self) -> None:
        if self.ptt_held:
            return
        self.hold += 1
        hold = self.hold
        self.ptt_held = True
        self.ptt_announced = False
        self.wake_audio.clear()
        await self.microphone.start(self._on_pcm)
        async with self.send_lock:
            if self.client is not None:
                try:
                    await self.client.send({"type": "ptt", "active": True})
                    self.ptt_announced = True
                    await self._flush_wake_audio(self.client)
                except (OSError, WebSocketException, ConnectionError):
                    self.ptt_announced = False
        self._start_camera(hold)

    async def end_ptt(self) -> None:
        if not self.ptt_held:
            return
        self.ptt_held = False
        await self.microphone.stop()
        await self._cancel_camera()
        async with self.send_lock:
            if self.client is not None and self.ptt_announced:
                try:
                    await self._flush_wake_audio(self.client)
                    await self.client.send({"type": "ptt", "active": False})
                except (OSError, WebSocketException, ConnectionError):
                    pass
            self.ptt_announced = False
            self.wake_audio.clear()

    def _start_camera(self, hold: int) -> None:
        if self.camera_task is None and self.ptt_held:
            self.camera_task = asyncio.create_task(self._capture_camera(hold))

    async def _capture_camera(self, hold: int) -> None:
        try:
            jpeg, dimensions = await self.camera.capture()
            if hold != self.hold or not self.ptt_held:
                return
            sent = await self._send({
                "type": "frame",
                "mime": "image/jpeg",
                "image": base64.b64encode(jpeg).decode("ascii"),
            })
            self.report({
                "type": "camera", "status": "sent" if sent else "dropped",
                "bytes": len(jpeg), "width": dimensions[0], "height": dimensions[1],
            })
        except asyncio.CancelledError:
            pass
        except HardwareIOError as error:
            self.report({"type": "camera", "status": "error", "message": str(error)})
        finally:
            if self.camera_task is asyncio.current_task():
                self.camera_task = None

    async def _cancel_camera(self) -> None:
        task, self.camera_task = self.camera_task, None
        if task is not None:
            task.cancel()
        await self.camera.cancel()
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)

    async def _handle(self, event: dict[str, Any]) -> None:
        kind = event.get("type")
        if kind == "audio" and isinstance(event.get("pcm"), str):
            try:
                pcm = base64.b64decode(event["pcm"], validate=True)
            except (binascii.Error, ValueError):
                self.report({"type": "speaker", "status": "error", "message": "invalid response PCM"})
            else:
                if not self.ptt_held:
                    accepted = self.speaker.enqueue(pcm)
                    if not accepted:
                        self.report({"type": "speaker", "status": "dropped", "bytes": len(pcm)})
        elif kind == "interrupted":
            await self.speaker.interrupt()
        elif kind == "glass":
            if self.glass_task is not None:
                self.glass_task.cancel()
            self.glass_task = asyncio.create_task(self._fetch_glass(event))
        self.report(event)

    async def _fetch_glass(self, event: dict[str, Any]) -> None:
        try:
            for media in await self.glass.fetch(event):
                self.report({"type": "glass_media", **media})
        except asyncio.CancelledError:
            pass
        except (HardwareIOError, httpx.HTTPError, OSError, ValueError) as error:
            self.report({"type": "glass_media", "status": "error", "message": str(error)})

    async def send_control(self, event: dict[str, Any]) -> None:
        if event.get("type") == "ptt":
            await (self.begin_ptt() if event.get("active") else self.end_ptt())
            return
        if event.get("type") == "power" and event.get("on") is False:
            await self.end_ptt()
        if not await self._send(event):
            self.report({"type": "connection", "status": "control_dropped", "control": event.get("type")})

    async def stop(self) -> None:
        self.stopping = True
        await self.end_ptt()
        client = self.client
        if client is not None:
            await client.close()

    async def _shutdown_io(self) -> None:
        await self.microphone.stop()
        await self._cancel_camera()
        await self.speaker.shutdown()
        if self.glass_task is not None:
            self.glass_task.cancel()
            await asyncio.gather(self.glass_task, return_exceptions=True)
        await self.glass.close()


def control(line: str) -> dict[str, Any] | None:
    command, _, argument = line.strip().partition(" ")
    command, argument = command.lower(), argument.strip()
    if command == "power" and argument in {"on", "off"}:
        return {"type": "power", "on": argument == "on"}
    if command == "ptt" and argument in {"down", "up"}:
        return {"type": "ptt", "active": argument == "down"}
    if command in {"up", "down"} and not argument:
        return {"type": "navigate", "direction": command}
    if command == "select" and not argument:
        return {"type": "select"}
    if command == "say" and argument:
        return {"type": "text", "text": argument}
    return None


def printable(event: dict[str, Any]) -> dict[str, Any]:
    safe = dict(event)
    if safe.get("type") == "audio" and isinstance(safe.get("pcm"), str):
        try:
            size = len(base64.b64decode(safe.pop("pcm"), validate=True))
        except (binascii.Error, ValueError):
            size = -1
            safe.pop("pcm", None)
        safe["pcm_bytes"] = size
    return safe


async def interactive(args: argparse.Namespace) -> None:
    ffmpeg = args.ffmpeg or bundled_ffmpeg()
    runtime = BodyRuntime(
        args,
        FFmpegMicrophone(ffmpeg, args.microphone_index),
        FFmpegCamera(ffmpeg, args.camera_index),
        FFmpegSpeaker(ffmpeg, args.speaker_index, args.speaker_buffer_bytes),
        GlassMediaFetcher(
            args.url, args.device_id, args.token,
            width=args.panel_width, height=args.panel_height, fps=args.panel_fps,
            max_bytes=args.media_cache_bytes,
        ),
    )
    runner = asyncio.create_task(runtime.run())
    print("Commands: power on|off, ptt down|up, up, down, select, say <text>, quit")
    if not runtime.glass.enabled:
        print("Glass media disabled until --panel-width and --panel-height describe the provisional panel.")
    try:
        while True:
            line = await asyncio.to_thread(input, "body> ")
            if line.strip().lower() in {"quit", "exit"}:
                return
            event = control(line)
            if event is None:
                print("Unknown command. Use the physical control names shown above.")
                continue
            await runtime.send_control(event)
    finally:
        await runtime.stop()
        runner.cancel()
        await asyncio.gather(runner, return_exceptions=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Gizmo body protocol v1 reference client")
    parser.add_argument("--url", default=os.environ.get("GIZMO_BRAIN_URL", "http://127.0.0.1:43147"))
    parser.add_argument("--device-id", default=os.environ.get("GIZMO_DEVICE_ID", "gizmo-reference"))
    parser.add_argument("--token", default=os.environ.get("GIZMO_DEVICE_TOKEN", ""))
    parser.add_argument("--ffmpeg", default="", help="FFmpeg binary; defaults to imageio-ffmpeg")
    parser.add_argument("--microphone-index", type=int, default=0, help="AVFoundation audio input index")
    parser.add_argument("--camera-index", type=int, default=0, help="AVFoundation video input index")
    parser.add_argument("--speaker-index", type=int, default=-1, help="AudioToolbox output index; -1 uses system default")
    parser.add_argument("--speaker-buffer-bytes", type=int, default=96_000, help="bounded response PCM queue")
    parser.add_argument("--panel-width", type=int, default=0, help="provisional physical panel width; 0 disables fetch")
    parser.add_argument("--panel-height", type=int, default=0, help="provisional physical panel height; 0 disables fetch")
    parser.add_argument("--panel-fps", type=int, default=24, help="provisional MJPEG playback rate")
    parser.add_argument("--media-cache-bytes", type=int, default=4 * 1024 * 1024, help="bounded still/MJPEG cache")
    args = parser.parse_args()
    if (args.panel_width == 0) != (args.panel_height == 0):
        parser.error("--panel-width and --panel-height must both be set or both be 0")
    if not (0 <= args.panel_width <= 1024 and 0 <= args.panel_height <= 1024):
        parser.error("panel dimensions must be 0–1024 pixels")
    if not (1 <= args.panel_fps <= 24):
        parser.error("panel fps must be 1–24")
    if args.microphone_index < 0 or args.camera_index < 0 or args.speaker_index < -1:
        parser.error("input indices must be non-negative; speaker index may also be -1")
    if args.speaker_buffer_bytes <= 0 or args.media_cache_bytes <= 0:
        parser.error("buffer bounds must be positive")
    try:
        asyncio.run(interactive(args))
    except (HardwareIOError, ProtocolError, OSError, httpx.HTTPError) as error:
        raise SystemExit(f"reference client: {error}") from error
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
