"""Server-owned Director WebRTC session; the provider key never reaches a browser.

Signaling follows @fal-ai/client 1.11.0-alpha.3's WMA transport. Media is
relayed to viewers, with one upstream generation session and a bounded lease.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable

import httpx
from aioice.ice import TransportPolicy
from aiortc import (
    RTCConfiguration,
    RTCIceServer,
    RTCPeerConnection,
    RTCRtpSender,
    RTCSessionDescription,
)
from aiortc.contrib.media import MediaRelay

ENDPOINT = "https://wma.fal.run"
MODEL = "minimax/h3-max/director"
logger = logging.getLogger(__name__)


def reliable_upstream_ice_servers(servers: list[RTCIceServer]) -> list[RTCIceServer]:
    """Select Fal's TCP TURN relay instead of aiortc's first (UDP) TURN URL.

    aiortc 1.15 supports one TURN server. Fal returns UDP before TCP, so passing
    the complete list silently selects UDP even though a reliable relay is
    available. A lost H.264 packet decodes as green/macroblock damage that then
    gets permanently encoded into the device MJPEG cue.
    """
    for server in servers:
        urls = server.urls if isinstance(server.urls, list) else [server.urls]
        for url in urls:
            if url.startswith("turn:") and "transport=tcp" in url:
                return [
                    RTCIceServer(
                        urls=url,
                        username=server.username,
                        credential=server.credential,
                        credentialType=server.credentialType,
                    )
                ]
    raise RuntimeError("Director did not provide a TCP TURN relay")


def force_relay_only(pc: RTCPeerConnection) -> None:
    """Keep the upstream media on TURN/TCP instead of a lossy direct UDP pair."""
    gatherers = []
    for transceiver in pc.getTransceivers():
        gatherers.append(transceiver.sender.transport.transport.iceGatherer)
    if pc.sctp is not None:
        gatherers.append(pc.sctp.transport.transport.iceGatherer)
    for gatherer in {id(value): value for value in gatherers}.values():
        # aiortc 1.15 does not expose iceTransportPolicy, but its pinned aioice
        # dependency does. Set it before setLocalDescription gathers candidates.
        gatherer._connection._transport_policy = TransportPolicy.RELAY


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
        upstream_servers = reliable_upstream_ice_servers(servers)
        self.pc = pc = RTCPeerConnection(
            RTCConfiguration(iceServers=upstream_servers)
        )
        video = pc.addTransceiver("video", direction="recvonly")
        # Prefer H.264: the device path decodes server-side, where PyAV's VP8
        # decoder has failed on provider packets in some deploys, and H.264's
        # FU-A fragmentation survives relayed media paths better.
        video.setCodecPreferences(
            [c for c in RTCRtpSender.getCapabilities("video").codecs
             if c.mimeType.lower() == "video/h264"]
        )
        pc.addTransceiver("audio", direction="recvonly")
        self.channel = channel = pc.createDataChannel("control")
        force_relay_only(pc)
        logger.info("Director upstream ICE: relay-only TURN/TCP")

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
