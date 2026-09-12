from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import uuid
from collections import deque
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from gizmo_friend.audio_out import Mouth
from gizmo_friend.brain.images import ImageProvider, NullImageProvider, image_provider_from_env
from gizmo_friend.brain.memory import MemoryProvider, memory_provider_from_env
from gizmo_friend.brain.narration import Narration, NarrationProvider, narration_provider_from_env
from gizmo_friend.brain.reasoning import ReasoningProvider, reasoning_provider_from_env
from gizmo_friend.brain.show_budget import ShowBudget
from gizmo_friend.brain.shows import ShowStore, StoredShow
from gizmo_friend.brain.transcripts import TranscriptStore
from gizmo_friend.brain.visual_director import (
    DIRECTOR_TIMEOUT_SECONDS,
    DialogueTurn,
    MAX_CONTEXT_TEXT,
    MAX_CONTEXT_TURNS,
    VisualDecision,
    VisualDirector,
    visual_director_from_env,
)
from gizmo_friend.body_protocol import (
    BodyEvent,
    Frame,
    GlassReady,
    MicChunk,
    Navigate,
    Power,
    PushToTalk,
    Select,
    TextLine,
    WorldCamera,
)
from gizmo_friend.prompt import FROZEN_PROMPT
from gizmo_friend.settings import DeviceSettings
from gizmo_friend.states import State, StateMachine
from gizmo_friend.tools.allowlist import ALLOWED_TOOLS
from gizmo_friend.transport.base import Transport, TransportEvent
from gizmo_friend.transport.gemini_live import GeminiLiveTransport

Listener = Callable[[dict[str, Any]], Any]
logger = logging.getLogger(__name__)

EXPRESSIONS = {"idle", "curious", "thinking", "happy", "concerned", "surprised"}
# Placeholder vocabulary for set_expression. Not the character. Glass ignores it.

# Live's reply is held until the committed ask is judged. Speculative work
# during speech is free. The deadline starts when the final transcript is
# known, not when Live first answers — on PTT that reply often precedes the
# transcript. A late or failed director degrades to talk.
TURN_ROUTE_GRACE_SECONDS = DIRECTOR_TIMEOUT_SECONDS
GLASS_NO_ACK_GRACE_SECONDS = 1.0 # a body that never acks gets this long to fetch a cued picture
AUDIO_CHUNK_BYTES = 11_520       # 240 ms of 24 kHz PCM16 per audio event to the body
# Film turns announce the wait, not the story: one short line while the
# thinking animation runs, then Cinema's own narration takes over.
# Keep these dry. Story TTS + "Ooh — let me cook" reads as breathy slow-mo.
FILM_ACK_STYLE = (
    "Read the following as Gizmo, a small dry wizard talking to a kid. "
    "Brisk, even, matter-of-fact, about 170 words per minute. "
    "No whispering, breathy delivery, drawn-out vowels, or dramatic suspense. "
    "Start promptly. Do not add words."
)
FILM_ACK_LINES = (
    "Hang on.",
    "One second.",
    "Give me a second.",
)


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
        image_provider: ImageProvider | None = None,
        show_budget: ShowBudget | None = None,
        show_idle_s: float = 90.0,
        visual_director: VisualDirector | None = None,
        narration_provider: NarrationProvider | None = None,
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
        self.reasoning = reasoning_provider or reasoning_provider_from_env()
        self.visual_director = visual_director or visual_director_from_env()
        self.narration = narration_provider or narration_provider_from_env(gemini_key)
        self.user_id = user_id or os.environ.get("GIZMO_USER_ID", "gizmo-local-user")
        self.images = image_provider or image_provider_from_env()
        self.shows = ShowStore(self.data_dir, device_id=self.user_id)
        # The server/CLI pass a common root budget. Direct session callers can
        # also supply one; otherwise keep a local ledger alongside their data.
        self.show_budget = show_budget or ShowBudget(self.data_dir)
        self.show_idle_s = show_idle_s
        self.current_show: StoredShow | None = None
        self.current_show_subject = ""
        self.current_story_setting = ""
        self.story_character = ""
        self._character_reference: bytes | None = None
        self._show_revision = 0
        self._show_task: asyncio.Task[None] | None = None
        self._show_tasks: set[asyncio.Task[None]] = set()
        self._director_task: asyncio.Task[None] | None = None
        self._director_tasks: set[asyncio.Task[None]] = set()
        self._directed_ask_revision = -1
        self._director_text = ""
        self._director_decision: VisualDecision | None = None
        self._director_committed = False
        self._visual_history: deque[DialogueTurn] = deque(maxlen=MAX_CONTEXT_TURNS)
        self._visual_turn_open = False
        self._visual_utterance = ""
        self._visual_narration = ""
        self._visual_narration_delta = ""
        self._visual_completion = asyncio.Event()
        self._visual_started_at = 0.0
        self._voice_started = False
        self._current_medium = "talk"
        self._suppress_live_output = False
        self._device_line = False
        self._show_idle_task: asyncio.Task[None] | None = None
        self._show_visible_at = 0.0
        self._ask_revision = 0
        self._show_ask_revision = -1
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
        self._ptt_owner: object | None = None
        self._body_input_lock = asyncio.Lock()
        # Mic audio that arrives before the cloud turn is open is buffered and
        # replayed in order. Generous, because a reconnect after a nap must
        # never eat the start of a sentence.
        self._mic_preroll: deque[bytes] = deque()
        self._mic_preroll_bytes = 0
        self._mic_preroll_limit = 480_000  # 10 s of 24 kHz mono PCM16
        self._camera_dirty = False
        self._closing = False
        self.settings = DeviceSettings(self.data_dir / "settings.json")
        # Hold-and-decide: Live's reply waits for the one per-turn judgment.
        self._hold: list[TransportEvent] | None = None
        self._hold_started_at: float | None = None
        self._hold_timer: asyncio.Task[None] | None = None
        self._cue_listeners: set[asyncio.Queue] = set()
        self._last_cue = 0
        self._cinema = None
        self._film_live_fallback: list[TransportEvent] | None = None
        self._film_ack_task: asyncio.Task[None] | None = None
        self._film_ack_index = 0

    @property
    def state(self) -> State:
        return self.machine.state

    def subscribe(self, *, glass_cues: bool = False) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._listeners.append(queue)
        if glass_cues:
            self._cue_listeners.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._cue_listeners.discard(queue)
        if queue in self._listeners:
            self._listeners.remove(queue)

    async def handle_body(self, event: BodyEvent, source: object) -> None:
        """Only the socket that pressed PTT can stream or release that hold."""
        if not isinstance(event, (PushToTalk, MicChunk, Frame)):
            await self.handle(event)
            return
        async with self._body_input_lock:
            if isinstance(event, PushToTalk) and event.active:
                if self._ptt_owner is not None and self._ptt_owner is not source:
                    return
                await self.handle(event)
                if self._ptt_pressed:
                    self._ptt_owner = source
            elif self._ptt_owner is source:
                try:
                    await self.handle(event)
                finally:
                    if not self._ptt_pressed:
                        self._ptt_owner = None

    async def body_disconnected(self, source: object) -> None:
        """Drop abandoned input without committing it or forgetting the session."""
        async with self._body_input_lock:
            if self._ptt_owner is not source:
                return
            self._visual_turn_open = False
            await self._drop_hold(interrupt=False)
            self._reset_ptt()
            self._cancel_warm()
            if self._reconnect_task:
                self._reconnect_task.cancel()
                self._reconnect_task = None
            self.mouth.cancel()
            if self.machine.state is State.TALKING:
                self.machine.apply("select")
            # An unfinished Live activity must not leak into the next hold.
            # Close instead of sending activity_end (which would request a reply).
            # Existing resumption/memory state is retained for the next connection.
            await self._disconnect_transport()
            await self.emit({"type": "ptt", "active": False, "reason": "body_disconnected"})

    def instructions(self) -> str:
        # The date lets him read the memory block's episode dates as "last
        # time" and "a while ago" without a clock tool. Fresh per connect.
        prefix = FROZEN_PROMPT + f"\n\nTODAY\n{_today()}"
        if self._memory_context.strip():
            prefix += (
                "\n\nTHIS KID\n"
                "Who they are, and things from last time. Use a name only when "
                "memory explicitly identifies it as this user's own name. Names "
                "of friends, relatives, pets, and story characters are not the "
                "user's name. If ownership is ambiguous, use no name. "
                "Never mention how you know.\n"
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
            if event.get("type") == "glass" and event.get("hold") and queue not in self._cue_listeners:
                continue
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
        elif isinstance(event, GlassReady):
            self._on_glass_ready(event)
        elif isinstance(event, Frame):
            self.camera.inject(image=event.image, hint=event.hint, mime=event.mime)
            self._camera_dirty = bool(event.image)
            await self.emit({"type": "frame", "hint": event.hint, "bytes": len(event.image or b"")})
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
        if self.settings.select():
            await self.emit(self.settings.snapshot())
            return
        if self.film_active():
            await self._stop_film(reason="select")
            await self._dismiss_show(reason="select", cancel_pending=False)
            return
        if self.current_show is not None:
            await self._dismiss_show(reason="select", cancel_pending=False)
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
            self._visual_history.clear()
            self.story_character = ""
            self._character_reference = None
            self._visual_turn_open = False
            self._current_medium = "talk"
            self.machine.apply("power_on")
            await self.emit({"type": "state", "reason": "switch"})
            self._boot_task = asyncio.create_task(self._boot())
            return
        await self._cut_power()

    async def _cut_power(self) -> None:
        """Hard off. Not sleep. Sleep is idle-only."""
        if self.machine.state is State.POWERED_OFF:
            return
        self._cancel_visual_direction()
        self._visual_turn_open = False
        await self._drop_hold(interrupt=False)
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
        await self._close_settings()
        await self._dismiss_show(reason="power_off")
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
        result = self.settings.navigate(cleaned)
        if result != "ignored":
            if self.settings.open:
                await self._stop_film(reason="settings", announce=False)
            await self.emit(self.settings.snapshot())
            return
        await self.emit({"type": "navigate", "direction": cleaned})

    async def _close_settings(self) -> None:
        if self.settings.close_panel():
            await self.emit(self.settings.snapshot())

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
            self._cancel_visual_direction()
            self._cancel_pending_show()
            await self._stop_film(reason="ptt", announce=False)
            await self._drop_hold(interrupt=False)
            self._suppress_live_output = False
            self._ask_revision += 1
            self._begin_visual_turn("")
            self._begin_hold()
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
        self._camera_dirty = False
        self.camera.inject()
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
        self._ptt_owner = None
        self._camera_dirty = False
        self.camera.inject()
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
        self._cancel_pending_show()
        await self._stop_film(reason="text", announce=False)
        await self._drop_hold(interrupt=False)
        self._ask_revision += 1
        self._suppress_live_output = False
        self._cancel_visual_direction()
        self._begin_visual_turn(cleaned)
        self._begin_hold()
        self._schedule_visual_direction(cleaned, self._ask_revision, commit=True)
        self._record_transcript("user", cleaned)
        await self._ensure_connected()
        if self._transport:
            await self._send_camera_frame()
            await self._transport.send_text(cleaned)
            if self._suppress_live_output:
                await self._transport.interrupt()

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
        self._cancel_visual_direction()
        await self._drop_hold(interrupt=False)
        if self._director_tasks:
            await asyncio.gather(*tuple(self._director_tasks), return_exceptions=True)
        await self._dismiss_show(reason="close")
        if self._show_tasks:
            await asyncio.gather(*tuple(self._show_tasks), return_exceptions=True)
        await self.images.close()
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
        await self.visual_director.close()
        await self.narration.close()
        if self._cinema is not None:
            await self._cinema.close()
            self._cinema = None

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
                    if self.film_active():
                        await asyncio.sleep(1.0)
                        continue
                    await self._sleep(reason="idle")
                    return
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            return

    async def _sleep(self, reason: str) -> None:
        """Only idleness puts him to sleep; there is no sleep button."""
        if not self.machine.can("sleep"):
            return
        self._cancel_visual_direction()
        await self._drop_hold(interrupt=False)
        self._reset_ptt()
        self._flush_transcript_turns()
        self._background_memory(self.memory_provider.flush(self.user_id))
        self.machine.apply("sleep")
        await self._close_settings()
        await self._dismiss_show(reason="sleep")
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

    async def _clear_line(self) -> None:
        if self._device_line:
            self._device_line = False
            await self.emit({"type": "line", "text": ""})

    async def _interrupt(self) -> None:
        await self._clear_line()
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
        if self._hold is not None and kind in {
            "audio", "transcript_delta", "transcript", "function_call", "done", "cancelled",
        }:
            # Live can answer while the director is still judging. Buffer the
            # complete fallback so film failure never costs the kid an answer.
            if kind == "function_call":
                # Non-visual tools still run; a Live-authored show cannot race
                # the turn director's one authoritative medium decision.
                if event.name == "show":
                    result: dict[str, Any] = {"ok": False, "reason": "deciding"}
                else:
                    result = await self._run_tool(event.name, event.arguments)
                if self._transport:
                    await self._transport.submit_tool_output(event.call_id, json.dumps(result))
                return
            self._hold.append(event)
            if self._hold_started_at is None:
                self._hold_started_at = asyncio.get_running_loop().time()
            return
        if self._film_live_fallback is not None and kind in {
            "audio", "transcript_delta", "transcript", "done", "cancelled",
            "function_call",
        }:
            if kind == "function_call":
                # The film owns the turn: a Live-authored show cannot spend a
                # still in its shadow. Other tools still feed the fallback.
                if event.name == "show":
                    result = {"ok": False, "reason": "film owns the turn"}
                else:
                    result = await self._run_tool(event.name, event.arguments)
                if self._transport:
                    await self._transport.submit_tool_output(event.call_id, json.dumps(result))
                return
            self._film_live_fallback.append(event)
            return
        if kind == "audio":
            if self._suppress_live_output:
                return
            if self._visual_turn_open and not self._voice_started:
                self._voice_started = True
                logger.info("Turn latency: stage=voice-first seconds=%.3f", self._visual_elapsed())
            await self._start_talking()
            self._item_id = event.item_id or self._item_id
            self.mouth.speak_pcm(event.pcm)
            await self.emit({"type": "audio", "pcm": base64.b64encode(event.pcm).decode("ascii")})
            return
        if kind == "transcript_delta":
            if self._suppress_live_output:
                return
            await self._clear_line()
            await self._start_talking()
            if self._visual_turn_open:
                self._visual_narration_delta = (
                    self._visual_narration_delta + event.text
                )[:MAX_CONTEXT_TEXT]
            await self.emit({"type": "transcript_delta", "text": event.text})
            return
        if kind == "transcript":
            if self._suppress_live_output:
                return
            await self._start_talking(announce=False)
            self._record_transcript("assistant", event.text)
            if self._visual_turn_open:
                self._visual_narration = (
                    self._visual_narration + " " + event.text
                ).strip()[:MAX_CONTEXT_TEXT]
                self._visual_narration_delta = ""
            await self.emit({"type": "transcript", "role": "gizmo", "text": event.text})
            return
        if kind == "user_transcript_preview":
            partial = event.text.strip()
            if partial:
                text = partial[:MAX_CONTEXT_TEXT]
                self._device_line = True
                await self.emit({"type": "user_partial", "text": text})
                await self.emit({"type": "line", "text": text})
            if self._visual_turn_open:
                self._visual_utterance = partial[:MAX_CONTEXT_TEXT]
                # Preview judgments overlap the tail of speech, but remain
                # speculative: they cannot spend, suppress voice, or touch glass.
                self._schedule_visual_direction(
                    self._visual_utterance, self._ask_revision, commit=False
                )
            return
        if kind == "user_transcript":
            final_text = event.text.strip()[:MAX_CONTEXT_TEXT]
            self._record_transcript("user", final_text)
            self._device_line = True
            await self.emit({"type": "line", "text": final_text})
            if self._visual_turn_open:
                self._visual_utterance = final_text
                self._schedule_visual_direction(
                    final_text, self._ask_revision, commit=True
                )
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
            if kind == "done" and not (self._ptt_pressed or self._ptt_active):
                self._flush_transcript_turns()
                self._finish_visual_turn()
            elif kind == "cancelled" and not (self._ptt_pressed or self._ptt_active):
                self._visual_turn_open = False
                self._cancel_visual_direction()
                self._cancel_pending_show()
            if kind == "done" and event.text:
                await self.emit({"type": "transcript", "role": "gizmo", "text": event.text})
            if (
                self.machine.state is State.TALKING
                and self.machine.can("done")
                and not self.film_active()
            ):
                self.machine.apply("done")
            await self.emit({"type": "state"})
            if not self.film_active():
                self._suppress_live_output = False
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

    def _cancel_visual_direction(self) -> None:
        if self._director_task and not self._director_task.done():
            self._director_task.cancel()
        self._director_task = None

    def _begin_visual_turn(self, utterance: str) -> None:
        self._visual_turn_open = True
        self._visual_utterance = utterance[:MAX_CONTEXT_TEXT]
        self._visual_narration = ""
        self._visual_narration_delta = ""
        self._visual_completion = asyncio.Event()
        self._visual_started_at = asyncio.get_running_loop().time()
        self._voice_started = False
        self._director_text = ""
        self._director_decision = None
        self._director_committed = False

    def _visual_elapsed(self) -> float:
        return asyncio.get_running_loop().time() - self._visual_started_at

    def _finish_visual_turn(self) -> None:
        if not self._visual_turn_open:
            return
        self._visual_turn_open = False
        self._visual_completion.set()
        narration = self._visual_narration
        if self._visual_utterance and narration and not self._suppress_live_output:
            self._visual_history.append(
                DialogueTurn(self._visual_utterance, narration).bounded()
            )

    def _cancel_pending_show(self) -> None:
        """A new turn supersedes a still that has not reached the glass yet."""
        task = self._show_task
        if task is None:
            return
        if not task.done():
            self._show_revision += 1
            task.cancel()
        self._show_task = None

    def _schedule_visual_direction(
        self, utterance: str, ask_revision: int, *, commit: bool,
    ) -> None:
        cleaned = utterance.strip()
        if (
            not cleaned
            or ask_revision == self._directed_ask_revision
            or self._closing
            or not self._ready_for_input()
        ):
            return

        # The final transcript commonly equals the last preview. Reuse that
        # in-flight/result judgment; only a changed transcript starts over.
        if cleaned == self._director_text:
            self._director_committed = self._director_committed or commit
            if self._director_committed and self._director_decision is not None:
                task = asyncio.create_task(
                    self._apply_visual_decision(
                        self._director_decision, cleaned, ask_revision
                    )
                )
                self._director_task = task
                self._director_tasks.add(task)
                task.add_done_callback(self._director_tasks.discard)
                return
            if commit:
                self._arm_committed_route_deadline()
            return

        self._cancel_visual_direction()
        self._director_text = cleaned
        self._director_decision = None
        self._director_committed = commit
        if commit:
            self._arm_committed_route_deadline()
        has_visual = self.current_show is not None
        current_subject = self.current_show_subject if has_visual else ""
        current_story_setting = self.current_story_setting if has_visual else ""
        recent_dialogue = tuple(self._visual_history)
        current_medium = self._current_medium

        async def direct() -> None:
            try:
                started = asyncio.get_running_loop().time()
                decision = await self.visual_director.decide(
                    cleaned,
                    has_visual=has_visual,
                    current_subject=current_subject,
                    narration="",
                    recent_dialogue=recent_dialogue,
                    narration_complete=True,
                    current_story_setting=current_story_setting,
                    current_character=self.story_character,
                    current_medium=current_medium,
                )
                self._director_decision = decision
                logger.info(
                    "Turn latency: stage=director route=%s seconds=%.3f turn_seconds=%.3f",
                    decision.route, asyncio.get_running_loop().time() - started, self._visual_elapsed(),
                )
                if (
                    ask_revision != self._ask_revision
                    or self._closing
                    or not self._ready_for_input()
                    or cleaned != self._director_text
                ):
                    return
                if self._director_committed:
                    await self._apply_visual_decision(decision, cleaned, ask_revision)
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001 - routing degrades to words
                logger.warning("Visual direction failed: error=%s", type(error).__name__)
                if commit and ask_revision == self._ask_revision:
                    await self._apply_visual_decision(
                        VisualDecision(), cleaned, ask_revision
                    )

        task = asyncio.create_task(direct())
        self._director_task = task
        self._director_tasks.add(task)
        task.add_done_callback(self._director_tasks.discard)

    async def _apply_visual_decision(
        self, decision: VisualDecision, utterance: str, ask_revision: int
    ) -> None:
        if (
            ask_revision != self._ask_revision
            or ask_revision == self._directed_ask_revision
            or self._closing
        ):
            return
        self._directed_ask_revision = ask_revision
        self._cancel_hold_timer()

        if decision.story_setting:
            if decision.new_story:
                self.story_character = ""
                self._character_reference = None
            if not self.story_character:
                self.story_character = decision.story_character

        if decision.route == "film":
            result = await self._start_film(utterance, direction=decision.subject)
            if result.get("ok"):
                if decision.story_setting:
                    self.current_story_setting = decision.story_setting
                self._current_medium = "film"
                return
            await self._release_hold()
            return

        if decision.route == "still":
            result = await self._show(
                {
                    "subject": decision.subject,
                    "story_setting": decision.story_setting,
                    "kind": decision.kind,
                    "character": self.story_character if decision.story_setting else "",
                }
            )
            if result.get("ok"):
                self._current_medium = "still"
            await self._release_hold()
            return

        if decision.thread != "detour":
            self._current_medium = "talk"
        await self._release_hold()

    async def _start_talking(self, announce: bool = True) -> None:
        if self.machine.can("speech_out"):
            self.machine.apply("speech_out")
            self.mouth.mark_playing()
            if announce:
                await self.emit({"type": "state"})

    def film_active(self) -> bool:
        return bool(self._cinema and self._cinema.active)

    def _cinema_capability(self):
        if self._cinema is None:
            from gizmo_friend.cinema.capability import FriendCinema
            from gizmo_friend.cinema.routes import FilmBudget

            self._cinema = FriendCinema(
                directory=self.show_budget.root / "cinema" / self.user_id,
                device_id=self.user_id,
                store=self.shows,
                emit=self.emit,
                budget=FilmBudget(self.show_budget.root),
                next_cue=self._issue_cue,
                on_segment=self._on_film_segment,
                on_talking=self._start_talking,
                on_preparing=self._on_film_preparing,
                on_presenting=self._on_film_presenting,
                on_idle=self._on_film_idle,
                on_failed=self._on_film_failed,
            )
        return self._cinema

    async def _start_film(self, text: str, *, direction: str = "") -> dict[str, Any]:
        if self._cinema is None and not self._cue_listeners:
            logger.info("Friend cinema skipped: no held-cue body")
            return {"ok": False, "reason": "no glass cues"}
        cinema = self._cinema_capability()
        # On the body the film is the whole answer, so it always gets the
        # directed arc; the ask itself is the brief unless a caller has better.
        result = await cinema.start(text, direction=direction or text)
        if not result.get("ok"):
            logger.info("Friend cinema skipped: %s", result.get("reason"))
            return result
        # Preserve everything Live already generated while the judgment was
        # pending. It stays muted unless Cinema fails before presentation.
        self._film_live_fallback = list(self._hold or ())
        self._hold = None
        self._hold_started_at = None
        self._cancel_hold_timer()
        self._suppress_live_output = True
        await self._clear_line()
        self.mouth.cancel()
        await self.emit({"type": "interrupted", "reason": "film"})
        logger.info("Friend cinema started device=%s", self.user_id)
        return result

    async def _stop_film(self, *, reason: str = "interrupt", announce: bool = True) -> bool:
        cinema = self._cinema
        self._cancel_film_ack()
        had_fallback = self._film_live_fallback is not None
        self._film_live_fallback = None
        if cinema is None or not cinema.active:
            if had_fallback:
                self._suppress_live_output = False
            return False
        await cinema.stop()
        if not cinema.active:
            # Cinema's interrupt() emits nothing; without this the next answer
            # would stay voice-muted on the body.
            self._suppress_live_output = False
        if not self.machine.powered():
            return True
        transitioned = False
        if self.machine.state in {State.TALKING, State.THINKING} and self.machine.can("select"):
            self.machine.apply("select")
            transitioned = True
        if announce:
            await self.emit({"type": "interrupted", "reason": reason})
        elif transitioned:
            await self.emit({"type": "state"})
        return True

    async def _on_film_preparing(self) -> None:
        # A film in flight owns the glass once segments land; until then the
        # body plays its built-in working animation on home, not a still card.
        self._cancel_film_ack()
        self._film_ack_task = asyncio.create_task(self._announce_film())
        self._cancel_pending_show()
        was_visible = self.current_show is not None
        self.current_show = None
        self.current_show_subject = ""
        self._device_line = False
        if was_visible and self._transport is not None:
            clear_pending_image = getattr(self._transport, "clear_pending_image", None)
            if clear_pending_image:
                await clear_pending_image()
        if self.machine.state is not State.THINKING and self.machine.can("think"):
            self.machine.apply("think")
        await self.emit(
            {"type": "glass", "viewing": False, "reason": "film", "text": ""}
        )
        await self.emit({"type": "state"})

    async def _on_film_segment(self, segment) -> None:
        self.current_show = segment.show
        title = ""
        if self._cinema and self._cinema.session and self._cinema.session.prepared:
            title = self._cinema.session.prepared.plan.title
        self.current_show_subject = title
        self._show_visible_at = asyncio.get_running_loop().time()

    async def _on_film_presenting(self) -> None:
        self._cancel_film_ack()
        self._film_live_fallback = None
        if self._transport:
            try:
                await self._transport.interrupt()
            except Exception as error:
                logger.warning("Live film handoff failed: error=%s", type(error).__name__)

    async def _on_film_failed(self) -> None:
        if self.machine.state in {State.TALKING, State.THINKING} and self.machine.can("select"):
            self.machine.apply("select")
        logger.warning("Film generation or playback failed; replaying held voice answer")

    def _cancel_film_ack(self) -> None:
        if self._film_ack_task and not self._film_ack_task.done():
            self._film_ack_task.cancel()
        self._film_ack_task = None

    async def _announce_film(self) -> None:
        """One spoken line that narrates the wait, never the story itself."""
        line = FILM_ACK_LINES[self._film_ack_index % len(FILM_ACK_LINES)]
        self._film_ack_index += 1
        try:
            voice = await self.narration.narrate(line, style=FILM_ACK_STYLE)
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - a silent wait beats a crash
            logger.debug("Film acknowledgement failed: error=%s", type(error).__name__)
            return
        if voice is None:
            return
        self.mouth.mark_playing()
        try:
            for offset in range(0, len(voice.pcm), AUDIO_CHUNK_BYTES):
                # The film ended or a new turn started: the line dies with it.
                if not self.film_active() or self._closing:
                    return
                chunk = voice.pcm[offset : offset + AUDIO_CHUNK_BYTES]
                self.mouth.speak_pcm(chunk)
                await self.emit({"type": "audio", "pcm": base64.b64encode(chunk).decode("ascii")})
        finally:
            self.mouth.mark_idle()

    async def _on_film_idle(self) -> None:
        fallback = self._film_live_fallback
        self._film_live_fallback = None
        if self.machine.state in {State.TALKING, State.THINKING} and self.machine.can("done"):
            self.machine.apply("done")
        self._device_line = False
        await self.emit({"type": "glass", "viewing": False, "reason": "film", "text": ""})
        await self.emit({"type": "state", "reason": "film"})
        if fallback:
            # A film that never presented hands the turn back to Live's held
            # answer. The playback task can still be unwinding here, so
            # film_active() is not a safe suppression check — clear it.
            self._suppress_live_output = False
            for event in fallback:
                await self._on_transport(event)
        elif not self.film_active():
            self._suppress_live_output = False

    async def _dismiss_show(self, reason: str, *, cancel_pending: bool = True) -> None:
        # Invalidate before any await: a late image cannot overtake a local
        # dismissal, sleep, power-off, or subsequent show.
        await self._stop_film(reason=reason, announce=False)
        if cancel_pending:
            self._show_revision += 1
            if self._show_task and not self._show_task.done():
                self._show_task.cancel()
            self._show_task = None
        if self._show_idle_task and self._show_idle_task is not asyncio.current_task():
            self._show_idle_task.cancel()
        self._show_idle_task = None
        was_visible = self.current_show is not None
        self.current_show = None
        self.current_show_subject = ""
        self.current_story_setting = ""
        if was_visible:
            clear_pending_image = getattr(self._transport, "clear_pending_image", None)
            if clear_pending_image:
                await clear_pending_image()
            self._device_line = False
            await self.emit(
                {"type": "glass", "viewing": False, "reason": reason, "text": ""}
            )

    def show_event(self) -> dict[str, Any] | None:
        if self.current_show is None:
            return None
        return {
            "type": "glass",
            "still": self.current_show.still_url,
            "subject": self.current_show_subject,
            "viewing": True,
        }

    async def _watch_show_idle(self) -> None:
        try:
            loop = asyncio.get_running_loop()
            while self.current_show is not None:
                idle = loop.time() - max(self._last_activity, self._show_visible_at)
                remaining = self.show_idle_s - idle
                if remaining > 0:
                    await asyncio.sleep(min(remaining, 1.0))
                    continue
                if self.machine.state is State.LISTENING and not self._ptt_pressed:
                    # A show nobody pulled forward for this long is over.
                    await self._dismiss_show(reason="idle", cancel_pending=False)
                    return
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            return

    async def _conjure_show(
        self, subject: str, revision: int, session_id: str,
        story_setting: str = "", kind: str = "scene",
        character: str = "", reference: bytes | None = None,
    ) -> None:
        def current() -> bool:
            return (
                revision == self._show_revision
                and not self._closing
                and self._ready_for_input()
                and session_id == self.session_id
            )

        try:
            options = {"kind": kind}
            if character:
                options.update(character=character, reference=reference)
            still = await self.images.conjure(subject, **options)
            if still is None or not current():
                return
            stored = await asyncio.to_thread(self.shows.save, still, session_id=session_id)
            if not current():
                return
            # Commit pending -> installed without an await in the middle. Once
            # this task stops being pending, a later turn keeps the Show.
            if self._show_task is asyncio.current_task():
                self._show_task = None
            self.current_show = stored
            self.current_show_subject = subject
            self.current_story_setting = story_setting
            if character and character == self.story_character and self._character_reference is None:
                self._character_reference = still.jpeg
            self._show_visible_at = asyncio.get_running_loop().time()
            await self.emit(self.show_event())
            logger.info("Turn latency: stage=still-glass show=%s seconds=%.3f", stored.id, self._visual_elapsed())
            if self._transport:
                await self._transport.send_image(
                    f"data:image/jpeg;base64,{base64.b64encode(still.jpeg).decode('ascii')}"
                )
            if self.show_idle_s > 0 and (self._show_idle_task is None or self._show_idle_task.done()):
                self._show_idle_task = asyncio.create_task(self._watch_show_idle())
        except asyncio.CancelledError:
            raise
        except Exception as error:
            # Additive: failures are operator diagnostics, never a kid-facing
            # error or another model turn about the missing picture.
            logger.warning("Show failed: error=%s", type(error).__name__)
        finally:
            if self._show_task is asyncio.current_task():
                self._show_task = None

    async def _show(self, arguments: dict[str, Any]) -> dict[str, Any]:
        subject = arguments.get("subject")
        if not isinstance(subject, str) or not subject.strip():
            return {"ok": False, "reason": "subject is required"}
        subject = subject.strip()
        if arguments.get("motion"):
            logger.info("show motion ignored; Friend has no short clip")
        if not self._ready_for_input() or self._closing:
            return {"ok": False, "reason": "asleep"}
        if isinstance(self.images, NullImageProvider):
            return {"ok": False, "reason": "unavailable"}
        ask_revision = self._ask_revision
        if ask_revision == self._show_ask_revision:
            return {"ok": False, "reason": "one per ask"}
        self._show_ask_revision = ask_revision
        self._show_revision += 1
        revision = self._show_revision
        session_id = self.session_id
        if self._show_task and not self._show_task.done():
            self._show_task.cancel()
        try:
            reserved = await asyncio.to_thread(self.show_budget.reserve, self.user_id)
        except Exception as error:
            logger.warning("Show budget unavailable: error=%s", type(error).__name__)
            return {"ok": False, "reason": "unavailable"}
        if not reserved:
            return {"ok": False, "reason": "quiet day"}
        if revision != self._show_revision or not self._ready_for_input() or self._closing:
            return {"ok": False, "reason": "cancelled"}
        story_setting = arguments.get("story_setting", "")
        story_setting = story_setting[:100] if isinstance(story_setting, str) else ""
        kind = arguments.get("kind", "scene")
        kind = kind if kind in {"scene", "diagram"} else "scene"
        if story_setting:
            kind = "scene"
        character = arguments.get("character", "") if story_setting else ""
        character = character[:600] if isinstance(character, str) else ""
        reference = self._character_reference if character and character == self.story_character else None
        task = asyncio.create_task(
            self._conjure_show(subject, revision, session_id, story_setting, kind, character, reference)
        )
        self._show_task = task
        self._show_tasks.add(task)
        task.add_done_callback(self._show_tasks.discard)
        result = {"ok": True, "status": "conjuring", "subject": subject}
        await self.emit({"type": "tool", "name": "show", "result": result})
        return result

    # ----- one per-turn hold-and-decide -------------------------------------------------

    def _begin_hold(self) -> None:
        """Buffer Live's reply until the final-transcript judgment commits."""
        if self._hold is not None:
            return
        self._hold = []
        self._hold_started_at = None
        self._cancel_hold_timer()

    def _hold_has_audio(self) -> bool:
        return self._hold is not None and any(event.kind == "audio" for event in self._hold)

    def _arm_committed_route_deadline(self) -> None:
        """Fail open only after a committed ask has had the director's timeout."""
        if self._hold is None:
            return
        self._arm_hold_timer()

    def _arm_hold_timer(self) -> None:
        self._cancel_hold_timer()
        ask_revision = self._ask_revision

        async def expire() -> None:
            try:
                await asyncio.sleep(TURN_ROUTE_GRACE_SECONDS)
            except asyncio.CancelledError:
                return
            if self._hold is None or ask_revision != self._ask_revision:
                return
            # Production chose film in ~0.9s and then talked anyway: expire
            # marked the ask directed in the gap between decide() returning
            # and _apply_visual_decision() running, so Cinema never started.
            if self._director_decision is not None:
                return
            logger.warning("Turn director late; failing open to talk")
            self._directed_ask_revision = ask_revision
            self._cancel_visual_direction()
            await self._release_hold()

        self._hold_timer = asyncio.create_task(expire())

    def _cancel_hold_timer(self) -> None:
        if self._hold_timer and self._hold_timer is not asyncio.current_task() and not self._hold_timer.done():
            self._hold_timer.cancel()
        self._hold_timer = None

    async def _release_hold(self) -> None:
        """Play Live's complete answer in order, as if it was never held."""
        ask_revision = self._ask_revision
        events = self._hold
        self._hold = None
        self._hold_started_at = None
        self._cancel_hold_timer()
        if not events:
            return
        for event in events:
            if self._hold is not None or ask_revision != self._ask_revision:
                # A new ask began while replaying; the rest belongs to the old turn.
                return
            await self._on_transport(event)

    async def _drop_hold(self, *, interrupt: bool = True) -> None:
        """A story move: Live's improvised answer is never heard. The conductor speaks instead."""
        had_hold = self._hold is not None
        self._hold = None
        self._hold_started_at = None
        self._cancel_hold_timer()
        if not had_hold or not interrupt:
            return
        self._suppress_live_output = True
        self._visual_turn_open = False
        self._cancel_visual_direction()
        if self._transport:
            try:
                await self._transport.interrupt()
            except Exception as error:  # noqa: BLE001 - the adapter already mutes locally
                logger.warning("Live interrupt failed: error=%s", type(error).__name__)

    # ----- film cues ------------------------------------------------------------------

    def _issue_cue(self) -> int:
        self._last_cue += 1
        return self._last_cue

    def _on_glass_ready(self, event: GlassReady) -> None:
        if self._cinema is not None:
            self._cinema.on_glass_ready(event.cue, event.kind, event.ok)

    async def _run_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name not in ALLOWED_TOOLS:
            return {"ok": False, "reason": f"unknown tool {name}"}
        if name == "show":
            return await self._show(arguments)
        if name == "deep_think":
            question = str(arguments.get("question") or "").strip()
            if not question:
                return {"ok": False, "reason": "question is required"}
            # While a film owns the turn its thinking state is the glass's own;
            # the tool still answers for the held voice, it just cannot move it.
            film_owns = self._film_live_fallback is not None or self.film_active()
            if not film_owns and self.machine.can("think"):
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
            if not film_owns and self.machine.state is State.THINKING:
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
