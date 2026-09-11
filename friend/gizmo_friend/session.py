from __future__ import annotations

import asyncio
import base64
import json
import inspect
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
from gizmo_friend.brain.story import NullStoryPlanner, StoryContext, StoryIntent, StoryPlanner, story_gate, story_planner_from_env
from gizmo_friend.brain.transcripts import TranscriptStore
from gizmo_friend.brain.visual_director import (
    DialogueTurn,
    MAX_CONTEXT_TEXT,
    MAX_CONTEXT_TURNS,
    VisualDirector,
    is_explicit_visual_request,
    is_moving_explanation_ask,
    opening_narration,
    prefer_film_route,
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
from gizmo_friend.story_run import StoryRun
from gizmo_friend.tools.allowlist import ALLOWED_TOOLS
from gizmo_friend.transport.base import Transport, TransportEvent
from gizmo_friend.transport.gemini_live import GeminiLiveTransport

Listener = Callable[[dict[str, Any]], Any]
logger = logging.getLogger(__name__)

EXPRESSIONS = {"idle", "curious", "thinking", "happy", "concerned", "surprised"}
# Placeholder vocabulary for set_expression. Not the character. Glass ignores it.

# Storytelling. Live's answer is held (not played) while the scout decides
# whether the kid asked for a told piece. The hold is short and fails open.
HOLD_PROVISIONAL_SECONDS = 0.7   # no story running: wait this long past first audio for a transcript
HOLD_STORY_SECONDS = 5.0         # a story is running, or the ask matched the gate: wait for the scout
STORY_CHUNK_BYTES = 11_520       # 240 ms of 24 kHz PCM16 per audio event to the body
STORY_AUDIO_LEAD_SECONDS = 1.5   # how far ahead of real time narration is sent; small so a press stops it fast
GLASS_NO_ACK_GRACE_SECONDS = 1.0 # a body that never acks gets this long to fetch a cued picture
STORY_RESUME_DELAY_SECONDS = 0.8 # breath between his answer to a side question and the story going on
STORY_FALLBACK_NUDGE = (
    "(The pictures could not be made for this part. Carry on in words, briefly, in your own voice, "
    "without mentioning pictures or that anything failed.)"
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
        story_planner: StoryPlanner | None = None,
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
        self._story_enabled = story_planner is not None or os.environ.get("GIZMO_STORY_ENABLED", "").lower() in {"1", "true"}
        self.story_planner = story_planner or (story_planner_from_env() if self._story_enabled else NullStoryPlanner())
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
        self._visual_history: deque[DialogueTurn] = deque(maxlen=MAX_CONTEXT_TURNS)
        self._visual_turn_open = False
        self._visual_utterance = ""
        self._visual_narration = ""
        self._visual_narration_delta = ""
        self._visual_completion = asyncio.Event()
        self._visual_started_at = 0.0
        self._voice_started = False
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
        # Storytelling: one told piece at a time, played by the conductor.
        self.story: StoryRun | None = None
        self._story_task: asyncio.Task[bool] | None = None
        self._story_resume_after_done = False
        # Hold-and-decide: Live's reply is buffered here until the scout speaks.
        self._hold: list[TransportEvent] | None = None
        self._hold_started_at: float | None = None
        self._hold_timer: asyncio.Task[None] | None = None
        self._hold_utterance = ""
        self._scout_task: asyncio.Task[None] | None = None
        self._scouted_ask_revision = -1
        # Body acknowledgements for cued pictures, keyed by (cue, kind).
        self._glass_ready: dict[tuple[int, str], asyncio.Future[bool]] = {}
        self._cue_listeners: set[asyncio.Queue] = set()
        self._last_story_cue = 0
        self._glass_ready_timeout = 6.0
        self._story_audio_lead = STORY_AUDIO_LEAD_SECONDS
        self._cinema = None
        self._prefers_device_film = os.environ.get("GIZMO_DIRECTOR_DEVICE", "") == self.user_id

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
        if not self._listeners:
            await self._pause_story(reason="body_disconnected")
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
        if self.story is not None:
            # Select keeps its existing physical contract: dismiss the Show.
            # PTT pauses a story; spoken requests resume or steer it.
            await self._end_story()
            await self._drop_hold()
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
        await self._end_story()
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
            if self.story is not None:
                await self._pause_story(reason="ptt")
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
        if self.story is not None:
            await self._pause_story(reason="text")
        self._ask_revision += 1
        self._suppress_live_output = False
        self._cancel_visual_direction()
        self._begin_visual_turn(cleaned)
        self._record_transcript("user", cleaned)
        # A typed line is known in full at once: the scout can start before Live answers.
        if self.story is not None or story_gate(cleaned):
            self._begin_hold()
            await self._consider_scout(cleaned, final=True)
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
        await self._end_story()
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
        await self.story_planner.close()
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
        await self._end_story()
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
            # Live has started answering while the scout is still deciding whether
            # this is a story ask. Keep the reply, do not play it yet.
            if kind == "function_call":
                # Tools still answer during the hold; only the glass tools wait for the ruling.
                if event.name == "show":
                    result: dict[str, Any] = {"ok": False, "reason": "deciding"}
                else:
                    result = await self._run_tool(event.name, event.arguments)
                if self._transport:
                    await self._transport.submit_tool_output(event.call_id, json.dumps(result))
                return
            self._hold.append(event)
            if kind == "audio" and self._hold_started_at is None:
                self._hold_started_at = asyncio.get_running_loop().time()
                self._arm_hold_timer()
            if kind == "audio" and self._hold_utterance:
                # The voice model has begun, so its transcript of the kid is settled.
                await self._consider_scout(self._hold_utterance, final=False, voice_started=True)
            return
        if kind == "audio":
            if self._suppress_live_output:
                return
            if self._visual_turn_open and not self._voice_started:
                self._voice_started = True
                logger.info("Turn latency: stage=voice-first seconds=%.3f", self._visual_elapsed())
                if self._can_direct_before_voice(self._visual_utterance):
                    self._schedule_visual_direction(self._visual_utterance, self._ask_revision)
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
                self._direct_opening_narration()
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
                self._direct_opening_narration()
            await self.emit({"type": "transcript", "role": "gizmo", "text": event.text})
            return
        if kind == "user_transcript_preview":
            partial = event.text.strip()
            if partial:
                text = partial[:MAX_CONTEXT_TEXT]
                self._device_line = True
                await self.emit({"type": "user_partial", "text": text})
                await self.emit({"type": "line", "text": text})
            if self._hold is not None:
                self._hold_utterance = event.text.strip()[:MAX_CONTEXT_TEXT]
                await self._consider_scout(self._hold_utterance, final=False, voice_started=self._hold_has_audio())
            if self._visual_turn_open:
                self._visual_utterance = event.text.strip()[:MAX_CONTEXT_TEXT]
                # Wait until the model begins answering, so a partial transcript
                # during the microphone hold cannot spend the visual budget.
                if self._voice_started:
                    if self._can_direct_before_voice(self._visual_utterance):
                        self._schedule_visual_direction(self._visual_utterance, self._ask_revision)
                    else:
                        self._direct_opening_narration()
            return
        if kind == "user_transcript":
            self._record_transcript("user", event.text)
            self._device_line = True
            await self.emit(
                {"type": "line", "text": event.text.strip()[:MAX_CONTEXT_TEXT]}
            )
            if self._hold is not None:
                self._hold_utterance = event.text.strip()[:MAX_CONTEXT_TEXT]
                await self._consider_scout(self._hold_utterance, final=True)
            if self._visual_turn_open:
                self._visual_utterance = event.text.strip()[:MAX_CONTEXT_TEXT]
            if self._visual_turn_open and self._can_direct_before_voice(event.text):
                self._schedule_visual_direction(event.text, self._ask_revision)
            elif self._visual_turn_open:
                # Live may finalize microphone transcription after the opening
                # sentence has already streamed. Use both when they are available.
                self._direct_opening_narration()
            await self.emit({"type": "transcript", "role": "user", "text": event.text})
            return
        if kind == "function_call":
            result = await self._run_tool(event.name, event.arguments)
            if self._transport:
                await self._transport.submit_tool_output(event.call_id, json.dumps(result))
            return
        if kind == "speech_started":
            if self.machine.state is State.TALKING and not self._story_speaking():
                await self._interrupt()
                self.machine.apply("select")
                await self.emit({"type": "interrupted"})
            return
        if kind in {"done", "cancelled"}:
            if not self._story_speaking():
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
                and not self._story_speaking()
                and not self.film_active()
            ):
                self.machine.apply("done")
            await self.emit({"type": "state"})
            if not self.film_active():
                self._suppress_live_output = False
            if kind == "done" and self._story_resume_after_done and self.story is not None:
                # He answered the side question; the story picks up where it stopped.
                self._story_resume_after_done = False
                self._continue_story(delay=STORY_RESUME_DELAY_SECONDS)
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
        if self._can_direct_before_voice(utterance):
            self._schedule_visual_direction(utterance, self._ask_revision)

    def _can_direct_before_voice(self, utterance: str) -> bool:
        cleaned = utterance.strip()
        if not cleaned:
            return False
        if self._prefers_device_film:
            return True
        return (
            not self.story_character and not self.current_story_setting
            and (is_explicit_visual_request(cleaned) or is_moving_explanation_ask(cleaned))
        )

    def _visual_elapsed(self) -> float:
        return asyncio.get_running_loop().time() - self._visual_started_at

    def _direct_opening_narration(self) -> None:
        if not self._visual_utterance or self._suppress_live_output:
            return
        opening = opening_narration(
            (self._visual_narration + " " + self._visual_narration_delta).strip()
        )
        if opening:
            self._schedule_visual_direction(
                self._visual_utterance, self._ask_revision, narration=opening
            )

    def _finish_visual_turn(self) -> None:
        if not self._visual_turn_open:
            return
        self._visual_turn_open = False
        self._visual_completion.set()
        if not self._visual_utterance:
            return
        narration = self._visual_narration
        # Short replies without an opening-sentence boundary direct here.
        # Missing narration must not conjure an invented chapter.
        if narration and not self._suppress_live_output:
            self._schedule_visual_direction(
                self._visual_utterance, self._ask_revision, narration=narration,
                narration_complete=True,
            )
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
        self, utterance: str, ask_revision: int, *, narration: str = "",
        narration_complete: bool = False,
    ) -> None:
        cleaned = utterance.strip()
        if (
            not cleaned
            or ask_revision == self._directed_ask_revision
            or self._closing
            or not self._ready_for_input()
            or self.story is not None
            or self._hold is not None
        ):
            # A told piece owns the glass; conversation pictures wait until it ends.
            return
        self._directed_ask_revision = ask_revision
        self._cancel_visual_direction()
        has_visual = self.current_show is not None
        current_subject = self.current_show_subject if has_visual else ""
        current_story_setting = self.current_story_setting if has_visual else ""
        recent_dialogue = tuple(self._visual_history)
        completion = self._visual_completion

        async def direct() -> None:
            try:
                if self._prefers_device_film:
                    await self._start_film(cleaned)
                    return
                started = asyncio.get_running_loop().time()
                decision = await self.visual_director.decide(
                    cleaned,
                    has_visual=has_visual,
                    current_subject=current_subject,
                    narration=narration,
                    recent_dialogue=recent_dialogue,
                    narration_complete=narration_complete,
                    current_story_setting=current_story_setting,
                    current_character=self.story_character,
                )
                logger.info(
                    "Turn latency: stage=director route=%s seconds=%.3f turn_seconds=%.3f",
                    decision.route, asyncio.get_running_loop().time() - started, self._visual_elapsed(),
                )
                if decision.follow_narration and not narration_complete:
                    # A provisional words-only story decision may inspect the
                    # finished chapter once. No media has been requested yet.
                    async with asyncio.timeout(35):
                        await completion.wait()
                    if ask_revision != self._ask_revision or not self._visual_narration:
                        return
                    decision = await self.visual_director.decide(
                        cleaned,
                        has_visual=self.current_show is not None,
                        current_subject=self.current_show_subject if self.current_show else "",
                        narration=self._visual_narration,
                        recent_dialogue=recent_dialogue,
                        narration_complete=True,
                        current_story_setting=self.current_story_setting if self.current_show else "",
                        current_character=self.story_character,
                    )
                if (
                    ask_revision != self._ask_revision
                    or self._closing
                    or not self._ready_for_input()
                ):
                    return
                if decision.story_setting:
                    if decision.new_story:
                        self.story_character = ""
                        self._character_reference = None
                    if not self.story_character:
                        self.story_character = decision.story_character
                decision = prefer_film_route(decision, cleaned)
                if decision.route in {"film", "motion"}:
                    if decision.story_setting:
                        self.current_story_setting = decision.story_setting
                    utterance = cleaned
                    if decision.story_setting:
                        chapter = (self._visual_narration or narration or "").strip()
                        if chapter:
                            utterance = chapter
                    await self._start_film(utterance)
                elif decision.route == "still":
                    arguments: dict[str, Any] = {"subject": decision.subject}
                    arguments["story_setting"] = decision.story_setting
                    arguments["kind"] = decision.kind
                    arguments["character"] = self.story_character if decision.story_setting else ""
                    await self._show(arguments)
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001 - routing degrades to words
                logger.warning("Visual direction failed: error=%s", type(error).__name__)

        task = asyncio.create_task(direct())
        self._director_task = task
        self._director_tasks.add(task)
        task.add_done_callback(self._director_tasks.discard)

    async def _start_talking(self, announce: bool = True) -> None:
        if self.machine.state is State.LISTENING and self.machine.can("speech_out"):
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
                next_cue=self._issue_story_cue,
                on_segment=self._on_film_segment,
                on_talking=self._start_talking,
                on_idle=self._on_film_idle,
                on_failed=self._on_film_failed,
            )
        return self._cinema

    async def _start_film(self, text: str) -> dict[str, Any]:
        if self._cinema is None and not self._cue_listeners:
            logger.info("Friend cinema skipped: no held-cue body")
            return {"ok": False, "reason": "no glass cues"}
        cinema = self._cinema_capability()
        result = await cinema.start(text)
        if not result.get("ok"):
            logger.info("Friend cinema skipped: %s", result.get("reason"))
            return result
        self._suppress_live_output = True
        await self._interrupt()
        logger.info("Friend cinema started device=%s", self.user_id)
        return result

    async def _stop_film(self, *, reason: str = "interrupt", announce: bool = True) -> bool:
        cinema = self._cinema
        if cinema is None or not cinema.active:
            return False
        await cinema.stop()
        if announce and self.machine.powered():
            if self.machine.state is State.TALKING and self.machine.can("select"):
                self.machine.apply("select")
            await self.emit({"type": "interrupted", "reason": reason})
        return True

    async def _on_film_segment(self, segment) -> None:
        self.current_show = segment.show
        title = ""
        if self._cinema and self._cinema.session and self._cinema.session.prepared:
            title = self._cinema.session.prepared.plan.title
        self.current_show_subject = title
        self._show_visible_at = asyncio.get_running_loop().time()

    async def _on_film_failed(self) -> None:
        if self.machine.state is State.TALKING and self.machine.can("select"):
            self.machine.apply("select")
        await self.emit({"type": "interrupted"})
        await self.emit(
            {
                "type": "error",
                "message": "Film playback stopped; the last picture is retained.",
            }
        )

    async def _on_film_idle(self) -> None:
        if self.machine.state is State.TALKING and self.machine.can("done"):
            self.machine.apply("done")
        if not self.film_active():
            self._suppress_live_output = False
        self._device_line = False
        await self.emit({"type": "glass", "viewing": False, "reason": "film", "text": ""})
        await self.emit({"type": "state", "reason": "film"})

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
                    # A story nobody pulled forward for this long is over.
                    await self._end_story()
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
        if self.story is not None:
            return {"ok": False, "reason": "story running"}
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

    # ----- storytelling: hold-and-decide ------------------------------------------------

    def _begin_hold(self) -> None:
        """Buffer Live's reply to this ask until the scout has ruled on it."""
        if not self._story_enabled or self._hold is not None:
            return
        self._hold = []
        self._hold_started_at = None
        self._hold_utterance = ""
        self._cancel_hold_timer()

    def _hold_has_audio(self) -> bool:
        return self._hold is not None and any(event.kind == "audio" for event in self._hold)

    def _arm_hold_timer(self) -> None:
        self._cancel_hold_timer()
        seconds = HOLD_STORY_SECONDS if (self.story is not None or self._scout_task) else HOLD_PROVISIONAL_SECONDS
        ask_revision = self._ask_revision

        async def expire() -> None:
            try:
                await asyncio.sleep(seconds)
            except asyncio.CancelledError:
                return
            if self._hold is None or ask_revision != self._ask_revision:
                return
            if self.story is None and not self._scout_task:
                # No transcript arrived in time to gate on: let him answer.
                await self._release_hold()
                return
            logger.warning("Story scout late; releasing Live's answer")
            self._cancel_scout()
            await self._release_hold()

        self._hold_timer = asyncio.create_task(expire())

    def _cancel_hold_timer(self) -> None:
        if self._hold_timer and self._hold_timer is not asyncio.current_task() and not self._hold_timer.done():
            self._hold_timer.cancel()
        self._hold_timer = None

    def _cancel_scout(self) -> None:
        if self._scout_task and not self._scout_task.done():
            self._scout_task.cancel()
        self._scout_task = None

    async def _release_hold(self) -> None:
        """Not a story move: play what Live said, in order, as if never held."""
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
        self._hold_utterance = ""
        self._cancel_hold_timer()
        self._cancel_scout()
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

    async def _consider_scout(self, utterance: str, *, final: bool, voice_started: bool = False) -> None:
        """Start the scout once per ask, as soon as the kid's words are settled enough."""
        if self._hold is None or self._scouted_ask_revision == self._ask_revision or self._closing:
            return
        cleaned = utterance.strip()
        if not cleaned:
            return
        if self.story is None and not story_gate(cleaned):
            # Ordinary conversation: no scout, no added latency.
            if final or voice_started:
                self._scouted_ask_revision = self._ask_revision
                await self._release_hold()
            return
        if not final and not voice_started:
            # A partial transcript of a story ask: keep holding; the words are still arriving.
            return
        self._scouted_ask_revision = self._ask_revision
        ask_revision = self._ask_revision
        context = self.story.context if self.story is not None else StoryContext()

        async def scout() -> None:
            try:
                started = asyncio.get_running_loop().time()
                intent = await self.story_planner.scout(cleaned, context)
                logger.info(
                    "Story scout: route=%s seconds=%.3f", intent.route,
                    asyncio.get_running_loop().time() - started,
                )
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001 - a broken scout means an ordinary answer
                logger.warning("Story scout failed: error=%s", type(error).__name__)
                intent = StoryIntent()
            if ask_revision != self._ask_revision or self._closing:
                return
            self._scout_task = None
            await self._apply_intent(intent, cleaned)

        self._scout_task = asyncio.create_task(scout())
        if self._hold_started_at is not None:
            # Audio is already waiting; give the scout its full window, not the provisional one.
            self._arm_hold_timer()

    async def _apply_intent(self, intent: StoryIntent, utterance: str) -> None:
        route = intent.route
        story = self.story
        if route == "begin":
            await self._drop_hold()
            await self._end_story()
            self._cancel_pending_show()
            # A new story/explanation prefers Cinema like the Oddity glass;
            # StoryRun remains the fallback when a film cannot start.
            if self.film_active():
                return
            if (await self._start_film(intent.premise or utterance)).get("ok"):
                self._directed_ask_revision = self._ask_revision
                return
            self._start_story(intent.premise, intent.opener)
            return
        if story is None:
            await self._release_hold()
            return
        if route == "continue":
            if story.finished:
                # Nothing left to tell. He answers this in his own voice, knowing the story.
                await self._end_story()
                await self._release_hold()
                return
            await self._drop_hold()
            self._continue_story()
            return
        if route == "steer":
            await self._drop_hold()
            edit = intent.edit or utterance
            self._run_story(story.steer(edit, intent.opener), what="steer")
            return
        if route == "leave":
            await self._end_story()
            await self._release_hold()
            return
        # "question" or "none" while a story runs: he answers, then the story goes on.
        self._story_resume_after_done = True
        await self._release_hold()

    # ----- storytelling: lifecycle -------------------------------------------------------

    def _start_story(self, premise: str, opener: str) -> None:
        self.story = StoryRun(
            stage=self, planner=self.story_planner, narration=self.narration, images=self.images,
            shows=self.shows, show_budget=self.show_budget,
            user_id=self.user_id, session_id=self.session_id,
            premise=premise, next_cue=self._issue_story_cue,
        )
        self._run_story(self.story.begin(opener), what="begin")

    def _run_story(self, call: Any, *, what: str) -> None:
        if self._story_task and not self._story_task.done():
            self._story_task.cancel()
        story = self.story

        async def run() -> None:
            try:
                ok = await call
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001 - the story fails soft into words
                logger.warning("Story %s failed: error=%s", what, type(error).__name__)
                ok = False
            if ok or self.story is not story or story is None:
                return
            # The chapter could not be written or drawn. The voice model carries it in words.
            await self._end_story()
            await self._nudge_words()

        self._story_task = asyncio.create_task(run())
        if inspect.iscoroutine(call):
            # Cancellation may happen before the wrapper starts awaiting it.
            self._story_task.add_done_callback(lambda _task: call.close())

    def _continue_story(self, *, delay: float = 0.0) -> None:
        story = self.story
        if story is None:
            return

        async def go_on() -> bool:
            if delay:
                await asyncio.sleep(delay)
            if self.story is not story or not self._ready_for_input():
                return True
            return await story.continue_()

        self._run_story(go_on(), what="continue")

    async def _pause_story(self, reason: str) -> None:
        """Stop the narration where it is; the picture stays. Resume is the kid's call."""
        story = self.story
        if story is None:
            return
        was_speaking = self._story_speaking()
        task, self._story_task = self._story_task, None
        if task and task is not asyncio.current_task():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        story.pause()
        self._story_resume_after_done = False
        if was_speaking and self.machine.state is State.TALKING:
            # Live's own answers are cut by the caller; this only silences the conductor.
            self.mouth.cancel()
            if self.machine.can("select"):
                self.machine.apply("select")
            await self.emit({"type": "interrupted", "reason": reason})

    async def _end_story(self) -> None:
        story = self.story
        was_speaking = self._story_speaking()
        self.story = None
        self._story_resume_after_done = False
        task, self._story_task = self._story_task, None
        if task and task is not asyncio.current_task():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if story is None:
            return
        story.end()
        if was_speaking and self.machine.state is State.TALKING and self.machine.can("done"):
            self.mouth.cancel()
            self.machine.apply("done")
            await self.emit({"type": "interrupted", "reason": "story_end"})
        self._flush_transcript_turns()
        await story.close()

    async def failed(self) -> None:
        await self._end_story()
        await self._nudge_words()

    async def _nudge_words(self) -> None:
        if self._closing or not self._ready_for_input():
            return
        self._suppress_live_output = False
        try:
            await self._ensure_connected()
            if self._transport:
                await self._transport.send_text(STORY_FALLBACK_NUDGE)
        except Exception as error:  # noqa: BLE001 - silence beats a crash
            logger.warning("Story fallback failed: error=%s", type(error).__name__)

    def _story_speaking(self) -> bool:
        """The conductor owns the voice: a beat is playing, or an opener/continue is in flight."""
        if self.story is None:
            return False
        return self.story.playing or bool(self._story_task and not self._story_task.done())

    # ----- storytelling: the stage (device + voice) as the conductor sees them ------------

    def _issue_story_cue(self) -> int:
        self._last_story_cue += 1
        return self._last_story_cue

    def _on_glass_ready(self, event: GlassReady) -> None:
        key = (event.cue, event.kind)
        future = self._glass_ready.get(key)
        if future is None:
            if self._cinema is not None:
                self._cinema.on_glass_ready(event.cue, event.kind, event.ok)
            return  # Only acknowledge cues actually offered by this session.
        if not future.done():
            future.set_result(event.ok)
        if self._cinema is not None:
            self._cinema.on_glass_ready(event.cue, event.kind, event.ok)
        # Keep only acks near the present; a body may report cues nobody waits for.
        for stale in [k for k in self._glass_ready if k[0] < event.cue - 4]:
            self._glass_ready.pop(stale, None)

    async def cue_still(self, stored: StoredShow, subject: str, cue: int) -> None:
        self._expect_glass(cue, "still")
        await self.emit({
            "type": "glass", "still": stored.still_url, "subject": subject,
            "viewing": True, "cue": cue, "hold": True,
        })

    async def play_film(self, utterance: str) -> None:
        """Told-piece moving chapter: one Cinema film, then wait until it ends."""
        result = await self._start_film(utterance)
        if not result.get("ok"):
            return
        try:
            deadline = asyncio.get_running_loop().time() + 180
            while self.film_active() and asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(0.2)
        except asyncio.CancelledError:
            await self._stop_film(reason="interrupt", announce=False)
            raise

    def _expect_glass(self, cue: int, kind: str) -> None:
        for stale in [key for key in self._glass_ready if key[0] < cue - 4]:
            self._glass_ready.pop(stale, None)
        self._glass_ready.setdefault((cue, kind), asyncio.get_running_loop().create_future())

    async def wait_ready(self, cue: int, kind: str, timeout: float) -> bool:
        if not self._cue_listeners:
            return False
        key = (cue, kind)
        future = self._glass_ready.get(key)
        if future is None:
            future = asyncio.get_running_loop().create_future()
            self._glass_ready[key] = future
        timeout = min(timeout, self._glass_ready_timeout)
        try:
            return bool(await asyncio.wait_for(asyncio.shield(future), timeout))
        except TimeoutError:
            return False
        finally:
            self._glass_ready.pop(key, None)

    async def go(self, cue: int, stored: StoredShow, subject: str, motion: bool) -> None:
        if self._show_idle_task and self._show_idle_task is not asyncio.current_task():
            self._show_idle_task.cancel()
        self.current_show = stored
        self.current_show_subject = subject
        _ = motion
        self._show_visible_at = asyncio.get_running_loop().time()
        event = {**(self.show_event() or {}), "cue": cue, "go": True}
        await self.emit(event)
        if self.show_idle_s > 0:
            self._show_idle_task = asyncio.create_task(self._watch_show_idle())
        if self._transport:
            # Live sees the picture too, so a "what's that?" lands on the right thing.
            try:
                still = await asyncio.to_thread(stored.still_path.read_bytes)
                await self._transport.send_image(
                    f"data:image/jpeg;base64,{base64.b64encode(still).decode('ascii')}"
                )
            except Exception as error:  # noqa: BLE001 - the picture on the glass is what matters
                logger.debug("Story image to Live skipped: error=%s", type(error).__name__)

    async def speak(self, narration: Narration) -> None:
        """Send one beat's voice at real time, a little ahead, so a press can stop it fast."""
        await self._start_talking()
        self.mouth.mark_playing()
        loop = asyncio.get_running_loop()
        started = loop.time()
        sent_seconds = 0.0
        pcm = narration.pcm
        for offset in range(0, len(pcm), STORY_CHUNK_BYTES):
            chunk = pcm[offset:offset + STORY_CHUNK_BYTES]
            ahead = sent_seconds - (loop.time() - started)
            if ahead > self._story_audio_lead:
                await asyncio.sleep(ahead - self._story_audio_lead)
            self.mouth.speak_pcm(chunk)
            await self.emit({"type": "audio", "pcm": base64.b64encode(chunk).decode("ascii")})
            sent_seconds += len(chunk) / 2 / 24_000
        remaining = sent_seconds - (loop.time() - started)
        if remaining > 0:
            await asyncio.sleep(remaining)

    async def rest(self) -> None:
        self.mouth.mark_idle()
        if self.machine.state is State.TALKING and self.machine.can("done"):
            self.machine.apply("done")
        self._flush_transcript_turns()
        await self.emit({"type": "state", "reason": "chapter"})

    async def remember(self, text: str) -> None:
        self._record_transcript("assistant", text)
        remember = getattr(self._transport, "remember", None)
        if remember is None:
            return
        try:
            await remember(text)
        except Exception as error:  # noqa: BLE001 - his memory of the chapter is best-effort
            logger.warning("Story context sync failed: error=%s", type(error).__name__)

    async def _run_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name not in ALLOWED_TOOLS:
            return {"ok": False, "reason": f"unknown tool {name}"}
        if name == "show":
            return await self._show(arguments)
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
