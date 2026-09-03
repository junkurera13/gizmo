#!/usr/bin/env python3
"""Laptop reference for Gizmo body protocol v1.

Checkpoint 1 covers connection, compatibility, identity and control events.
Microphone, camera, speaker and glass-media adapters are checkpoint 2.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import binascii
import json
import os
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
from websockets.asyncio.client import connect


PROTOCOL_VERSION = 1


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
    client = BodyClient(args.url, args.device_id, args.token)
    hello, glass = await client.connect()
    print(json.dumps(printable(hello), ensure_ascii=False))
    print(json.dumps(printable(glass), ensure_ascii=False))
    print("Commands: power on|off, ptt down|up, up, down, select, say <text>, quit")

    async def read_events() -> None:
        while True:
            print(json.dumps(printable(await client.receive()), ensure_ascii=False))

    reader = asyncio.create_task(read_events())
    try:
        while True:
            line = await asyncio.to_thread(input, "body> ")
            if line.strip().lower() in {"quit", "exit"}:
                return
            event = control(line)
            if event is None:
                print("Unknown command. Use the physical control names shown above.")
                continue
            await client.send(event)
    finally:
        reader.cancel()
        await asyncio.gather(reader, return_exceptions=True)
        await client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Gizmo body protocol v1 reference client")
    parser.add_argument("--url", default=os.environ.get("GIZMO_BRAIN_URL", "http://127.0.0.1:43147"))
    parser.add_argument("--device-id", default=os.environ.get("GIZMO_DEVICE_ID", "gizmo-reference"))
    parser.add_argument("--token", default=os.environ.get("GIZMO_DEVICE_TOKEN", ""))
    args = parser.parse_args()
    try:
        asyncio.run(interactive(args))
    except (ProtocolError, OSError, httpx.HTTPError) as error:
        raise SystemExit(f"reference client: {error}") from error
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
