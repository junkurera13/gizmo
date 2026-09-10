"""Server-owned Director WebRTC session; the provider key never reaches a browser.

Signaling follows @fal-ai/client 1.11.0-alpha.3's WMA transport. Media is
relayed to viewers, with one upstream generation session and a bounded lease.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable

import httpx
from aiortc import (
    RTCConfiguration,
    RTCIceServer,
    RTCPeerConnection,
    RTCSessionDescription,
)
from aiortc.contrib.media import MediaRelay

ENDPOINT = "https://wma.fal.run"
MODEL = "minimax/h3-max/director"


class DirectorStream:
    def __init__(self, key: str, event: Callable[[dict], Awaitable[None]]):
        self.key = key
        self.event = event
        self.http = httpx.AsyncClient(timeout=75, follow_redirects=False)
        self.pc: RTCPeerConnection | None = None
        self.channel = None
        self.relay = MediaRelay()
        self.tracks = {}
        self.viewers: set[RTCPeerConnection] = set()
        self.tasks: set[asyncio.Task] = set()
        self.opened = asyncio.Event()
        self.video_ready = asyncio.Event()
        self.audio_ready = asyncio.Event()
        self.first_frame = asyncio.Event()
        self.latest_frame = None
        self.started = time.monotonic()
        self.closed = False
        self.frames = 0
        self.audio_samples = 0
        self.session_id = ""
        self.ice_servers = []

    def spawn(self, work):
        task = asyncio.create_task(work)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    async def post(self, path, body):
        response = await self.http.post(
            ENDPOINT + path, json=body, headers={"Authorization": "Key " + self.key}
        )
        if response.status_code != 200:
            # Provider errors can contain credentials or internal URLs.
            raise RuntimeError(f"Director {path} returned HTTP {response.status_code}")
        return response.json()

    async def connect(self):
        ice = await self.post("/ice", {"app_id": MODEL})
        servers = [
            RTCIceServer(
                **{k: row[k] for k in ("urls", "username", "credential") if k in row}
            )
            for row in ice.get("ice_servers", [])
        ]
        self.ice_servers = servers
        self.pc = pc = RTCPeerConnection(RTCConfiguration(iceServers=servers))
        pc.addTransceiver("video", direction="recvonly")
        pc.addTransceiver("audio", direction="recvonly")
        self.channel = channel = pc.createDataChannel("control")

        @channel.on("open")
        def opened():
            self.opened.set()

        @channel.on("message")
        def message(raw):
            try:
                value = json.loads(raw)
            except (ValueError, TypeError):
                return
            if isinstance(value, dict):
                self.spawn(self.event(value))

        @pc.on("track")
        def track_received(track):
            self.tracks[track.kind] = track
            (self.video_ready if track.kind == "video" else self.audio_ready).set()
            self.spawn(self.observe(self.relay.subscribe(track)))

        @pc.on("connectionstatechange")
        async def connection_changed():
            if pc.connectionState in {"failed", "closed"} and not self.closed:
                await self.event({"type": "transport_failed"})
                await self.close()

        try:
            async with asyncio.timeout(90):
                await pc.setLocalDescription(await pc.createOffer())
                answer = await self.post(
                    "/session",
                    {"app_id": MODEL, "type": "offer", "sdp": pc.localDescription.sdp},
                )
                self.session_id = answer["session_id"]
                await pc.setRemoteDescription(
                    RTCSessionDescription(sdp=answer["sdp"], type=answer["type"])
                )
                self.spawn(self.heartbeat())
                await self.opened.wait()
        except BaseException:
            await self.close()
            raise

    def send(self, message):
        if self.closed or self.channel is None or self.channel.readyState != "open":
            raise RuntimeError("Director is not connected")
        self.channel.send(json.dumps(message))

    async def observe(self, track):
        try:
            while not self.closed:
                frame = await track.recv()
                if track.kind == "video":
                    self.frames += 1
                    self.latest_frame = frame
                    if not self.first_frame.is_set():
                        self.first_frame.set()
                        await self.event(
                            {
                                "type": "first_frame",
                                "seconds": round(time.monotonic() - self.started, 3),
                            }
                        )
                else:
                    self.audio_samples += frame.samples
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - isolate a provider or socket failure
            if not self.closed:
                await self.event({"type": "track_ended", "kind": track.kind})
        finally:
            track.stop()

    async def heartbeat(self):
        try:
            while not self.closed:
                await asyncio.sleep(5)
                async with asyncio.timeout(5):
                    await self.post(
                        "/session/heartbeat", {"session_id": self.session_id}
                    )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - isolate a provider or socket failure
            await self.event({"type": "transport_failed"})
            await self.close()

    async def answer(self, sdp: str, kind: str, *, local: bool = False):
        async with asyncio.timeout(15):
            await self.video_ready.wait()
            await self.audio_ready.wait()
        if self.closed:
            raise RuntimeError("Film ended")
        pc = RTCPeerConnection(
            RTCConfiguration(iceServers=[] if local else list(self.ice_servers))
        )
        self.viewers.add(pc)

        @pc.on("connectionstatechange")
        async def changed():
            if pc.connectionState in {"failed", "closed"}:
                self.viewers.discard(pc)
                await pc.close()

        try:
            await pc.setRemoteDescription(RTCSessionDescription(sdp=sdp, type=kind))
            for track in self.tracks.values():
                pc.addTrack(self.relay.subscribe(track))
            await pc.setLocalDescription(await pc.createAnswer())
            return {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}
        except BaseException:
            self.viewers.discard(pc)
            await pc.close()
            raise

    async def close(self):
        if self.closed:
            return
        self.closed = True
        # Unblock offer/play waiters so interrupt does not sit on track events.
        self.opened.set()
        self.video_ready.set()
        self.audio_ready.set()
        if self.channel is not None and self.channel.readyState == "open":
            self.channel.send(json.dumps({"type": "stop"}))
            await asyncio.sleep(0)
        tasks = [t for t in self.tasks if t is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        peers = list(self.viewers) + ([self.pc] if self.pc else [])
        await asyncio.gather(*(pc.close() for pc in peers), return_exceptions=True)
        self.viewers.clear()
        await self.http.aclose()
