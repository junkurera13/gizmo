"""Text brain via OpenRouter. The real agent, no voice yet.

Same frozen prompt, same tools, real judgment. Used when there is no OpenAI
key (or the realtime cloud is down) but an OpenRouter key exists. The
simulator's composer becomes a real conversation with Gizmo, minus audio.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Any

import httpx

from gizmo_friend.tools.allowlist import TOOL_SCHEMAS, assert_allowlist
from gizmo_friend.tools.think import OPENROUTER_KEY_ENV, OPENROUTER_URL
from gizmo_friend.transport.base import TransportEvent

TEXT_MODEL_ENV = "GIZMO_TEXT_MODEL"
DEFAULT_TEXT_MODEL = "openai/gpt-5.6-luna"
KEY_CHECK_URL = "https://openrouter.ai/api/v1/key"

MAX_TOOL_ROUNDS = 4

# Two sentences, then stop. Text models yap; the device does not.
TALK_SENTENCES = 2
AFTER_TOOL_SENTENCES = 4


def shorten(text: str, max_sentences: int) -> str:
    parts = [p for p in re.split(r"(?<=[.!?])\s+", text.strip()) if p]
    return " ".join(parts[:max_sentences])


def chat_tools() -> list[dict[str, Any]]:
    """Realtime-style schemas -> chat-completions tool format."""
    assert_allowlist(TOOL_SCHEMAS)
    return [
        {
            "type": "function",
            "function": {
                "name": schema["name"],
                "description": schema.get("description", ""),
                "parameters": schema.get("parameters", {}),
            },
        }
        for schema in TOOL_SCHEMAS
    ]


class OpenRouterTextTransport:
    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        self.api_key = api_key if api_key is not None else os.environ.get(OPENROUTER_KEY_ENV)
        self.model = model or os.environ.get(TEXT_MODEL_ENV) or DEFAULT_TEXT_MODEL
        self.instructions = ""
        self._queue: asyncio.Queue[TransportEvent | None] = asyncio.Queue()
        self._messages: list[dict[str, Any]] = []
        self._awaiting: set[str] = set()
        self._rounds = 0
        self._cancelled = False

    async def connect(self, instructions: str) -> None:
        if not self.api_key:
            raise RuntimeError("OPENROUTER_API_KEY missing")
        await self._check_key()
        self.instructions = instructions
        self._messages = [{"role": "system", "content": instructions}]

    async def _check_key(self) -> None:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                KEY_CHECK_URL, headers={"Authorization": f"Bearer {self.api_key}"}
            )
        if response.status_code >= 400:
            raise RuntimeError(f"openrouter key rejected ({response.status_code})")

    async def close(self) -> None:
        await self._queue.put(None)

    async def send_text(self, text: str) -> None:
        self._cancelled = False
        self._rounds = 0
        self._messages.append({"role": "user", "content": text})
        await self._advance()

    async def send_audio(self, pcm: bytes) -> None:
        del pcm  # text brain has no ears; the composer is the mouth-side input

    async def commit_audio(self) -> None:
        return

    async def send_image(self, data_url: str) -> None:
        del data_url  # camera lands with the realtime transport

    async def interrupt(self, played_ms: int = 0, item_id: str = "") -> None:
        del played_ms, item_id
        self._cancelled = True
        await self._queue.put(TransportEvent(kind="cancelled"))

    async def request_response(self) -> None:
        # Wake. The frozen prompt knows the beat; let the real agent say it.
        self._cancelled = False
        self._rounds = 0
        self._messages.append(
            {"role": "user", "content": "(the kid just clicked you awake — say your wake line)"}
        )
        await self._advance()

    async def submit_tool_output(self, call_id: str, output: str) -> None:
        tool_message = {"role": "tool", "tool_call_id": call_id, "content": output}
        self._messages.insert(self._tool_slot(call_id), tool_message)
        self._awaiting.discard(call_id)
        if not self._awaiting:
            await self._advance()

    def _tool_slot(self, call_id: str) -> int:
        """Tool results must sit directly after their assistant tool_calls message,
        even if the kid typed something new while the tool was running."""
        for index, message in enumerate(self._messages):
            calls = message.get("tool_calls") if message.get("role") == "assistant" else None
            if calls and any(call.get("id") == call_id for call in calls):
                slot = index + 1
                while slot < len(self._messages) and self._messages[slot].get("role") == "tool":
                    slot += 1
                return slot
        return len(self._messages)

    async def _advance(self) -> None:
        if self._cancelled or self._rounds >= MAX_TOOL_ROUNDS:
            await self._queue.put(TransportEvent(kind="done"))
            return
        self._rounds += 1
        data = await self._complete()
        if data is None:
            await self._queue.put(
                TransportEvent(kind="error", text="text brain unreachable. try again.")
            )
            await self._queue.put(TransportEvent(kind="done"))
            return
        message = (data.get("choices") or [{}])[0].get("message") or {}
        tool_calls = message.get("tool_calls") or []
        content = message.get("content") or ""
        if tool_calls:
            self._messages.append(message)
            if content.strip():
                # The beat line before the spell ("Hold on. Big one.")
                await self._queue.put(
                    TransportEvent(kind="transcript", text=shorten(content, TALK_SENTENCES))
                )
            self._awaiting = {call["id"] for call in tool_calls}
            for call in tool_calls:
                function = call.get("function") or {}
                try:
                    arguments = json.loads(function.get("arguments") or "{}")
                except json.JSONDecodeError:
                    arguments = {}
                await self._queue.put(
                    TransportEvent(
                        kind="function_call",
                        name=str(function.get("name") or ""),
                        arguments=arguments,
                        call_id=str(call["id"]),
                    )
                )
            return
        # After a tool he may carry back up to four short sentences; talk is two.
        cap = AFTER_TOOL_SENTENCES if self._rounds > 1 else TALK_SENTENCES
        spoken = shorten(content, cap)
        # History keeps what he actually said, so he can't reference cut yap.
        self._messages.append({"role": "assistant", "content": spoken or content})
        if spoken:
            await self._queue.put(TransportEvent(kind="transcript", text=spoken))
        await self._queue.put(TransportEvent(kind="done"))

    async def _complete(self) -> dict[str, Any] | None:
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    OPENROUTER_URL,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "messages": self._messages,
                        "tools": chat_tools(),
                        # Cap reserve so small credit balances don't 402.
                        "max_tokens": 2048,
                    },
                )
                if response.status_code >= 400:
                    return None
                return response.json()
        except httpx.HTTPError:
            return None

    def __aiter__(self) -> OpenRouterTextTransport:
        return self

    async def __anext__(self) -> TransportEvent:
        item = await self._queue.get()
        if item is None:
            raise StopAsyncIteration
        return item
