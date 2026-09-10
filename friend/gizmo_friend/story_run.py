"""The storytelling conductor: renders every beat ahead, then cuts pictures to the voice.

Conversation is improvised by Gemini Live and its pictures chase the words.
A told piece is the other way round. A planner writes the chapter; quiet beats
are drawn and voiced before they are spoken. A chapter that should move plays
one Cinema film (H3 Max Director) instead of Fal still→clips. The conductor
never talks to sockets, models, or state machines directly. The session hands
it a Stage (the device plus the voice) and the providers. That keeps it
testable with fakes, and keeps one owner for the glass.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Callable, Protocol

from gizmo_friend.brain.clips import ClipProvider, NullClipProvider
from gizmo_friend.brain.images import ImageProvider, NullImageProvider
from gizmo_friend.brain.narration import Narration, NarrationProvider
from gizmo_friend.brain.show_budget import MotionBudget, ShowBudget
from gizmo_friend.brain.show_media import MediaError
from gizmo_friend.brain.shows import ShowStore, StoredShow
from gizmo_friend.brain.story import DEFAULT_BEATS, Beat, StoryContext, StoryPlanner, Storyboard

logger = logging.getLogger(__name__)

# How long a beat waits for its picture before it is spoken without one, and
# for its voice before the picture is held in silence. Rendering started long
# before, so these only bite when a provider is slow or down.
STILL_WAIT_SECONDS = 14.0
NARRATION_WAIT_SECONDS = 20.0
READY_TIMEOUT_SECONDS = 6.0
MOTION_READY_GRACE_SECONDS = 1.5
# A beat whose voice failed keeps its picture up this long, then moves on.
SILENT_BEAT_SECONDS = 4.0
# What is warmed for the chapter after this one, before the kid asks for it.
# "plan": words only. "stills": words and pictures. "all" used to mean Fal clips;
# leftover — moving chapters play Cinema instead of clips.
PREFETCH_LEVELS = ("plan", "stills", "all")


class Stage(Protocol):
    """The device and the voice, as the conductor sees them. Implemented by the session."""

    async def cue_still(self, stored: StoredShow, subject: str, cue: int) -> None:
        """Send a held still: the body downloads it but keeps showing the current picture."""

    async def play_film(self, utterance: str) -> None:
        """Play one Cinema film for a moving chapter. The film has its own voice."""

    async def cue_motion(self, stored: StoredShow, cue: int, *, hold: bool) -> None:
        """Leftover Fal clip frames. Product movement is play_film."""

    async def wait_ready(self, cue: int, kind: str, timeout: float) -> bool:
        """Wait until the body reports the cue downloaded and indexed. Decode occurs on display."""

    async def go(self, cue: int, stored: StoredShow, subject: str, motion: bool) -> None:
        """Swap the held cue onto the glass and make it the current Show."""

    async def speak(self, narration: Narration) -> None:
        """Play one beat's voice at real time. Raises CancelledError on interruption."""

    async def rest(self) -> None:
        """A chapter finished: he goes quiet and listens; the picture stays."""

    async def failed(self) -> None:
        """Return to ordinary conversation when scripted narration cannot play."""

    async def remember(self, text: str) -> None:
        """Tell the conversational voice what was just narrated, silently."""


@dataclass
class _BeatRender:
    beat: Beat
    still: asyncio.Future[StoredShow | None] | None = None
    voice: asyncio.Future[Narration | None] | None = None
    motion: asyncio.Future[bool] | None = None
    # Set once the body has been sent this beat's picture (and frames), held for go.
    cued: int | None = None
    motion_cued: bool = False
    played: bool = False
    tasks: set[asyncio.Task[object]] = field(default_factory=set)

    def keep(self, task: asyncio.Task) -> asyncio.Task:
        self.tasks.add(task)
        return task


@dataclass
class _ChapterRender:
    board: Storyboard
    beats: list[_BeatRender]
    pictures_started: bool = False

    def cancel(self) -> None:
        for render in self.beats:
            for task in render.tasks:
                if task is not asyncio.current_task():
                    task.cancel()


class StoryRun:
    """One told piece: its chapters so far, the chapter being played, and the next one warming."""

    def __init__(
        self,
        *,
        stage: Stage,
        planner: StoryPlanner,
        narration: NarrationProvider,
        images: ImageProvider,
        clips: ClipProvider,
        shows: ShowStore,
        show_budget: ShowBudget,
        motion_budget: MotionBudget,
        user_id: str,
        session_id: str,
        premise: str,
        beats_per_chapter: int = DEFAULT_BEATS,
        prefetch: str = "stills",
        motion: bool = True,
        ready_timeout: float = READY_TIMEOUT_SECONDS,
        still_wait: float = STILL_WAIT_SECONDS,
        narration_wait: float = NARRATION_WAIT_SECONDS,
        silent_beat: float = SILENT_BEAT_SECONDS,
        motion_grace: float = MOTION_READY_GRACE_SECONDS,
        next_cue: Callable[[], int] | None = None,
    ) -> None:
        self.stage = stage
        self.planner = planner
        self.narration = narration
        self.images = images
        self.clips = clips
        self.shows = shows
        self.show_budget = show_budget
        self.motion_budget = motion_budget
        self.user_id = user_id
        self.session_id = session_id
        self.context = StoryContext(premise=premise)
        self.beats_per_chapter = beats_per_chapter
        self.prefetch = prefetch if prefetch in PREFETCH_LEVELS else "stills"
        self.motion = motion
        self.ready_timeout = ready_timeout
        self.still_wait = still_wait
        self.narration_wait = narration_wait
        self.silent_beat = silent_beat
        self.motion_grace = motion_grace
        self._cue = 0  # the cue on the glass
        self._issued = 0  # the last cue number handed to the body
        self._reference: bytes | None = None
        self._current: _ChapterRender | None = None
        self._resume_at = 0
        self._next: asyncio.Task[_ChapterRender | None] | None = None
        self._play_task: asyncio.Task[None] | None = None
        self._still_slots = asyncio.Semaphore(3)
        self._clip_slots = asyncio.Semaphore(2)
        self._ended = False
        self._tasks: set[asyncio.Task] = set()
        self._next_cue = next_cue
        self._reference_lock = asyncio.Lock()

    def _spawn(self, coroutine) -> asyncio.Task:
        task = asyncio.create_task(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    # ----- what the session asks -------------------------------------------------

    @property
    def playing(self) -> bool:
        return self._play_task is not None and not self._play_task.done()

    @property
    def paused_mid_chapter(self) -> bool:
        return self._current is not None and not self.context.at_boundary and not self.playing

    @property
    def finished(self) -> bool:
        return self._current is not None and self._current.board.finished and self.context.at_boundary

    @property
    def cue(self) -> int:
        return self._cue

    async def begin(self, opener: str) -> bool:
        """Say the opener while the first chapter is written and drawn, then play it."""
        return await self._open(opener, edit="")

    async def continue_(self) -> bool:
        """The kid pulled the next part. Resume a paused chapter or start the warmed one."""
        if self._ended:
            return False
        if self.paused_mid_chapter and self._current is not None:
            self._start(self._current, self._resume_at)
            return True
        if self.finished:
            return False
        chapter = await self._take_next()
        if chapter is None or self._ended:
            return False
        self._start(chapter, 0)
        return True

    async def steer(self, edit: str, opener: str) -> bool:
        """The kid changed the story. Drop what has not been spoken and rewrite from here."""
        if self._ended:
            return False
        self.pause()
        self._drop_next()
        if self._current is not None and not self.context.at_boundary:
            # Beats already heard stay told; the unspoken remainder is rewritten.
            spoken = self._current.board.beats[: self._resume_at]
            self._current.cancel()
            self.context = StoryContext(
                premise=self.context.premise,
                told=(self.context.told + " " + " ".join(beat.narration for beat in spoken)).strip(),
                remaining=self.context.remaining, character=self.context.character,
                chapter=self.context.chapter, at_boundary=True,
            )
            self._current = None
        return await self._open(opener, edit=edit)

    def pause(self) -> None:
        """Stop the voice where it is. The picture stays; the beat replays on resume."""
        if self._play_task and self._play_task is not asyncio.current_task() and not self._play_task.done():
            self._play_task.cancel()
        self._play_task = None

    def end(self) -> None:
        self._ended = True
        self.pause()
        self._drop_next()
        for task in tuple(self._tasks):
            if task is not asyncio.current_task():
                task.cancel()
        if self._current is not None:
            self._current.cancel()

    async def close(self) -> None:
        self.end()
        pending = tuple(task for task in self._tasks if task is not asyncio.current_task())
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    # ----- writing and rendering ---------------------------------------------------

    async def _open(self, opener: str, *, edit: str) -> bool:
        prepare = self._spawn(self._prepare(self.context, edit=edit, ahead=False))
        try:
            await self._speak_line(opener)
            chapter = await asyncio.shield(prepare)
        except asyncio.CancelledError:
            # The kid spoke over the opener. The chapter keeps being written;
            # their next line decides whether it plays.
            if not self._ended:
                self._next = prepare
            else:
                prepare.cancel()
            raise
        if chapter is None or self._ended:
            return False
        self._start(chapter, 0)
        return True

    async def _prepare(self, context: StoryContext, *, edit: str = "", ahead: bool) -> _ChapterRender | None:
        board = await self.planner.plan(context, beats=self.beats_per_chapter, edit=edit)
        if board is None or self._ended:
            return None
        chapter = _ChapterRender(board=board, beats=[_BeatRender(beat=beat) for beat in board.beats])
        if self._chapter_moves(chapter):
            return chapter
        for render in chapter.beats:
            # Words are cheap and fast; always warm them.
            render.voice = render.keep(self._spawn(self.narration.narrate(render.beat.narration)))
        # The chapter about to play renders everything now, bounded by the slots.
        # A chapter warmed ahead renders what the prefetch level allows.
        if not ahead or self.prefetch in {"stills", "all"}:
            self._start_pictures(chapter)
        return chapter

    def _chapter_moves(self, chapter: _ChapterRender) -> bool:
        return self.motion and any((render.beat.motion or "").strip() for render in chapter.beats)

    def _start_pictures(self, chapter: _ChapterRender) -> None:
        if self._chapter_moves(chapter):
            return
        if not chapter.pictures_started:
            chapter.pictures_started = True
            for render in chapter.beats:
                render.still = render.keep(self._spawn(self._render_still(render.beat, chapter.board)))

    def _ensure_motion(self, render: _BeatRender) -> None:
        """Leftover Fal still→clip. Product movement is _play_chapter_film."""
        if render.motion is None and render.still is not None:
            render.motion = render.keep(self._spawn(self._render_motion(render)))

    async def _render_still(self, beat: Beat, board: Storyboard) -> StoredShow | None:
        if board.character and self._reference is None:
            async with self._reference_lock:
                if self._reference is None:
                    return await self._draw_still(beat, board)
        return await self._draw_still(beat, board)

    async def _draw_still(self, beat: Beat, board: Storyboard) -> StoredShow | None:
        if isinstance(self.images, NullImageProvider):
            return None
        try:
            async with self._still_slots:
                reserved = await asyncio.to_thread(self.show_budget.reserve, self.user_id)
                if not reserved:
                    logger.info("Story still skipped: quiet day")
                    return None
                still = await self.images.conjure(
                    beat.scene, kind="scene", character=board.character, reference=self._reference,
                )
            if still is None:
                return None
            stored = await asyncio.to_thread(
                self.shows.save, still, session_id=self.session_id, motion=beat.motion or None,
            )
            if board.character and self._reference is None:
                self._reference = still.jpeg
            return stored
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - a missing picture never stops the words
            logger.warning("Story still failed: error=%s", type(error).__name__)
            return None

    async def _render_motion(self, render: _BeatRender) -> bool:
        """Leftover Fal image-to-video. Moving chapters use play_film instead."""
        if not self.motion or not render.beat.motion or isinstance(self.clips, NullClipProvider):
            return False
        if render.still is None:
            return False
        try:
            stored = await render.still
            if stored is None:
                return False
            async with self._clip_slots:
                reserved = await asyncio.to_thread(self.motion_budget.reserve, self.user_id)
                if not reserved:
                    logger.info("Story motion skipped: quiet day")
                    return False
                still = await asyncio.to_thread(stored.still_path.read_bytes)
                clip = await self.clips.animate(still, render.beat.motion)
            if clip is None:
                return False
            await asyncio.to_thread(self.shows.save_clip, stored.id, clip)
            return True
        except asyncio.CancelledError:
            raise
        except MediaError as error:
            logger.warning("Story motion failed: error=%s message=%s", type(error).__name__, error)
            return False
        except Exception as error:  # noqa: BLE001 - the still stands
            logger.warning("Story motion failed: error=%s", type(error).__name__)
            return False

    # ----- playback -----------------------------------------------------------------

    def _start(self, chapter: _ChapterRender, beat_index: int) -> None:
        self.pause()
        self._start_pictures(chapter)
        self._current = chapter
        self._resume_at = beat_index
        self.context = StoryContext(
            premise=self.context.premise, told=self.context.told, remaining=self.context.remaining,
            character=chapter.board.character or self.context.character,
            chapter=self.context.chapter, at_boundary=False,
        )
        self._play_task = self._spawn(self._play(chapter, beat_index))

    async def _play_chapter_film(self, chapter: _ChapterRender) -> None:
        narration = " ".join(
            render.beat.narration.strip()
            for render in chapter.beats
            if render.beat.narration.strip()
        ) or chapter.board.title
        for render in chapter.beats:
            render.played = True
        await self.stage.play_film(narration)

    async def _play(self, chapter: _ChapterRender, start: int) -> None:
        try:
            if self._chapter_moves(chapter):
                await self._play_chapter_film(chapter)
                await self._finish_chapter(chapter)
                return
            for index in range(start, len(chapter.beats)):
                self._resume_at = index
                await self._play_beat(chapter, index)
            await self._finish_chapter(chapter)
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - a broken beat ends the chapter quietly
            logger.warning("Story playback failed: error=%s", type(error).__name__)
            heard = " ".join(beat.beat.narration for beat in chapter.beats[:self._resume_at])
            if heard:
                await self.stage.remember(heard)
            await self.stage.failed()

    async def _play_beat(self, chapter: _ChapterRender, index: int) -> None:
        render = chapter.beats[index]
        stored = await self._await(render.still, self.still_wait)
        render.played = True
        if stored is not None:
            if render.cued is None:
                render.cued = self._issue_cue()
                await self.stage.cue_still(stored, render.beat.scene, render.cued)
            cue = self._cue = render.cued
            await self.stage.wait_ready(cue, "still", self.ready_timeout)
            # Let the body download while speech is still rendering.
            voice = await self._await(render.voice, self.narration_wait)
            if voice is None:
                raise RuntimeError("Story narration unavailable")
            await self.stage.go(cue, stored, render.beat.scene, False)
        else:
            voice = await self._await(render.voice, self.narration_wait)
            if voice is None:
                raise RuntimeError("Story narration unavailable")
        if index + 1 < len(chapter.beats):
            self._prefetch_next(chapter.beats[index + 1])
        await self.stage.speak(voice)

    async def _motion_ready(self, render: _BeatRender) -> bool:
        """Leftover Fal clip readiness. Product movement is Cinema."""
        if render.motion is None:
            return False
        if render.motion.done():
            return (not render.motion.cancelled()) and render.motion.exception() is None and bool(render.motion.result())
        # The words are not waiting on the clip; a still under them is the design.
        # A clip that is seconds from done is worth a short wait so the beat opens moving.
        try:
            return bool(await asyncio.wait_for(asyncio.shield(render.motion), self.motion_grace))
        except TimeoutError:
            return False
        except asyncio.CancelledError:
            if render.motion.cancelled():
                return False
            raise

    def _attach_when_ready(self, render: _BeatRender, stored: StoredShow, cue: int) -> None:
        """Leftover Fal clip attach. Product movement is Cinema."""
        async def attach() -> None:
            try:
                ready = await render.motion
                if ready and not self._ended and self.playing and not render.motion_cued and self._current is not None and cue == self._cue:
                    render.motion_cued = True
                    await self.stage.cue_motion(stored, cue, hold=False)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - a late clip is optional
                return

        render.keep(self._spawn(attach()))

    def _prefetch_next(self, render: _BeatRender) -> None:
        """Push the next beat onto the body while this one plays, held until its go."""

        async def prefetch() -> None:
            try:
                stored = await render.still
                if stored is None or self._ended or render.cued is not None or render.played:
                    return
                cue = render.cued = self._issue_cue()
                await self.stage.cue_still(stored, render.beat.scene, cue)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - prefetch is an optimization
                return

        render.keep(self._spawn(prefetch()))

    async def _finish_chapter(self, chapter: _ChapterRender) -> None:
        board = chapter.board
        self.context = StoryContext(
            premise=self.context.premise,
            told=(self.context.told + " " + board.text).strip(),
            remaining=board.remaining,
            character=board.character or self.context.character,
            chapter=self.context.chapter + 1,
            at_boundary=True,
        )
        self._resume_at = len(chapter.beats)
        await self.stage.remember(board.text)
        await self.stage.rest()
        if not board.finished and not self._ended and self._next is None:
            self._next = self._spawn(self._prepare(self.context, ahead=True))

    async def _take_next(self) -> _ChapterRender | None:
        task = self._next
        self._next = None
        if task is None:
            return await self._prepare(self.context, ahead=False)
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            if not self._ended:
                self._next = task
            raise

    def _drop_next(self) -> None:
        task = self._next
        self._next = None
        if task is None:
            return
        if not task.done():
            task.cancel()
        elif not task.cancelled() and task.exception() is None and task.result() is not None:
            task.result().cancel()

    async def _speak_line(self, text: str) -> None:
        text = " ".join(text.split())
        if not text:
            return
        voice = await self.narration.narrate(text)
        if voice is not None and not self._ended:
            await self.stage.speak(voice)

    def _issue_cue(self) -> int:
        # Cue numbers only ever grow, so a rewritten beat never reuses a number the body may hold.
        if self._next_cue is not None:
            return self._next_cue()
        self._issued += 1
        return self._issued

    @staticmethod
    async def _await(future: asyncio.Future | None, timeout: float):
        if future is None:
            return None
        try:
            return await asyncio.wait_for(asyncio.shield(future), timeout)
        except TimeoutError:
            logger.warning("Story render late; playing the beat without it")
            return None
        except asyncio.CancelledError:
            if future.cancelled():
                return None
            raise
        except Exception as error:  # noqa: BLE001 - a failed render is a missing render
            logger.warning("Story render failed: error=%s", type(error).__name__)
            return None
