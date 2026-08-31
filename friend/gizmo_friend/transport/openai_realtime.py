from __future__ import annotations

import asyncio
import base64
import json
import os
from typing import Any

import websockets
from websockets.exceptions import ConnectionClosed

from gizmo_friend.tools.allowlist import TOOL_SCHEMAS, assert_allowlist
from gizmo_friend.transport.base import TransportEvent

MODEL = "gpt-realtime-2.1-mini"
REALTIME_URL = f"wss://api.openai.com/v1/realtime?model={MODEL}"

AUDIO_DELTA = {"response.output_audio.delta", "response.audio.delta"}
TEXT_DELTA = {
    "response.output_audio_transcript.delta",
    "response.audio_transcript.delta",
    "response.output_text.delta",
    "response.text.delta",
}


def session_update_payload(instructions: str) -> dict[str, Any]:
    assert_allowlist(TOOL_SCHEMAS)
    return {
        "type": "session.update",
        "session": {
            "type": "realtime",
            "model": MODEL,
            "instructions": instructions,
            "output_modalities": ["audio"],
            "reasoning": {"effort": "low"},
            "tool_choice": "auto",
            "tools": TOOL_SCHEMAS,
            "audio": {
                "input": {
                    "format": {"type": "audio/pcm", "rate": 24000},
                    "turn_detection": None,
                },
                "output": {
                    "format": {"type": "audio/pcm", "rate": 24000},
                    "voice": "marin",
                },
            },
        },
    }


class OpenAIRealtimeTransport:
    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key if api_key is not None else os.environ.get("OPENAI_API_KEY")
        self._ws: Any = None
        self._queue: asyncio.Queue[TransportEvent | None] = asyncio.Queue()
        self._reader: asyncio.Task[None] | None = None
        self._current_item = ""
        self.instructions = ""

    async def connect(self, instructions: str) -> None:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY missing")
        self.instructions = instructions
        self._ws = await websockets.connect(
            REALTIME_URL,
            additional_headers={"Authorization": f"Bearer {self.api_key}"},
            max_size=16 * 1024 * 1024,
        )
        await self._send(session_update_payload(instructions))
        self._reader = asyncio.create_task(self._read_loop())

    async def close(self) -> None:
        if self._reader:
            self._reader.cancel()
        if self._ws:
            await self._ws.close()
        await self._queue.put(None)

    async def send_text(self, text: str) -> None:
        await self._send(
            {
                "type": "conversation.item.create",
                "item": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": text}],
                },
            }
        )
        await self.request_response()

    async def send_audio(self, pcm: bytes) -> None:
        encoded = base64.b64encode(pcm).decode("ascii")
        await self._send({"type": "input_audio_buffer.append", "audio": encoded})

    async def commit_audio(self) -> None:
        await self._send({"type": "input_audio_buffer.commit"})

    async def interrupt(self, played_ms: int = 0, item_id: str = "") -> None:
        await self._send({"type": "response.cancel"})
        target = item_id or self._current_item
        if target:
            await self._send(
                {
                    "type": "conversation.item.truncate",
                    "item_id": target,
                    "content_index": 0,
                    "audio_end_ms": max(0, played_ms),
                }
            )

    async def request_response(self) -> None:
        await self._send({"type": "response.create"})

    async def submit_tool_output(self, call_id: str, output: str) -> None:
        await self._send(
            {
                "type": "conversation.item.create",
                "item": {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": output,
                },
            }
        )
        await self.request_response()

    async def send_image(self, data_url: str) -> None:
        await self._send(
            {
                "type": "conversation.item.create",
                "item": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_image", "image_url": data_url}],
                },
            }
        )

    async def _send(self, event: dict[str, Any]) -> None:
        if not self._ws:
            raise RuntimeError("realtime socket is closed")
        await self._ws.send(json.dumps(event))

    async def _read_loop(self) -> None:
        assert self._ws is not None
        try:
            async for message in self._ws:
                if isinstance(message, bytes):
                    continue
                data = json.loads(message)
                event = self._map(data)
                if event:
                    await self._queue.put(event)
        except ConnectionClosed:
            await self._queue.put(None)
        except asyncio.CancelledError:
            return

    def _map(self, data: dict[str, Any]) -> TransportEvent | None:
        kind = data.get("type") or ""
        if kind in AUDIO_DELTA:
            delta = data.get("delta") or ""
            pcm = base64.b64decode(delta) if delta else b""
            item_id = data.get("item_id") or ""
            if item_id:
                self._current_item = item_id
            return TransportEvent(kind="audio", pcm=pcm, item_id=item_id, raw=data)
        if kind in TEXT_DELTA:
            return TransportEvent(kind="transcript_delta", text=str(data.get("delta") or ""), raw=data)
        if kind in {
            "response.output_audio_transcript.done",
            "response.audio_transcript.done",
        }:
            return TransportEvent(kind="transcript", text=str(data.get("transcript") or ""), raw=data)
        if kind == "response.function_call_arguments.done":
            raw_args = data.get("arguments") or "{}"
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
            except json.JSONDecodeError:
                args = {}
            if not isinstance(args, dict):
                args = {}
            return TransportEvent(
                kind="function_call",
                name=str(data.get("name") or ""),
                arguments=args,
                call_id=str(data.get("call_id") or ""),
                raw=data,
            )
        if kind == "response.done":
            return TransportEvent(kind="done", raw=data)
        if kind == "response.cancelled":
            return TransportEvent(kind="cancelled", raw=data)
        if kind == "input_audio_buffer.speech_started":
            return TransportEvent(kind="speech_started", raw=data)
        if kind == "error":
            err = data.get("error") or {}
            message = err.get("message") if isinstance(err, dict) else str(err)
            return TransportEvent(kind="error", text=str(message or "realtime error"), raw=data)
        return None

    def __aiter__(self) -> OpenAIRealtimeTransport:
        return self

    async def __anext__(self) -> TransportEvent:
        item = await self._queue.get()
        if item is None:
            raise StopAsyncIteration
        return item
