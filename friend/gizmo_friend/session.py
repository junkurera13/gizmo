from __future__ import annotations

import asyncio
import base64
import json
import os
import uuid
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

from gizmo_friend.audio_out import BroadcastMouth, Mouth
from gizmo_friend.brain.memory import MemoryProvider, memory_provider_from_env
from gizmo_friend.brain.reasoning import ReasoningProvider, reasoning_provider_from_env
from gizmo_friend.brain.transcripts import TranscriptStore
from gizmo_friend.body_protocol import (
    BodyEvent,
    Frame,
    MicChunk,
    Navigate,
    Power,
    PushToTalk,
    Select,
    TextLine,
    WorldCamera,
)
from gizmo_friend.memory import Memory
from gizmo_friend.prefix import assemble_prefix
from gizmo_friend.prompt import FROZEN_PROMPT
from gizmo_friend.states import State, StateMachine
from gizmo_friend.tools.allowlist import ALLOWED_TOOLS
from gizmo_friend.tools.show import VideoBackend
from gizmo_friend.tools.think import ThinkBackend
from gizmo_friend.transport.base import Transport
from gizmo_friend.transport.fake import FakeTransport
from gizmo_friend.transport.gemini_live import GeminiLiveTransport
from gizmo_reach.outbox import ParentOutbox

Listener = Callable[[dict[str, Any]], Any]


class _LegacyReasoningAdapter(ReasoningProvider):
    """Temporary source-compatibility for callers that injected ThinkBackend."""

    def __init__(self, backend: ThinkBackend) -> None:
        self.backend = backend

    async def reason(self, question: str, memory_context: str = "") -> str | None:
        del memory_context
        return await self.backend.answer(question)


class GizmoSession:
    """Central agent controller shared by the emulator and the physical device."""

    def __init__(
        self,
        data_dir: Path,
        mouth: Mouth | None = None,
        camera: WorldCamera | None = None,
        outbox: ParentOutbox | None = None,
        video: VideoBackend | None = None,
        thinker: ThinkBackend | None = None,
        openai_key: str | None = None,
        gemini_key: str | None = None,
        memory_provider: MemoryProvider | None = None,
        reasoning_provider: ReasoningProvider | None = None,
        user_id: str | None = None,
        transport_factory: Callable[[str], Transport] | None = None,
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
        # Legacy injection point only; Adaptive Media is not activated in V1.
        self.video = video
        self.show_hold_s = show_hold_s
        self.boot_s = boot_s
        self.idle_sleep_s = idle_sleep_s
        # openai_key/thinker remain accepted so older callers do not break;
        # neither is exposed to the agent as an alternate router.
        self.openai_key = openai_key
        self.gemini_key = (
            gemini_key if gemini_key is not None else os.environ.get("GEMINI_API_KEY")
        )
        self.thinker = thinker
        self.memory_provider = memory_provider or memory_provider_from_env()
        self.reasoning = (
            reasoning_provider
            or (_LegacyReasoningAdapter(thinker) if thinker else None)
            or reasoning_provider_from_env(self.gemini_key)
        )
        self.user_id = user_id or os.environ.get("GIZMO_USER_ID", "gizmo-local-user")
        self.session_id = uuid.uuid4().hex
        self.transcripts = TranscriptStore(self.data_dir / "transcripts")
        self._memory_context = ""
        self._memory_tasks: set[asyncio.Task[Any]] = set()
        self._memory_loaded = False
        self._transport_factory = transport_factory
        self._resume_handle = ""
        self._connect_lock = asyncio.Lock()
        self._reconnect_task: asyncio.Task[None] | None = None
        self.last_still: str | None = None
        self.last_subject = "thing"
        self.viewing_page = False
        self._page_lit = False
        self.transport_name = "gemini" if self.gemini_key else "fake"
        self._transport: Transport | None = None
        self._pump: asyncio.Task[None] | None = None
        self._listeners: list[asyncio.Queue[dict[str, Any]]] = []
        self._connected = False
        self._item_id = ""
        self._boot_task: asyncio.Task[None] | None = None
        self._idle_task: asyncio.Task[None] | None = None
        self._last_activity = 0.0
        self._ptt_active = False
        # The talk button works like a phone's side button: tap toggles
        # sleep/wake, and only a hold past this threshold opens the mic.
        self.ptt_hold_s = 0.35
        self._ptt_press_task: asyncio.Task[None] | None = None
        self._mic_preroll: deque[bytes] = deque()
        self._mic_preroll_bytes = 0
        self._mic_preroll_limit = 24_000  # 500 ms of 24 kHz mono PCM16
        self._camera_dirty = False
        self._closing = False

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
        if self._memory_context.strip():
            prefix += (
                "\n\nPERSISTENT MEMORY FROM MEMOBASE\n"
                "Use only when relevant. Never mention the memory system.\n"
                f"{self._memory_context.strip()}"
            )
        return prefix

    async def emit(self, event: dict[str, Any]) -> None:
        event = {
            **event,
            "state": self.machine.state.value,
            "power": self.machine.powered(),
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
        if isinstance(event, Select):
            await self.on_select()
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
            self._camera_dirty = bool(event.image)
            await self.emit({"type": "frame", "hint": event.hint})
            if self._ready_for_input() and self._camera_dirty:
                await self._ensure_connected()
                await self._send_camera_frame()

    async def on_select(self) -> None:
        if not self._ready_for_input():
            return

        if self.machine.state is State.TALKING:
            await self._interrupt()
            self.machine.apply("select")
            await self.emit({"type": "interrupted"})
            return
        if self.machine.state is State.LISTENING:
            self.machine.apply("select")
            await self.emit({"type": "select"})
            return
        if self.machine.can("select"):
            await self._interrupt()
            self.machine.apply("select")
            self.viewing_page = False
            self._page_lit = False
            await self.emit({"type": "interrupted"})

    async def on_power(self, on: bool) -> None:
        if on:
            if self.machine.state is State.POWERED_OFF:
                self.session_id = uuid.uuid4().hex
                self.transcripts = TranscriptStore(self.data_dir / "transcripts")
                self._memory_context = ""
                self._memory_loaded = False
                self._resume_handle = ""
                self.machine.apply("power_on")
                await self.emit({"type": "state", "reason": "switch"})
                self._boot_task = asyncio.create_task(self._boot())
            return
        if self.machine.state is State.POWERED_OFF:
            return
        if self._boot_task and not self._boot_task.done():
            self._boot_task.cancel()
        self._cancel_press_watch()
        self._ptt_active = False
        self._clear_mic_preroll()
        self.memory.rewrite_summary()
        self._flush_transcript_turns()
        self._background_memory(self.memory_provider.flush(self.user_id))
        if self.machine.can("power_off"):
            self.machine.apply("power_off")
        self.viewing_page = False
        self._page_lit = False
        await self.emit({"type": "state", "reason": "switch"})
        # Power-off is a local body transition and must complete even if the
        # cloud voice socket has already gone stale. Cancel cloud output only
        # after the device is observably asleep; _interrupt itself fails soft.
        await self._interrupt()
        await self._disconnect_transport()

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
        if not self._ready_for_input() or cleaned not in {"up", "down"}:
            return
        await self.emit({"type": "navigate", "direction": cleaned})

    async def on_push_to_talk(self, active: bool) -> None:
        # The talk button is a phone side button: press while asleep wakes,
        # a tap while awake sleeps, and only a hold opens the mic.
        if self.machine.state is State.POWERED_OFF:
            return
        if self.machine.state is State.ASLEEP:
            if active:
                await self._wake_from_sleep()
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
            self._clear_mic_preroll()
            await self._sleep(reason="ptt")
            return
        self._ptt_press_task = None

        if not self._ptt_active:
            return
        self._ptt_active = False
        if self._transport:
            await self._transport.commit_audio()
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
            self.machine.apply("select")
            await self.emit({"type": "interrupted"})
        if self._transport:
            await self._send_camera_frame()
            await self._transport.begin_audio()
            while self._mic_preroll:
                await self._transport.send_audio(self._mic_preroll.popleft())
            self._mic_preroll_bytes = 0
        await self.emit({"type": "ptt", "active": True})

    async def on_text(self, text: str) -> None:
        cleaned = text.strip()
        if not cleaned:
            return
        if not self._ready_for_input():
            return
        self.memory.remember_from_utterance(cleaned)
        self._record_transcript("user", cleaned)
        await self._ensure_connected()
        if self._transport:
            await self._send_camera_frame()
            await self._transport.send_text(cleaned)

    async def on_mic(self, pcm: bytes) -> None:
        if not self._ready_for_input():
            return
        if not self._ptt_active:
            if self._ptt_press_task and not self._ptt_press_task.done():
                self._append_mic_preroll(pcm)
            return
        await self._ensure_connected()
        if self._transport:
            await self._transport.send_audio(pcm)

    async def close(self) -> None:
        self._closing = True
        if self.machine.state is not State.POWERED_OFF:
            self.memory.rewrite_summary()
        for task in (self._boot_task, self._idle_task, self._pump, self._reconnect_task):
            if task:
                task.cancel()
        if self._transport:
            await self._transport.close()
        self._flush_transcript_turns()
        self._background_memory(self.memory_provider.flush(self.user_id))
        if self._memory_tasks:
            try:
                async with asyncio.timeout(3.0):
                    await asyncio.gather(*tuple(self._memory_tasks), return_exceptions=True)
            except TimeoutError:
                for task in self._memory_tasks:
                    task.cancel()
        await self.memory_provider.close()
        await self.reasoning.close()
        self.memory.close()

    def _ready_for_input(self) -> bool:
        return self.machine.state not in {State.POWERED_OFF, State.ASLEEP, State.BOOTING}

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
        await self._sleep(reason="idle")

    async def _sleep(self, reason: str) -> None:
        if not self.machine.can("sleep"):
            return
        self._cancel_press_watch()
        self._ptt_active = False
        self._clear_mic_preroll()
        self.memory.rewrite_summary()
        self._flush_transcript_turns()
        self._background_memory(self.memory_provider.flush(self.user_id))
        self.machine.apply("sleep")
        self.viewing_page = False
        self._page_lit = False
        await self.emit({"type": "state", "reason": reason})
        await self._interrupt()

    async def _wake_from_sleep(self) -> None:
        if not self.machine.can("wake"):
            return
        self.machine.apply("wake")
        self._touch()
        await self.emit({"type": "state", "reason": "ptt"})
        self._ensure_idle_watch()
        await self._wake()

    async def _wake(self) -> None:
        await self._ensure_connected()
        if self._transport:
            await self._transport.request_response()

    async def _interrupt(self) -> None:
        self.mouth.cancel()
        if self._transport:
            try:
                await self._transport.interrupt(
                    played_ms=self.mouth.played_ms,
                    item_id=self._item_id,
                )
            except Exception as error:  # noqa: BLE001 - controls stay local when cloud is stale
                await self.emit(
                    {
                        "type": "error",
                        "message": f"voice interrupt failed: {error}",
                    }
                )

    async def _load_memory_context(self) -> None:
        if self._memory_loaded:
            return
        try:
            async with asyncio.timeout(1.5):
                self._memory_context = await self.memory_provider.context(self.user_id)
            self._memory_loaded = True
            await self.emit({"type": "memory", "status": "ready"})
        except TimeoutError:
            await self.emit({"type": "memory", "status": "timeout"})
        except Exception as error:  # noqa: BLE001 - memory cannot stop realtime boot
            await self.emit({"type": "error", "message": f"memory unavailable: {error}"})
        finally:
            # Retrieval happens once at startup. A slow memory service must not
            # be retried on the user's first realtime turn.
            self._memory_loaded = True

    def _record_transcript(self, role: str, text: str) -> None:
        transcript_role = "assistant" if role == "assistant" else "user"
        self.transcripts.append(
            session_id=self.session_id,
            user_id=self.user_id,
            role=transcript_role,
            text=text,
        )

    def _flush_transcript_turns(self) -> None:
        completed = self.transcripts.take_completed_turns()
        if completed:
            self._background_memory(self.memory_provider.remember(self.user_id, completed))

    def _background_memory(self, operation: Any) -> None:
        async def guarded() -> None:
            try:
                await operation
            except Exception as error:  # noqa: BLE001 - memory is explicitly fail-soft
                if not self._closing:
                    await self.emit({"type": "error", "message": f"memory write failed: {error}"})

        task = asyncio.create_task(guarded())
        self._memory_tasks.add(task)
        task.add_done_callback(self._memory_tasks.discard)

    def _append_mic_preroll(self, pcm: bytes) -> None:
        if not pcm:
            return
        self._mic_preroll.append(pcm)
        self._mic_preroll_bytes += len(pcm)
        while self._mic_preroll and self._mic_preroll_bytes > self._mic_preroll_limit:
            self._mic_preroll_bytes -= len(self._mic_preroll.popleft())

    def _clear_mic_preroll(self) -> None:
        self._mic_preroll.clear()
        self._mic_preroll_bytes = 0

    async def _send_camera_frame(self) -> None:
        if not self._camera_dirty or not self._transport:
            return
        frame = self.camera.grab()
        if not frame.image:
            self._camera_dirty = False
            return
        mime = _image_mime(frame.image, frame.mime)
        data_url = f"data:{mime};base64,{base64.b64encode(frame.image).decode('ascii')}"
        await self._transport.send_image(data_url)
        self._camera_dirty = False

    def _schedule_reconnect(self) -> None:
        if self._closing or not self.machine.awake():
            return
        if self._reconnect_task and not self._reconnect_task.done():
            return
        self._reconnect_task = asyncio.create_task(self._reconnect())

    async def _reconnect(self) -> None:
        old = self._transport
        self._transport = None
        self._connected = False
        if old:
            await old.close()
        await self.emit({"type": "connection", "status": "reconnecting"})
        try:
            await asyncio.sleep(0.25)
            await self._ensure_connected()
            await self.emit({"type": "connection", "status": "connected"})
        except asyncio.CancelledError:
            return
        except Exception as error:  # noqa: BLE001
            await self.emit({"type": "error", "message": f"reconnect failed: {error}"})

    async def _disconnect_transport(self) -> None:
        transport = self._transport
        self._transport = None
        self._connected = False
        if self._pump:
            self._pump.cancel()
            self._pump = None
        if transport:
            try:
                async with asyncio.timeout(1.0):
                    await transport.close()
            except Exception:  # noqa: BLE001 - power remains local
                return

    async def _ensure_connected(self) -> None:
        if self._connected and self._transport:
            return
        async with self._connect_lock:
            if self._connected and self._transport:
                return
            await self._load_memory_context()
            instructions = self.instructions()
            candidates: list[tuple[str, Callable[[], Transport]]] = []
            if self._transport_factory:
                candidates.append(("custom", lambda: self._transport_factory(self._resume_handle)))
            elif self.gemini_key:
                candidates.append(
                    (
                        "gemini",
                        lambda: GeminiLiveTransport(
                            self.gemini_key,
                            resume_handle=self._resume_handle,
                        ),
                    )
                )
            candidates.append(("fake", lambda: FakeTransport(lambda: self.memory.prefix_memory())))
            for name, build in candidates:
                transport = build()
                try:
                    await transport.connect(instructions)
                except Exception as error:  # noqa: BLE001 — fail soft, never hang boot
                    await self.emit({"type": "error", "message": f"{name} unreachable: {error}"})
                    continue
                self._transport = transport
                self.transport_name = name
                self._connected = True
                self._pump = asyncio.create_task(self._pump_events(transport))
                return
            raise RuntimeError("no Gizmo transport available")

    async def _pump_events(self, transport: Transport) -> None:
        try:
            async for event in transport:
                await self._on_transport(event)
        except asyncio.CancelledError:
            return
        except StopAsyncIteration:
            return
        finally:
            if not self._closing and transport is self._transport and self.machine.awake():
                self._schedule_reconnect()

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
            self._record_transcript("assistant", event.text)
            await self.emit({"type": "transcript", "role": "gizmo", "text": event.text})
            return
        if kind == "user_transcript":
            self.memory.remember_from_utterance(event.text)
            self._record_transcript("user", event.text)
            await self.emit({"type": "transcript", "role": "user", "text": event.text})
            return
        if kind == "function_call":
            result = await self._run_tool(event.name, event.arguments)
            if self._transport:
                await self._transport.submit_tool_output(event.call_id, json.dumps(result))
            return
        if kind == "speech_started":
            if self.machine.state is State.TALKING:
                await self._interrupt()
                self.machine.apply("select")
                await self.emit({"type": "interrupted"})
            return
        if kind in {"done", "cancelled"}:
            self.mouth.mark_idle()
            if kind == "done":
                self._flush_transcript_turns()
            if kind == "done" and event.text:
                await self.emit({"type": "transcript", "role": "gizmo", "text": event.text})
            if self.machine.state is State.TALKING and self.machine.can("done"):
                self.machine.apply("done")
            if not self._page_lit:
                self.viewing_page = False
            await self.emit({"type": "state"})
            return
        if kind == "grounding":
            await self.emit({"type": "grounding", "metadata": event.raw})
            return
        if kind == "session_resumption":
            self._resume_handle = event.text
            return
        if kind in {"reconnect_required", "disconnected"}:
            self._schedule_reconnect()
            return
        if kind == "error":
            await self.emit({"type": "error", "message": event.text})

    async def _run_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name not in ALLOWED_TOOLS:
            return {"ok": False, "reason": f"unknown tool {name}"}
        if name == "deep_think":
            question = str(arguments.get("question") or "").strip()
            if not question:
                return {"ok": False, "reason": "question is required"}
            if self.machine.can("think"):
                self.machine.apply("think")
            await self.emit({"type": "state"})
            try:
                answer = await self.reasoning.reason(question, self._memory_context)
            except Exception as error:  # noqa: BLE001 - deep model must fail soft
                answer = None
                await self.emit({"type": "error", "message": f"deep_think failed: {error}"})
            result = (
                {"ok": True, "answer": answer}
                if answer
                else {
                    "ok": False,
                    "reason": "reasoning model unavailable",
                    "say": "Big one. My deeper brain is offline right now.",
                }
            )
            if self.machine.state is State.THINKING:
                self.machine.apply("done")
            await self.emit({"type": "tool", "name": "deep_think", "result": result})
            return result
        if name == "set_expression":
            expression = str(arguments.get("expression") or "").strip().lower()
            allowed = {"idle", "curious", "thinking", "happy", "concerned", "surprised"}
            if expression not in allowed:
                return {"ok": False, "reason": "invalid expression"}
            result = {"ok": True, "expression": expression}
            await self.emit({"type": "expression", "expression": expression})
            return result
        return {"ok": False, "reason": "unhandled"}


def _image_mime(image: bytes, declared: str) -> str:
    if image.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if image.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if image.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if image.startswith(b"RIFF") and image[8:12] == b"WEBP":
        return "image/webp"
    return declared if declared.startswith("image/") else "image/jpeg"


# Existing imports and third-party callers can migrate incrementally.
Friend = GizmoSession
