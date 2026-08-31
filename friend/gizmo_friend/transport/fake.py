from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable
from typing import Any

from gizmo_friend.prefix import PrefixMemory
from gizmo_friend.prompt import AFTER_MAKE, AFTER_SHOW, wake_speech
from gizmo_friend.transport.base import TransportEvent

ContextFn = Callable[[], PrefixMemory]

_SEE = re.compile(r"\b(look|see|what(?:'s| is) (?:this|that)|camera|point)\b", re.I)
_SHOW = re.compile(r"\b(show|spell|make it move|do the (?:thing|spell))\b", re.I)
_MAKE = re.compile(r"\b(keep|save|make (?:a )?page|remember this (?:one|page)|mine)\b", re.I)
_REACH = re.compile(r"\b(send|mom|dad|parent|phone|reach)\b", re.I)
_YESTERDAY = re.compile(r"\b(yesterday|last time|remember when|do you remember)\b", re.I)
_BORED = re.compile(r"\b(bored|nothing|whatever|idk|i don't know|meh)\b", re.I)
_WHO = re.compile(r"\b(who are you|what are you|what can you do|are you real)\b", re.I)


def _two_sentences(text: str) -> str:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    kept = [p for p in parts if p][:2]
    out = " ".join(kept).strip()
    banned = (
        "hocus",
        "pocus",
        "merlin",
        "thou ",
        "young wizard",
        "greetings traveler",
        "as an ai",
        "as an AI",
    )
    lower = out.lower()
    if any(b in lower for b in banned):
        return "I'm here. That's the useful part."
    return out


def classify(text: str) -> tuple[str, dict[str, Any]]:
    t = text.strip()
    if _SEE.search(t) and not _SHOW.search(t):
        return "see", {}
    if _SHOW.search(t):
        subject = "pinecone" if "pine" in t.lower() else "thing"
        return "show", {"subject": subject}
    if _MAKE.search(t):
        return "make", {"line": t.strip()}
    if _REACH.search(t):
        return "reach", {}
    return "talk", {"text": t}


def _talk(text: str, memory: PrefixMemory) -> str:
    t = text.strip()
    lower = t.lower()
    if _WHO.search(t):
        return "Gizmo. That's the coat."
    if _YESTERDAY.search(t):
        if memory.episodes:
            last = memory.episodes[-1]
            return _two_sentences(f"Yeah. {last}")
        return "I don't have that. Tell me again."
    if _BORED.search(t):
        return "Yeah. We could look at something."
    if "?" in t:
        if memory.name and memory.name.lower() in lower:
            return f"Hi {memory.name}. I'm still here."
        return "I don't know. We could look."
    if len(t) > 80 and " " not in t.strip()[:10]:
        return "Okay. That's a sentence."
    if not t:
        return "I'm here."
    # nonsense / play / open talk — dry, stop
    if any(ch.isalpha() for ch in t) and len(t.split()) <= 2 and "?" not in t:
        return "Okay. Go on."
    return "Okay. What are we looking at?"


class FakeTransport:
    """Offline stand-in. Same tools and wake lines. Not a second personality."""

    def __init__(self, context: ContextFn) -> None:
        self._context = context
        self._queue: asyncio.Queue[TransportEvent | None] = asyncio.Queue()
        self._pending_tool: str | None = None
        self._last_subject = "thing"
        self._connected = False
        self.instructions = ""

    async def connect(self, instructions: str) -> None:
        self.instructions = instructions
        self._connected = True

    async def close(self) -> None:
        self._connected = False
        await self._queue.put(None)

    async def send_text(self, text: str) -> None:
        intent, args = classify(text)
        if intent in {"see", "show", "make", "reach"}:
            if intent == "show":
                subject = str(args.get("subject") or "thing")
                if subject == "thing":
                    args["subject"] = self._last_subject
                else:
                    self._last_subject = subject
            if intent == "make":
                args["subject"] = args.get("subject") or self._last_subject
                if args.get("line") == text.strip():
                    args["line"] = self._last_subject
            self._pending_tool = intent
            await self._queue.put(
                TransportEvent(
                    kind="function_call",
                    name=intent,
                    arguments=args,
                    call_id=f"fake-{intent}",
                )
            )
            return
        memory = self._context()
        reply = _talk(text, memory)
        await self._speak(reply)

    async def send_audio(self, pcm: bytes) -> None:
        del pcm  # fake has no STT; laptop typed path covers tests

    async def commit_audio(self) -> None:
        return

    async def interrupt(self, played_ms: int = 0, item_id: str = "") -> None:
        del played_ms, item_id
        # drain pending speech
        dumped: list[TransportEvent] = []
        while True:
            try:
                item = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            if item is not None:
                dumped.append(item)
        await self._queue.put(TransportEvent(kind="cancelled"))

    async def request_response(self) -> None:
        memory = self._context()
        await self._speak(wake_speech(memory.name), cap=False)

    async def submit_tool_output(self, call_id: str, output: str) -> None:
        del call_id
        name = self._pending_tool or ""
        self._pending_tool = None
        try:
            data = json.loads(output) if output else {}
        except json.JSONDecodeError:
            data = {}
        if name == "see":
            beat = data.get("beat", "something.")
            await self._speak(str(beat))
        elif name == "show":
            subject = str(data.get("subject") or "").strip()
            if subject and subject != "thing":
                self._last_subject = subject
            await self._speak(AFTER_SHOW)
        elif name == "make":
            await self._speak(AFTER_MAKE)
        elif name == "reach":
            if data.get("ok"):
                await self._speak("It's on its way. I'm not a phone.")
            else:
                await self._speak("Didn't go. We can try later.")
        else:
            await self._speak("Okay.")

    async def send_image(self, data_url: str) -> None:
        del data_url

    async def _speak(self, text: str, cap: bool = True) -> None:
        line = _two_sentences(text) if cap else text.strip()
        await self._queue.put(TransportEvent(kind="transcript", text=line))
        await self._queue.put(TransportEvent(kind="done"))

    def __aiter__(self) -> FakeTransport:
        return self

    async def __anext__(self) -> TransportEvent:
        item = await self._queue.get()
        if item is None:
            raise StopAsyncIteration
        return item
