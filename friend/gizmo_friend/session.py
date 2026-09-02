from __future__ import annotations

import asyncio
import base64
import json
import os
import uuid
from collections import deque
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from gizmo_friend.audio_out import Mouth
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
from gizmo_friend.prompt import FROZEN_PROMPT
from gizmo_friend.states import State, StateMachine
from gizmo_friend.tools.allowlist import ALLOWED_TOOLS
from gizmo_friend.transport.base import Transport
from gizmo_friend.transport.gemini_live import GeminiLiveTransport

Listener = Callable[[dict[str, Any]], Any]

EXPRESSIONS = {"idle", "curious", "thinking", "happy", "concerned", "surprised"}
# Placeholder vocabulary for set_expression. Not the character. Glass ignores it.


def _today() -> str:
    """The kid's local date, e.g. 'Wednesday 2 September 2026'. GIZMO_TZ picks the zone."""
    zone = os.environ.get("GIZMO_TZ", "UTC")
    try:
        now = datetime.now(ZoneInfo(zone))
    except Exception:  # noqa: BLE001 - a bad zone name must not stop a boot
        now = datetime.now(ZoneInfo("UTC"))
    return now.strftime("%A %-d %B %Y")


class GizmoSession:
    """Central agent controller shared by the emulator and the physical device."""

    _RECONNECT_DELAYS_S = (0.25, 1.0, 3.0)

    def __init__(
        self,
        data_dir: Path,
        mouth: Mouth | None = None,
        camera: WorldCamera | None = None,
        gemini_key: str | None = None,
        memory_provider: MemoryProvider | None = None,
        reasoning_provider: ReasoningProvider | None = None,
        user_id: str | None = None,
        transport_factory: Callable[[str], Transport] | None = None,
        # Matches the glass splash: ~1.75 s blink, then the wordmark holds.
        boot_s: float = 3.8,
        idle_sleep_s: float = 120.0,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.machine = StateMachine()
        self.mouth = mouth or Mouth()
        self.camera = camera or WorldCamera()
        self.boot_s = boot_s
        self.idle_sleep_s = idle_sleep_s
        self.gemini_key = (
            gemini_key if gemini_key is not None else os.environ.get("GEMINI_API_KEY")
        )
        self._transport_factory = transport_factory
        if not self.gemini_key and not self._transport_factory:
            raise RuntimeError("GEMINI_API_KEY is required: Gizmo has no offline brain")
        self.memory_provider = memory_provider or memory_provider_from_env()
        self.reasoning = reasoning_provider or reasoning_provider_from_env(self.gemini_key)
        self.user_id = user_id or os.environ.get("GIZMO_USER_ID", "gizmo-local-user")
        self.session_id = uuid.uuid4().hex
        self.transcripts = TranscriptStore(self.data_dir / "transcripts")
        self._memory_context = ""
        self._memory_tasks: set[asyncio.Task[Any]] = set()
        self._memory_write_lock = asyncio.Lock()
        self._memory_loaded = False
        self._resume_handle = ""
        self._connect_lock = asyncio.Lock()
        self._reconnect_task: asyncio.Task[None] | None = None
        self._warm_task: asyncio.Task[None] | None = None
        self.transport_name = "gemini"
        self._transport: Transport | None = None
        self._pump: asyncio.Task[None] | None = None
        self._listeners: list[asyncio.Queue[dict[str, Any]]] = []
        self._connected = False
        self._item_id = ""
        self._boot_task: asyncio.Task[None] | None = None
        self._idle_task: asyncio.Task[None] | None = None
        self._last_activity = 0.0
        # The talk button does one thing: while it is down, Gizmo listens.
        # A press also wakes him; there is no tap gesture to disambiguate.
        self._ptt_pressed = False
        self._ptt_active = False
        self._ptt_audio_ready = False
        self._ptt_open_task: asyncio.Task[None] | None = None
        # Mic audio that arrives before the cloud turn is open is buffered and
        # replayed in order. Generous, because a reconnect after a nap must
        # never eat the start of a sentence.
        self._mic_preroll: deque[bytes] = deque()
        self._mic_preroll_bytes = 0
        self._mic_preroll_limit = 480_000  # 10 s of 24 kHz mono PCM16
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
        # The date lets him read the memory block's episode dates as "last
        # time" and "a while ago" without a clock tool. Fresh per connect.
        prefix = FROZEN_PROMPT + f"\n\nTODAY\n{_today()}"
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
            # Glass is alive (face) whenever he's awake.
            "screen": self.machine.awake(),
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
            return
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
        if self.machine.state is State.ASLEEP:
            # Any button wakes him. The waking press itself means nothing more.
            await self._wake_from_sleep(reason="select")
            return
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
            await self.emit({"type": "interrupted"})

    async def on_power(self, on: bool) -> None:
        if on:
            if self.machine.state is State.BOOTING:
                return
            if self.machine.state is not State.POWERED_OFF:
                # Rising edge from the body. If we weren't off, we desynced —
                # cut power first so this is a real cold boot, not a wake.
                await self._cut_power()
            self.session_id = uuid.uuid4().hex
            self.transcripts = TranscriptStore(self.data_dir / "transcripts")
            self._memory_context = ""
            self._memory_loaded = False
            self._resume_handle = ""
            self.machine.apply("power_on")
            await self.emit({"type": "state", "reason": "switch"})
            self._boot_task = asyncio.create_task(self._boot())
            return
        await self._cut_power()

    async def _cut_power(self) -> None:
        """Hard off. Not sleep. Sleep is idle-only."""
        if self.machine.state is State.POWERED_OFF:
            return
        if self._boot_task and not self._boot_task.done():
            self._boot_task.cancel()
            self._boot_task = None
        self._cancel_warm()
        self._reset_ptt()
        self._flush_transcript_turns()
        self._background_memory(self.memory_provider.flush(self.user_id))
        if self.machine.can("power_off"):
            self.machine.apply("power_off")
        else:
            self.machine.state = State.POWERED_OFF
        await self.emit({"type": "state", "reason": "switch"})
        # Power-off is a local body transition and must complete even if the
        # cloud voice socket has already gone stale. Cancel cloud output only
        # after the device is observably off; _interrupt itself fails soft.
        await self._interrupt()
        await self._disconnect_transport()

    async def _boot(self) -> None:
        """Fixed splash on the glass. Brain connect runs in parallel and must
        not stretch or freeze the boot animation."""
        try:
            self._warm_connection()
            await asyncio.sleep(self.boot_s)
        except asyncio.CancelledError:
            return
        if self.machine.state is not State.BOOTING:
            return
        self.machine.apply("boot_done")
        self._touch()
        await self.emit({"type": "state"})
        self._ensure_idle_watch()

    async def on_navigate(self, direction: str) -> None:
        cleaned = direction.strip().lower()
        if cleaned not in {"up", "down"}:
            return
        if self.machine.state is State.ASLEEP:
            await self._wake_from_sleep(reason="navigate")
            return
        if not self._ready_for_input():
            return
        await self.emit({"type": "navigate", "direction": cleaned})

    async def on_push_to_talk(self, active: bool) -> None:
        """Press: he listens (waking first if he must). Release: he answers."""
        if self.machine.state is State.POWERED_OFF:
            return
        if active:
            if self._ptt_pressed:
                return
            if self.machine.state is State.ASLEEP:
                await self._wake_from_sleep(reason="ptt")
            if not self._ready_for_input():
                return
            self._ptt_pressed = True
            self._ptt_open_task = asyncio.create_task(self._open_mic())
            return

        if not self._ptt_pressed:
            return
        self._ptt_pressed = False
        # A release while the cloud turn is still opening waits for it, so
        # buffered audio lands before the commit. asyncio.wait keeps a
        # cancelled opener from unwinding this handler.
        if self._ptt_open_task:
            await asyncio.wait({self._ptt_open_task})
            self._ptt_open_task = None
        if not self._ptt_active:
            return
        self._ptt_active = False
        self._ptt_audio_ready = False
        if self._transport:
            await self._transport.commit_audio()
        await self.emit({"type": "ptt", "active": False})

    def _reset_ptt(self) -> None:
        if self._ptt_open_task and not self._ptt_open_task.done():
            self._ptt_open_task.cancel()
        self._ptt_open_task = None
        self._ptt_pressed = False
        self._ptt_active = False
        self._ptt_audio_ready = False
        self._clear_mic_preroll()

    async def _open_mic(self) -> None:
        """Button is down: open the cloud turn and let buffered audio through."""
        self._ptt_active = True
        try:
            await self._ensure_connected()
            if self.machine.state is State.TALKING:
                await self._interrupt()
                self.machine.apply("select")
                await self.emit({"type": "interrupted"})
            if self._transport:
                await self._send_camera_frame()
                await self._transport.begin_audio()
                # Audio arriving while connection/activity-start is in
                # flight stays buffered, so it cannot precede activity-start.
                while self._mic_preroll:
                    pcm = self._mic_preroll.popleft()
                    self._mic_preroll_bytes -= len(pcm)
                    await self._transport.send_audio(pcm)
                self._ptt_audio_ready = True
            await self.emit({"type": "ptt", "active": True})
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - surface microphone-turn failures
            self._ptt_active = False
            self._ptt_audio_ready = False
            self._clear_mic_preroll()
            await self.emit({"type": "error", "message": f"microphone turn failed: {error}"})

    async def on_text(self, text: str) -> None:
        cleaned = text.strip()
        if not cleaned:
            return
        if not self._ready_for_input():
            return
        self._record_transcript("user", cleaned)
        await self._ensure_connected()
        if self._transport:
            await self._send_camera_frame()
            await self._transport.send_text(cleaned)

    async def on_mic(self, pcm: bytes) -> None:
        if not self._ready_for_input():
            return
        if not self._ptt_audio_ready:
            if self._ptt_pressed:
                self._append_mic_preroll(pcm)
            return
        await self._ensure_connected()
        if self._transport:
            await self._transport.send_audio(pcm)

    async def close(self) -> None:
        self._closing = True
        self._reset_ptt()
        background = [
            task
            for task in (self._boot_task, self._idle_task, self._pump, self._reconnect_task, self._warm_task)
            if task and not task.done()
        ]
        for task in background:
            task.cancel()
        if background:
            await asyncio.gather(*background, return_exceptions=True)
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
                if self.machine.state is State.LISTENING and not self._ptt_pressed:
                    await self._sleep(reason="idle")
                    return
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            return

    async def _sleep(self, reason: str) -> None:
        """Only idleness puts him to sleep; there is no sleep button."""
        if not self.machine.can("sleep"):
            return
        self._reset_ptt()
        self._flush_transcript_turns()
        self._background_memory(self.memory_provider.flush(self.user_id))
        self.machine.apply("sleep")
        await self.emit({"type": "state", "reason": reason})
        # A sleeping body holds no cloud socket. Google closes idle Live
        # connections after ~10 minutes anyway, and a socket that dies while
        # nobody is listening used to leave the brain dead until power-cycle.
        # The resumption handle survives, so waking continues the conversation.
        self.mouth.cancel()
        self._cancel_warm()
        await self._disconnect_transport()
        # Sleep just flushed new turns to Memobase; waking re-reads context so
        # what the kid said this morning is known this afternoon.
        self._memory_loaded = False

    async def _wake_from_sleep(self, reason: str) -> None:
        if not self.machine.can("wake"):
            return
        self.machine.apply("wake")
        self._touch()
        await self.emit({"type": "state", "reason": reason})
        self._ensure_idle_watch()
        self._warm_connection()

    def _warm_connection(self) -> None:
        """Start the cloud connection now so a hold that follows a wake is not slowed by it."""
        if self._connected and self._transport:
            return
        if self._warm_task and not self._warm_task.done():
            return

        async def warm() -> None:
            try:
                await self._ensure_connected()
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001 - the next hold retries
                await self.emit({"type": "error", "message": f"brain offline: {error}"})

        self._warm_task = asyncio.create_task(warm())

    def _cancel_warm(self) -> None:
        if self._warm_task and not self._warm_task.done():
            self._warm_task.cancel()
        self._warm_task = None

    async def _interrupt(self) -> None:
        self.mouth.cancel()
        if self._transport:
            try:
                await self._transport.interrupt(
                    played_ms=self.mouth.played_ms,
                    item_id=self._item_id,
                )
            except Exception as error:  # noqa: BLE001 - controls stay local when cloud is stale
                await self.emit({"type": "error", "message": f"voice interrupt failed: {error}"})

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
            # Retrieval happens once per connection. A slow memory service must
            # not be retried on the user's first realtime turn.
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
            started = False
            try:
                # Flush must not overtake the transcript insert it belongs to.
                # The lock orders background writes without blocking voice.
                async with self._memory_write_lock:
                    started = True
                    await operation
            except Exception as error:  # noqa: BLE001 - memory is explicitly fail-soft
                if not self._closing:
                    await self.emit({"type": "error", "message": f"memory write failed: {error}"})
            finally:
                if not started:
                    operation.close()

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
        if self._closing:
            return
        if self._reconnect_task and not self._reconnect_task.done():
            return
        if not self.machine.awake():
            # Nobody is listening, so do not reconnect; but forget the dead
            # socket now so the next wake builds a fresh one instead of
            # trusting a connection that no longer exists.
            self._reconnect_task = asyncio.create_task(self._disconnect_transport())
            return
        self._reconnect_task = asyncio.create_task(self._reconnect())

    async def _reconnect(self) -> None:
        await self._disconnect_transport()
        await self.emit({"type": "connection", "status": "reconnecting"})
        last_error: Exception | None = None
        for delay in self._RECONNECT_DELAYS_S:
            try:
                await asyncio.sleep(delay)
                if not self.machine.awake():
                    return
                await self._ensure_connected()
            except asyncio.CancelledError:
                return
            except Exception as error:  # noqa: BLE001 - retry with backoff
                last_error = error
                if not self.machine.awake():
                    return
                continue
            await self.emit({"type": "connection", "status": "connected"})
            return
        await self.emit({"type": "error", "message": f"reconnect failed: {last_error}"})

    async def _disconnect_transport(self) -> None:
        transport = self._transport
        self._transport = None
        self._connected = False
        pump = self._pump
        self._pump = None
        if pump and pump is not asyncio.current_task() and not pump.done():
            pump.cancel()
        if transport:
            try:
                async with asyncio.timeout(1.0):
                    await transport.close()
            except Exception:  # noqa: BLE001 - power remains local
                return

    def _transport_candidates(self) -> list[Callable[[], Transport]]:
        """Connection attempts in order: with the resumption handle, then without.

        Resumption handles expire (about two hours after the last connection).
        A stale handle must cost a retry, not the brain.
        """

        def fresh_handle() -> str:
            self._resume_handle = ""
            return ""

        if self._transport_factory:
            factory = self._transport_factory
            build: Callable[[str], Transport] = factory
        else:
            key = self.gemini_key
            build = lambda handle: GeminiLiveTransport(key, resume_handle=handle)  # noqa: E731
        candidates = [lambda: build(self._resume_handle)]
        if self._resume_handle:
            candidates.append(lambda: build(fresh_handle()))
        return candidates

    async def _ensure_connected(self) -> None:
        if self._connected and self._transport:
            return
        async with self._connect_lock:
            if self._connected and self._transport:
                return
            await self._load_memory_context()
            instructions = self.instructions()
            last_error: Exception | None = None
            for make_transport in self._transport_candidates():
                transport = make_transport()
                try:
                    await transport.connect(instructions)
                except asyncio.CancelledError:
                    await transport.close()
                    raise
                except Exception as error:  # noqa: BLE001 — report, then try the next candidate
                    last_error = error
                    await self.emit({"type": "error", "message": f"gemini unreachable: {error}"})
                    continue
                self._transport = transport
                self._connected = True
                self._pump = asyncio.create_task(self._pump_events(transport))
                return
            raise RuntimeError(f"no Gizmo transport available: {last_error}")

    async def _pump_events(self, transport: Transport) -> None:
        try:
            async for event in transport:
                await self._on_transport(event)
        except asyncio.CancelledError:
            return
        except StopAsyncIteration:
            return
        finally:
            if not self._closing and transport is self._transport:
                self._schedule_reconnect()

    async def _on_transport(self, event: Any) -> None:
        self._touch()
        kind = event.kind
        if kind == "audio":
            await self._start_talking()
            self._item_id = event.item_id or self._item_id
            self.mouth.speak_pcm(event.pcm)
            await self.emit({"type": "audio", "pcm": base64.b64encode(event.pcm).decode("ascii")})
            return
        if kind == "transcript_delta":
            await self._start_talking()
            await self.emit({"type": "transcript_delta", "text": event.text})
            return
        if kind == "transcript":
            await self._start_talking(announce=False)
            self._record_transcript("assistant", event.text)
            await self.emit({"type": "transcript", "role": "gizmo", "text": event.text})
            return
        if kind == "user_transcript":
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

    async def _start_talking(self, announce: bool = True) -> None:
        if self.machine.state is State.LISTENING and self.machine.can("speech_out"):
            self.machine.apply("speech_out")
            self.mouth.mark_playing()
            if announce:
                await self.emit({"type": "state"})

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
            if expression not in EXPRESSIONS:
                return {"ok": False, "reason": "invalid expression"}
            await self.emit({"type": "expression", "expression": expression})
            return {"ok": True, "expression": expression}
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
