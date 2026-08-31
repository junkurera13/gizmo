from __future__ import annotations

import asyncio
import base64
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from gizmo_friend.audio_out import BroadcastMouth, Mouth
from gizmo_friend.body_protocol import (
    BodyEvent,
    Click,
    Frame,
    Hold,
    MicChunk,
    Navigate,
    Power,
    PushToTalk,
    TextLine,
    WorldCamera,
)
from gizmo_friend.memory import Memory
from gizmo_friend.prefix import assemble_prefix
from gizmo_friend.prompt import FROZEN_PROMPT
from gizmo_friend.states import IllegalTransition, State, StateMachine
from gizmo_friend.tools.allowlist import ALLOWED_TOOLS
from gizmo_friend.tools.make import make
from gizmo_friend.tools.reach import reach
from gizmo_friend.tools.see import see
from gizmo_friend.tools.show import VideoBackend, show, video_backend_from_env
from gizmo_friend.tools.think import ThinkBackend, think, think_backend_from_env
from gizmo_friend.transport.fake import FakeTransport
from gizmo_friend.transport.openai_realtime import OpenAIRealtimeTransport
from gizmo_friend.transport.openrouter_text import OpenRouterTextTransport
from gizmo_reach.outbox import ParentOutbox

Listener = Callable[[dict[str, Any]], Any]


class Friend:
    """Laptop brain. One session, six verbs, local memory."""

    def __init__(
        self,
        data_dir: Path,
        mouth: Mouth | None = None,
        camera: WorldCamera | None = None,
        outbox: ParentOutbox | None = None,
        video: VideoBackend | None = None,
        thinker: ThinkBackend | None = None,
        openai_key: str | None = None,
        show_hold_s: float = 2.2,
        boot_s: float = 1.6,
        idle_sleep_s: float = 120.0,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.media_dir = self.data_dir / "media"
        self.media_dir.mkdir(parents=True, exist_ok=True)
        self.memory = Memory(self.data_dir / "gizmo.db")
        self.machine = StateMachine()
        self.mouth = mouth or BroadcastMouth()
        self.camera = camera or WorldCamera()
        self.outbox = outbox or ParentOutbox(self.data_dir / "outbox.jsonl")
        self.video = video if video is not None else video_backend_from_env()
        self.show_hold_s = show_hold_s
        self.boot_s = boot_s
        self.idle_sleep_s = idle_sleep_s
        self.openai_key = openai_key if openai_key is not None else os.environ.get("OPENAI_API_KEY")
        self.openrouter_key = os.environ.get("OPENROUTER_API_KEY")
        self.thinker = thinker if thinker is not None else think_backend_from_env(self.openai_key)
        self.last_still: str | None = None
        self.last_subject = "thing"
        self.viewing_page = False
        self._page_lit = False
        if self.openai_key:
            self.transport_name = "openai"
        elif self.openrouter_key:
            self.transport_name = "openrouter"
        else:
            self.transport_name = "fake"
        self._transport: FakeTransport | OpenAIRealtimeTransport | OpenRouterTextTransport | None = None
        self._pump: asyncio.Task[None] | None = None
        self._listeners: list[asyncio.Queue[dict[str, Any]]] = []
        self._connected = False
        self._item_id = ""
        self._boot_task: asyncio.Task[None] | None = None
        self._idle_task: asyncio.Task[None] | None = None
        self._last_activity = 0.0
        self._ptt_active = False
        # Double-click on the trackball opens the camera; one click closes it.
        self.double_click_s = 0.45
        self._last_click_at = float("-inf")
        self._last_click_state: State | None = None
        # The talk button works like a phone's side button: tap toggles
        # sleep/wake, and only a hold past this threshold opens the mic.
        self.ptt_hold_s = 0.35
        self._ptt_press_task: asyncio.Task[None] | None = None

    @property
    def state(self) -> State:
        return self.machine.state

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._listeners.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        if queue in self._listeners:
            self._listeners.remove(queue)

    def instructions(self) -> str:
        prefix = assemble_prefix(self.memory.prefix_memory())
        if not prefix.startswith(FROZEN_PROMPT):
            raise RuntimeError("prefix lost the frozen prompt")
        return prefix

    async def emit(self, event: dict[str, Any]) -> None:
        event = {
            **event,
            "state": self.machine.state.value,
            # Glass is alive (face) whenever he's awake; "viewing" means a
            # page/still should cover the face right now.
            "screen": self.machine.awake(),
            "viewing": self.machine.screen_on(self.viewing_page),
            "transport": self.transport_name,
        }
        for queue in list(self._listeners):
            await queue.put(event)

    async def handle(self, event: BodyEvent) -> None:
        self._touch()
        if isinstance(event, Click):
            await self.on_click()
        elif isinstance(event, Hold):
            await self.on_hold()
        elif isinstance(event, Power):
            await self.on_power(event.on)
        elif isinstance(event, PushToTalk):
            await self.on_push_to_talk(event.active)
        elif isinstance(event, Navigate):
            await self.on_navigate(event.direction)
        elif isinstance(event, TextLine):
            await self.on_text(event.text)
        elif isinstance(event, MicChunk):
            await self.on_mic(event.pcm)
        elif isinstance(event, Frame):
            self.camera.inject(image=event.image, hint=event.hint, mime=event.mime)
            await self.emit({"type": "frame", "hint": event.hint})

    async def on_click(self) -> None:
        if not self._ready_for_input():
            return

        now = asyncio.get_running_loop().time()
        previous_at = self._last_click_at
        previous_state = self._last_click_state
        self._last_click_at = now
        self._last_click_state = self.machine.state

        # Second fast click while idle: open the camera. The body stays dumb;
        # the brain recognizes the gesture, so real hardware gets it for free.
        if (
            self.machine.state is State.LISTENING
            and previous_state is State.LISTENING
            and now - previous_at <= self.double_click_s
        ):
            self.machine.apply("see")
            await self.emit({"type": "camera", "open": True})
            return

        if self.machine.state is State.TALKING:
            await self._interrupt()
            self.machine.apply("click")
            await self.emit({"type": "interrupted"})
            return
        if self.machine.state is State.LISTENING:
            self.machine.apply("click")
            await self.emit({"type": "select"})
            return
        if self.machine.can("click"):
            await self._interrupt()
            self.machine.apply("click")
            self.viewing_page = False
            self._page_lit = False
            await self.emit({"type": "interrupted"})

    async def on_hold(self) -> None:
        # Reserved. Reaching a parent goes through conversation
        # ("tell mom I'll be 5 mins late"), not a gesture.
        return

    async def on_power(self, on: bool) -> None:
        if on:
            if self.machine.state is State.ASLEEP:
                self.machine.apply("power_on")
                await self.emit({"type": "state"})
                self._boot_task = asyncio.create_task(self._boot())
            return
        if self.machine.state is State.ASLEEP:
            return
        if self._boot_task and not self._boot_task.done():
            self._boot_task.cancel()
        self._ptt_active = False
        await self._interrupt()
        self.memory.rewrite_summary()
        if self.machine.can("power_off"):
            self.machine.apply("power_off")
        self.viewing_page = False
        self._page_lit = False
        await self.emit({"type": "state", "power": False})

    async def _boot(self) -> None:
        """Boot moment: connect the brain while the glass plays wake-up."""
        try:
            loop = asyncio.get_running_loop()
            started = loop.time()
            await self._ensure_connected()
            remaining = self.boot_s - (loop.time() - started)
            if remaining > 0:
                await asyncio.sleep(remaining)
        except asyncio.CancelledError:
            return
        if self.machine.state is not State.BOOTING:
            return
        self.machine.apply("boot_done")
        self._touch()
        await self.emit({"type": "state"})
        self._ensure_idle_watch()
        await self._wake()

    async def on_navigate(self, direction: str) -> None:
        cleaned = direction.strip().lower()
        if not self._ready_for_input() or cleaned not in {"up", "down", "left", "right"}:
            return
        await self.emit({"type": "navigate", "direction": cleaned})

    async def on_push_to_talk(self, active: bool) -> None:
        # The talk button is a phone side button: press while asleep wakes,
        # a tap while awake sleeps, and only a hold opens the mic.
        if self.machine.state is State.ASLEEP:
            if active:
                await self.on_power(True)
            return
        if not self._ready_for_input():
            return

        if active:
            self._cancel_press_watch()
            self._ptt_press_task = asyncio.create_task(self._ptt_hold_watch())
            return

        # Release before the hold threshold: it was a tap. Sleep.
        if self._ptt_press_task and not self._ptt_press_task.done():
            self._cancel_press_watch()
            await self.on_power(False)
            return
        self._ptt_press_task = None

        if not self._ptt_active:
            return
        self._ptt_active = False
        if self._transport:
            await self._transport.commit_audio()
            await self._transport.request_response()
        await self.emit({"type": "ptt", "active": False})

    def _cancel_press_watch(self) -> None:
        if self._ptt_press_task and not self._ptt_press_task.done():
            self._ptt_press_task.cancel()
        self._ptt_press_task = None

    async def _ptt_hold_watch(self) -> None:
        """Held past the threshold: now it's push-to-talk. Mic goes hot."""
        await asyncio.sleep(self.ptt_hold_s)
        self._ptt_active = True
        await self._ensure_connected()
        if self.machine.state is State.TALKING:
            await self._interrupt()
            self.machine.apply("click")
            await self.emit({"type": "interrupted"})
        await self.emit({"type": "ptt", "active": True})

    async def on_text(self, text: str) -> None:
        cleaned = text.strip()
        if not cleaned:
            return
        if not self._ready_for_input():
            return
        self.memory.remember_from_utterance(cleaned)
        await self._ensure_connected()
        if self._transport:
            await self._transport.send_text(cleaned)

    async def on_mic(self, pcm: bytes) -> None:
        if not self._ready_for_input():
            return
        # Mic is only hot while the talk button is held past the threshold.
        if not self._ptt_active:
            return
        await self._ensure_connected()
        if self._transport:
            await self._transport.send_audio(pcm)

    async def close(self) -> None:
        if self.machine.state is not State.ASLEEP:
            self.memory.rewrite_summary()
        for task in (self._boot_task, self._idle_task, self._pump):
            if task:
                task.cancel()
        if self._transport:
            await self._transport.close()
        self.memory.close()

    def _ready_for_input(self) -> bool:
        return self.machine.state not in {State.ASLEEP, State.BOOTING}

    def _touch(self) -> None:
        try:
            self._last_activity = asyncio.get_running_loop().time()
        except RuntimeError:
            pass

    def _ensure_idle_watch(self) -> None:
        if self.idle_sleep_s <= 0:
            return
        if self._idle_task is None or self._idle_task.done():
            self._idle_task = asyncio.create_task(self._idle_watch())

    async def _idle_watch(self) -> None:
        """Like a phone: no interaction for a while -> sleep on his own."""
        try:
            loop = asyncio.get_running_loop()
            while self.machine.awake():
                idle = loop.time() - self._last_activity
                remaining = self.idle_sleep_s - idle
                if remaining > 0:
                    await asyncio.sleep(min(remaining, 1.0))
                    continue
                if self.machine.state is State.LISTENING and not self._ptt_active:
                    await self._sleep_from_idle()
                    return
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            return

    async def _sleep_from_idle(self) -> None:
        self.memory.rewrite_summary()
        if self.machine.can("power_off"):
            self.machine.apply("power_off")
        self.viewing_page = False
        self._page_lit = False
        await self.emit({"type": "state", "power": False, "reason": "idle"})

    async def _wake(self) -> None:
        await self._ensure_connected()
        if self._transport:
            await self._transport.request_response()

    async def _interrupt(self) -> None:
        self.mouth.cancel()
        if self._transport:
            await self._transport.interrupt(played_ms=self.mouth.played_ms, item_id=self._item_id)

    async def _ensure_connected(self) -> None:
        if self._connected and self._transport:
            return
        # Memory is local sqlite — already loaded. Do not await retrieval.
        instructions = self.instructions()
        # Fail-soft chain: live voice -> text brain -> offline stand-in.
        candidates: list[tuple[str, Any]] = []
        if self.openai_key:
            candidates.append(("openai", lambda: OpenAIRealtimeTransport(self.openai_key)))
        if self.openrouter_key:
            candidates.append(("openrouter", lambda: OpenRouterTextTransport(self.openrouter_key)))
        candidates.append(("fake", lambda: FakeTransport(lambda: self.memory.prefix_memory())))
        for name, build in candidates:
            transport = build()
            try:
                await transport.connect(instructions)
            except Exception as error:  # noqa: BLE001 — fail soft, never hang the boot
                await self.emit({"type": "error", "message": f"{name} unreachable: {error}"})
                continue
            self._transport = transport
            self.transport_name = name
            break
        self._connected = True
        self._pump = asyncio.create_task(self._pump_events())

    async def _pump_events(self) -> None:
        assert self._transport is not None
        try:
            async for event in self._transport:
                await self._on_transport(event)
        except asyncio.CancelledError:
            return
        except StopAsyncIteration:
            return

    async def _on_transport(self, event: Any) -> None:
        self._touch()
        kind = event.kind
        if kind == "audio":
            if self.machine.state is State.LISTENING and self.machine.can("speech_out"):
                self.machine.apply("speech_out")
                self.mouth.mark_playing()
                await self.emit({"type": "state"})
            self._item_id = event.item_id or self._item_id
            await self.mouth.speak_pcm(event.pcm)
            await self.emit({"type": "audio", "pcm": base64.b64encode(event.pcm).decode("ascii")})
            return
        if kind == "transcript_delta":
            if self.machine.state is State.LISTENING and self.machine.can("speech_out"):
                self.machine.apply("speech_out")
                self.mouth.mark_playing()
                await self.emit({"type": "state"})
            await self.emit({"type": "transcript_delta", "text": event.text})
            return
        if kind == "transcript":
            if self.machine.state is State.LISTENING and self.machine.can("speech_out"):
                self.machine.apply("speech_out")
                self.mouth.mark_playing()
            await self.mouth.speak_text(event.text)
            await self.emit({"type": "transcript", "role": "gizmo", "text": event.text})
            return
        if kind == "function_call":
            result = await self._run_tool(event.name, event.arguments)
            if self._transport:
                await self._transport.submit_tool_output(event.call_id, json.dumps(result))
            return
        if kind == "speech_started":
            if self.machine.state is State.TALKING:
                await self._interrupt()
                self.machine.apply("click")
                await self.emit({"type": "interrupted"})
            return
        if kind in {"done", "cancelled"}:
            self.mouth.mark_idle()
            if kind == "done" and event.text:
                await self.emit({"type": "transcript", "role": "gizmo", "text": event.text})
            if self.machine.state is State.TALKING and self.machine.can("done"):
                self.machine.apply("done")
            if not self._page_lit:
                self.viewing_page = False
            await self.emit({"type": "state"})
            return
        if kind == "error":
            await self.emit({"type": "error", "message": event.text})

    async def _run_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name not in ALLOWED_TOOLS:
            return {"ok": False, "reason": f"unknown tool {name}"}
        if name == "see":
            if self.machine.can("see"):
                self.machine.apply("see")
            await self.emit({"type": "state"})
            result = await see(self.camera, arguments.get("image"))
            beat = str(result.get("beat") or "")
            if "pinecone" in beat.lower():
                self.last_subject = "pinecone"
            elif beat and beat not in {"dark. nothing to name yet."}:
                self.last_subject = beat.rstrip(".")[:40]
            frame = self.camera.grab()
            if frame.image and self._transport and self.transport_name == "openai":
                mime = frame.mime or "image/jpeg"
                data_url = f"data:{mime};base64,{base64.b64encode(frame.image).decode('ascii')}"
                await self._transport.send_image(data_url)
            if self.machine.state is State.SEEING:
                self.machine.apply("done")
            self.memory.add_episode(f"saw: {result.get('beat')}")
            await self.emit({"type": "tool", "name": "see", "result": result})
            return result
        if name == "think":
            question = str(arguments.get("question") or "").strip()
            if self.machine.can("think"):
                self.machine.apply("think")
            await self.emit({"type": "state"})
            result = await think(self.thinker, question)
            if self.machine.state is State.THINKING:
                self.machine.apply("done")
            if result.get("ok"):
                self.memory.add_episode(f"thought hard about: {question[:80]}")
            await self.emit({"type": "tool", "name": "think", "result": result})
            return result
        if name == "show":
            subject = str(arguments.get("subject") or "").strip()
            if not subject or subject == "thing":
                subject = self.last_subject
            self.last_subject = subject
            if self.machine.can("show"):
                self.machine.apply("show")
            self.viewing_page = True
            self._page_lit = False
            await self.emit({"type": "state"})
            result = await show(subject, self.media_dir, video=self.video)
            self.last_still = result["still"]
            still_url = _public_media(result["still"])
            self.memory.add_episode(f"showed: {subject}")
            await self.emit({"type": "glass", "still": still_url, "clips": result["clips"]})
            # Still first. Then screen off. Then he talks.
            hold = self.show_hold_s
            if result["clips"]:
                hold = max(hold, 0.4)
            if hold:
                await asyncio.sleep(hold)
            if self.machine.state is State.SHOWING:
                self.machine.apply("done")
            self.viewing_page = False
            await self.emit({"type": "state"})
            return {**result, "still": still_url}
        if name == "make":
            line = str(arguments.get("line") or "")
            subject = str(arguments.get("subject") or self.last_subject)
            if self.machine.can("make"):
                self.machine.apply("make")
            self.viewing_page = True
            self._page_lit = True
            await self.emit({"type": "state"})
            page = make(
                self.memory,
                self.media_dir,
                line=line or f"{subject}.",
                subject=subject,
                still_path=self.last_still,
            )
            self.last_still = page.still_path
            if self.machine.state is State.MAKING:
                self.machine.apply("done")
            payload = {
                "ok": True,
                "id": page.id,
                "line": page.line,
                "subject": page.subject,
                "still": _public_media(page.still_path),
            }
            await self.emit({"type": "glass", "still": payload["still"], "clips": [], "page": payload})
            return payload
        if name == "reach":
            if self.machine.can("hold"):
                self.machine.apply("hold")
            await self.emit({"type": "state"})
            page = self.memory.last_page()
            result = reach(self.outbox, page)
            if self.machine.state is State.REACHING:
                self.machine.apply("done")
            self.memory.add_episode("reached a parent" if result.get("ok") else "reach failed soft")
            await self.emit({"type": "tool", "name": "reach", "result": result})
            return result
        return {"ok": False, "reason": "unhandled"}


def _public_media(path: str) -> str:
    name = Path(path).name
    return f"/media/{name}"
