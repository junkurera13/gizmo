"""Prepare ahead, play in order, remember only what was actually presented."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from pathlib import Path

from gizmo_friend.brain.images import image_provider_from_env
from gizmo_friend.brain.memory import memory_provider_from_env
from gizmo_friend.brain.show_budget import OddityMotionBudget, OddityShowBudget
from gizmo_friend.brain.shows import _atomic_write
from gizmo_friend.oddity.director import Beat, Director
from gizmo_friend.oddity.film import OddityCinema
from gizmo_friend.oddity.interactions import interaction_answer, orbit_result

logger = logging.getLogger(__name__)
MEDIA_NAME = re.compile(r"[0-9a-f]{32}\.(jpg|mp4|wav)")


class ExperienceSession:
    def __init__(self, root: Path, identity: str, send, *, director=None, images=None, cinema=None, memory=None):
        self.identity = identity
        self.directory = root / "oddity" / identity
        self.directory.mkdir(parents=True, exist_ok=True)
        self.send = send
        self.director = director or Director()
        self.images = images or image_provider_from_env()
        self.cinema = cinema or OddityCinema(directory=self.directory)
        self.memory = memory or memory_provider_from_env()
        self.image_budget = OddityShowBudget(root)
        self.video_budget = OddityMotionBudget(root)
        self.history: list[dict] = []
        self.current: dict = {}
        self.journey: dict = {"goal": "", "observations": []}
        self.library: list[dict] = []
        self.pending: dict[str, dict] = {}
        self.turn = ""
        self.utterance = ""
        self.task: asyncio.Task | None = None
        self.character = ""
        self.reference: str | None = None
        self.memory_context = ""
        self.memory_task: asyncio.Task | None = None
        self.media_slots = asyncio.Semaphore(2)
        self.character_lock = asyncio.Lock()
        self.mode = "preview"
        self.moment_id = ""
        self.seed_memory = ""
        self.director_addendum = ""
        path = self.directory / "session.json"
        if path.exists():
            saved = json.loads(path.read_text())
            self.history = saved.get("history", [])[-24:]
            self.current = saved.get("current", {})
            self.journey = saved.get("journey", self.journey)
            self.library = saved.get("library", [])[-40:]
            self.character = saved.get("character", "")
            self.reference = saved.get("reference")
            self.mode = saved.get("mode", "preview")
            self.moment_id = saved.get("moment", "")
            self.seed_memory = saved.get("seed_memory", "")
            self.director_addendum = saved.get("director_addendum", "")
            if self.current.get("playing"):
                self.current.update(playing=False, interrupted=True)
            if self.current.get("awaiting"):
                self.turn = self.current.get("invitation_turn", "")
        self.bounded = self.mode == "moment"

    def save(self):
        _atomic_write(self.directory / "session.json", json.dumps({
            "history": self.history[-24:], "current": self.current,
            "library": self.library[-40:], "character": self.character,
            "reference": self.reference,
            "journey": self.journey,
            "mode": self.mode, "moment": self.moment_id,
            "seed_memory": self.seed_memory, "director_addendum": self.director_addendum,
        }).encode())

    async def load_memory(self):
        remote = ""
        try:
            async with asyncio.timeout(3):
                remote = await self.memory.context("oddity-" + self.identity)
        except Exception:  # noqa: BLE001 - memory is optional context
            logger.info("Oddity memory context unavailable; using local conversation")
        self.memory_context = "\n\n".join(part for part in (self.seed_memory, remote) if part)

    async def event(self, kind: str, turn: str, **values):
        if turn == self.turn:
            await self.send({"type": kind, "turn": turn, **values})

    def planning_history(self) -> list[dict]:
        history = list(self.history[:-1])
        while history and history[-1].get("role") == "user":
            history.pop()
        return history[-24:]

    async def stop(self, *, preserve_invitation=False):
        invitation_turn = self.turn
        self.turn = ""
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.task = None
        if self.cinema:
            await self.cinema.interrupt()
        if self.current.get("playing"):
            self.current["playing"] = False
            self.current["interrupted"] = True
        if self.current.get("interaction") and not preserve_invitation:
            self.current["awaiting"] = False
        if preserve_invitation and self.current.get("awaiting"):
            self.current["invitation_turn"] = invitation_turn
        self.pending.clear()
        self.save()

    async def begin(self, text: str = "", *, audio: bytes | None = None, mime: str = "audio/webm"):
        await self.stop()
        self.turn = uuid.uuid4().hex
        await self.event("turn", self.turn)
        self.task = asyncio.create_task(self.run(self.turn, text, audio, mime))

    def asset(self, data: bytes, suffix: str) -> str:
        name = uuid.uuid4().hex + suffix
        _atomic_write(self.directory / name, data)
        return f"/oddity/media/{name}?session={self.identity}"

    def _screen_for(self, beat: dict, previous_visual):
        if beat["visual"] == "orbit":
            return {"kind": "orbit", "speed": beat["interaction"]["speed"]}
        if beat["visual"] == "film" and beat.get("film"):
            return {"kind": "film", **beat["film"], "subject": beat.get("subject", "")}
        if beat.get("image"):
            return {"image": beat["image"], "subject": beat["subject"]}
        if beat["visual"] == "face":
            return None
        return previous_visual

    async def say(self, text: str) -> bytes | None:
        # One retry: a transient timeout shouldn't mute the beat.
        for _ in range(2):
            try:
                audio = await self.director.speech(text)
                if audio:
                    return audio
            except Exception as error:  # noqa: BLE001 - voice failures become captions
                logger.warning("Oddity voice attempt failed: %s", type(error).__name__)
        return None

    def film_brief(self, beat: Beat) -> str:
        """The director's brief rides to Cinema: angle, motion, and any moment contract."""
        parts = [beat.subject.strip()]
        if beat.motion.strip():
            parts.append("Key motion: " + beat.motion.strip())
        if self.director_addendum.strip():
            parts.append("Moment contract: " + self.director_addendum.strip())
        return "\n".join(part for part in parts if part)

    async def film(self, beat: Beat, index: int, turn: str, result: dict) -> bool:
        """Start Cinema for a film beat. False means the beat must fall back."""
        await self.event("preparing", turn, index=index, stage="film")
        if not self.cinema.available():
            result["warnings"].append("Film is not configured on this server.")
            return False
        if self.bounded and not await asyncio.to_thread(self.video_budget.reserve, "oddity-" + self.identity):
            result["warnings"].append("Today's film allowance is used up.")
            return False

        async def pending(revision: int) -> None:
            # The glass can connect its peer now, while the score is written.
            await self.event("film", turn, phase="pending", index=index, revision=revision)

        film = await self.cinema.start(self.utterance, direction=self.film_brief(beat), on_pending=pending)
        if not film:
            result["warnings"].append("The film couldn't start, so here it is as a picture.")
            return False
        result["film"] = {
            "revision": film.revision,
            "duration": film.duration,
            "title": film.title,
            "timings": list(film.timings),
        }
        if film.narration:
            result["narration"] = film.narration
        if film.soundtrack:
            # Cinema's own recording doubles as the voice if the glass cannot
            # receive the stream: the answer is never reduced to a caption.
            result["audio"] = self.asset(film.soundtrack, ".wav")
        return True

    async def prepare(self, beat: Beat, index: int, turn: str, character: str) -> dict:
        result = {**beat.model_dump(), "id": f"{turn}-{index}", "index": index,
                  "image": None, "video": None, "film": None, "audio": None, "warnings": []}
        if beat.visual == "film":
            if await self.film(beat, index, turn, result):
                return result
            # A film that cannot be made becomes a voiced still of the same
            # brief — the answer still arrives, with a picture and a voice.
            beat = beat.model_copy(update={"visual": "image" if beat.subject.strip() else "keep"})
            result["visual"] = beat.visual

        async def voice():
            audio = await self.say(beat.narration)
            if audio:
                result["audio"] = self.asset(audio, ".wav")
            elif beat.narration:
                result["warnings"].append("Voice is unavailable. This part has captions only.")

        async def visual():
            if beat.visual not in {"image", "diagram"}:
                return
            async with self.media_slots:
                if self.bounded and not await asyncio.to_thread(self.image_budget.reserve, "oddity-" + self.identity):
                    result["warnings"].append("Today's image allowance is used up.")
                    result["visual"] = "keep"
                    return
                async def draw():
                    reference = None
                    if self.reference and character == self.character and MEDIA_NAME.fullmatch(self.reference):
                        reference_path = self.directory / self.reference
                        if reference_path.exists():
                            reference = reference_path.read_bytes()
                    still = await self.images.conjure(beat.subject, kind="diagram" if beat.visual == "diagram" else "scene",
                                                      character=character, reference=reference)
                    if still:
                        result["image"] = self.asset(still.jpeg, ".jpg")
                        if character and not self.reference:
                            self.character = character
                            self.reference = result["image"].rsplit("/", 1)[-1].split("?", 1)[0]
                    return still
                if character:
                    # Later story images must see the first character anchor.
                    async with self.character_lock:
                        still = await draw()
                else:
                    still = await draw()
                if not still:
                    result["warnings"].append("The picture couldn't be made. You can try that thought again.")
                    result["visual"] = "keep"

        async with asyncio.TaskGroup() as group:
            group.create_task(voice())
            group.create_task(visual())
        return result

    async def run(self, turn: str, text: str, audio: bytes | None, mime: str):
        try:
            if audio:
                await self.event("status", turn, stage="hearing")
                text = await self.director.transcribe(audio, mime)
            text = text.strip()[:3000]
            if not text or not any(c.isalnum() for c in text):
                await self.event("error", turn, message="I didn't catch any words. Try again, or type your thought.")
                return
            self.utterance = text
            self.history.append({"role": "user", "text": text})
            self.save()
            await self.event("transcript", turn, role="user", text=text)
            await self.event("status", turn, stage="thinking")
            # The planner never reads back its own thread summaries: a stale
            # goal outranks the kid's actual words and pulls the plan back to
            # an older topic. Continuity comes from history, the live screen,
            # and what was actually heard and observed.
            journey = {key: self.journey[key] for key in ("last_presented", "observations")
                       if self.journey.get(key)}
            context = {**self.current, "journey": journey}
            plan = await self.director.plan(text, self.planning_history(), context, self.memory_context,
                                           contract=self.director_addendum)
            if plan.thread == "new":
                self.journey = {"goal": plan.goal or text[:240], "observations": []}
            elif plan.thread == "detour":
                self.journey.setdefault("return_to", self.journey.get("goal", ""))
                self.journey["detour"] = text[:240]
            elif plan.goal:
                self.journey["goal"] = plan.goal
                self.journey.pop("detour", None)
                self.journey.pop("return_to", None)
            if plan.character != self.character:
                self.character, self.reference = plan.character, None
            await self.event("plan", turn, title=plan.title, medium=plan.medium, beats=[{
                "visual": b.visual, "purpose": b.purpose, "delivery": b.delivery,
            } for b in plan.beats])
            # Two beats ahead at most, which for a film turn means the opener
            # and the film start together. Canceling this task cancels every
            # child, including an in-flight Cinema session, before a new turn.
            async with asyncio.TaskGroup() as group:
                jobs = {}
                for i in range(min(2, len(plan.beats))):
                    jobs[i] = group.create_task(self.prepare(plan.beats[i], i, turn, plan.character))
                for i in range(len(plan.beats)):
                    prepared = await jobs[i]
                    if turn != self.turn:
                        return
                    prepared["title"] = plan.title
                    self.pending[prepared["id"]] = prepared
                    await self.event("beat", turn, beat=prepared)
                    if i + 2 < len(plan.beats):
                        jobs[i + 2] = group.create_task(self.prepare(plan.beats[i + 2], i + 2, turn, plan.character))
            self.save()
            await self.event("ready", turn)
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - turn failures stay on the glass
            logger.warning("Oddity experience failed: %s code=%s", type(error).__name__, getattr(error, "code", None),
                           exc_info=True)
            await self.event("error", turn, message="That thought didn't come through. Try again in a moment.")

    async def playback(self, message: dict):
        if message.get("turn") != self.turn:
            return
        beat = self.pending.get(message.get("id"))
        if not beat:
            return
        phase = message.get("phase")
        if phase == "started":
            if self.current.get("id") == beat["id"]:
                return
            previous_visual = self.current.get("screen")
            if not self.current.get("playing") and (previous_visual or {}).get("kind") == "film":
                previous_visual = None
            screen = self._screen_for(beat, previous_visual)
            self.current = {"id": beat["id"], "utterance": self.utterance,
                            "narration": beat["narration"], "screen": screen,
                            "playing": True, "title": beat["title"], "elapsed": 0,
                            "interaction": beat.get("interaction"), "awaiting": False}
            if beat.get("film"):
                mark_presented = getattr(self.cinema, "mark_presented", None)
                if mark_presented:
                    mark_presented(beat["film"]["revision"])
            archived = dict(beat)
            if beat["visual"] == "keep" and screen:
                archived.update(screen)
            self.library.append(archived)
            self.library = self.library[-40:]
        elif phase == "progress" and self.current.get("id") == beat["id"]:
            self.current["elapsed"] = max(0, min(180, float(message.get("elapsed", 0))))
        elif phase == "finished" and self.current.get("id") == beat["id"]:
            self.current["playing"] = False
            if (self.current.get("screen") or {}).get("kind") == "film":
                # The live film dissolves to the face; current must not claim it stays.
                self.current["screen"] = None
            self.journey["last_presented"] = beat["narration"]
            if beat.get("film"):
                await self.cinema.finish(beat["film"]["revision"])
            if beat.get("interaction"):
                self.current.update(awaiting=True, invitation_turn=self.turn)
            self.history.append({"role": "assistant", "text": beat["narration"],
                                 "visual": beat["subject"], "presented": "completed"})
            self.history = self.history[-24:]
            self.pending.pop(beat["id"], None)
            if self.memory_task:
                self.memory_task.cancel()
            self.memory_task = asyncio.create_task(self.remember())
        self.save()

    def watch(self, message: dict) -> bool:
        """The glass is showing the film beat now: let Director start painting."""
        if message.get("turn") != self.turn or not self.cinema:
            return False
        try:
            revision = int(message.get("revision"))
        except (TypeError, ValueError):
            return False
        return self.cinema.watch(revision)

    async def experiment(self, message: dict):
        if (message.get("turn") != self.turn or message.get("id") != self.current.get("id")
                or not self.current.get("awaiting")
                or (self.current.get("interaction") or {}).get("kind") != "orbit"):
            raise ValueError("That experiment is no longer active")
        trial = orbit_result(message.get("speed"))
        self.current["trials"] = (self.current.get("trials", []) + [trial])[-6:]
        self.current["screen"] = {"kind": "orbit", "speed": trial["speed"], "outcome": trial["outcome"]}
        self.save()
        await self.event("observation", self.turn, id=self.current["id"], observation=trial)

    def answer(self, message: dict) -> str:
        text, observation = interaction_answer(self.current, message, self.turn)
        self.current["awaiting"] = False  # consume exactly once before any await
        self.journey["observations"] = (self.journey.get("observations", []) + [observation])[-8:]
        self.save()
        return text

    def revisit(self, beat_id: str | None):
        if beat_id is None:
            self.current = {"screen": None, "playing": False}
        else:
            beat = next((b for b in self.library if b["id"] == beat_id), None)
            if not beat:
                return
            self.current = {"screen": self._screen_for(beat, None),
                            "narration": beat["narration"],
                            "title": beat["title"], "playing": False, "revisited": True}
        self.save()

    async def remember(self):
        try:
            async with asyncio.timeout(4):
                recent = self.history[-2:]
                if len(recent) == 2 and recent[0]["role"] == "user":
                    await self.memory.remember("oddity-" + self.identity, [
                        {"role": m["role"], "content": m["text"]} for m in recent])
        except Exception:  # noqa: BLE001 - local history is enough
            logger.info("Oddity remote memory unavailable; local history retained")

    async def close(self):
        await self.stop(preserve_invitation=True)
        if self.memory_task:
            self.memory_task.cancel()
            await asyncio.gather(self.memory_task, return_exceptions=True)
        await asyncio.gather(self.director.close(), self.images.close(), self.cinema.close(), self.memory.close(),
                             return_exceptions=True)
