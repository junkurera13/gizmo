"""Prepare ahead, play in order, remember only what was actually presented."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import uuid
from pathlib import Path

from gizmo_friend.brain.clips import H3MaxClipProvider, NullClipProvider
from gizmo_friend.brain.images import image_provider_from_env
from gizmo_friend.brain.memory import memory_provider_from_env
from gizmo_friend.brain.show_budget import OddityMotionBudget, OddityShowBudget
from gizmo_friend.brain.shows import _atomic_write
from gizmo_friend.oddity.director import Beat, Director

logger = logging.getLogger(__name__)
MEDIA_NAME = re.compile(r"[0-9a-f]{32}\.(jpg|mp4|wav)")
ODDITY_MOTION = (
    "Create one coherent five-second educational animated shot from this first frame. "
    "Preserve its violet and pink print illustration style, subject identity, and geometry. "
    "Depict the requested physical process accurately. Camera movement may help reveal "
    "scale or guide attention. No cuts, new text, logos, gore or frightening imagery. "
    "Keep any labels unchanged. No audio is needed; narration is supplied separately."
)


class ExperienceSession:
    def __init__(self, root: Path, identity: str, send, *, director=None, images=None, clips=None, memory=None):
        self.identity = identity
        self.directory = root / "oddity" / identity
        self.directory.mkdir(parents=True, exist_ok=True)
        self.send = send
        self.director = director or Director()
        self.images = images or image_provider_from_env()
        self.clips = clips or (H3MaxClipProvider(
            api_key=os.environ["FAL_KEY"], timeout_seconds=120, motion_prefix=ODDITY_MOTION,
        ) if os.environ.get("FAL_KEY") else NullClipProvider())
        self.memory = memory or memory_provider_from_env()
        self.image_budget = OddityShowBudget(root)
        self.video_budget = OddityMotionBudget(root)
        self.history: list[dict] = []
        self.current: dict = {}
        self.library: list[dict] = []
        self.pending: dict[str, dict] = {}
        self.turn = ""
        self.task: asyncio.Task | None = None
        self.character = ""
        self.reference: str | None = None
        self.memory_context = ""
        self.memory_task: asyncio.Task | None = None
        self.media_slots = asyncio.Semaphore(2)
        self.character_lock = asyncio.Lock()
        path = self.directory / "session.json"
        if path.exists():
            saved = json.loads(path.read_text())
            self.history = saved.get("history", [])[-24:]
            self.current = saved.get("current", {})
            self.library = saved.get("library", [])[-40:]
            self.character = saved.get("character", "")
            self.reference = saved.get("reference")
            if self.current.get("playing"):
                self.current.update(playing=False, interrupted=True)

    def save(self):
        _atomic_write(self.directory / "session.json", json.dumps({
            "history": self.history[-24:], "current": self.current,
            "library": self.library[-40:], "character": self.character,
            "reference": self.reference,
        }).encode())

    async def load_memory(self):
        try:
            async with asyncio.timeout(3):
                self.memory_context = await self.memory.context("oddity-" + self.identity)
        except Exception:
            logger.info("Oddity memory context unavailable; using local conversation")

    async def event(self, kind: str, turn: str, **values):
        if turn == self.turn:
            await self.send({"type": kind, "turn": turn, **values})

    async def stop(self):
        self.turn = ""
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.task = None
        if self.current.get("playing"):
            self.current["playing"] = False
            self.current["interrupted"] = True
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

    async def prepare(self, beat: Beat, index: int, turn: str, character: str) -> dict:
        result = {**beat.model_dump(), "id": f"{turn}-{index}", "index": index,
                  "image": None, "video": None, "audio": None, "warnings": []}

        async def voice():
            try:
                audio = await self.director.speech(beat.narration)
                if audio:
                    result["audio"] = self.asset(audio, ".wav")
                elif beat.narration:
                    result["warnings"].append("Voice is unavailable. This part has captions only.")
            except Exception as error:
                logger.warning("Oddity voice unavailable: %s", type(error).__name__)
                result["warnings"].append("Voice is unavailable. This part has captions only.")

        async def visual():
            if beat.visual not in {"image", "diagram", "video"}:
                return
            async with self.media_slots:
                if not await asyncio.to_thread(self.image_budget.reserve, "oddity-" + self.identity):
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
                    return
                if beat.visual == "video":
                    await self.event("preparing", turn, index=index, stage="video")
                    if isinstance(self.clips, NullClipProvider):
                        result["warnings"].append("Video generation is not configured on this server. Showing the drawing.")
                    elif await asyncio.to_thread(self.video_budget.reserve, "oddity-" + self.identity):
                        clip = await self.clips.animate(still.jpeg, beat.motion)
                        if clip:
                            result["video"] = self.asset(clip.mp4, ".mp4")
                        else:
                            result["warnings"].append("The video couldn't be made. Showing the drawing.")
                    else:
                        result["warnings"].append("Today's video allowance is used up. Showing the drawing.")
                    if not result["video"]:
                        result["visual"] = "image"

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
            if not text:
                await self.event("error", turn, message="I didn't catch any words. Try again, or type your thought.")
                return
            self.history.append({"role": "user", "text": text})
            self.save()
            await self.event("transcript", turn, role="user", text=text)
            await self.event("status", turn, stage="thinking")
            plan = await self.director.plan(text, self.history[:-1], self.current, self.memory_context)
            if plan.character != self.character:
                self.character, self.reference = plan.character, None
            await self.event("plan", turn, title=plan.title, beats=[{
                "visual": b.visual, "purpose": b.purpose, "delivery": b.delivery,
            } for b in plan.beats])
            # Two beats ahead at most. Canceling this task cancels every child,
            # including in-flight fal queue requests, before a new turn starts.
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
        except Exception as error:
            logger.warning("Oddity experience failed: %s code=%s", type(error).__name__, getattr(error, "code", None))
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
            screen = ({"image": beat["image"], "video": beat["video"], "subject": beat["subject"]}
                      if beat["image"] else (None if beat["visual"] == "face" else previous_visual))
            self.current = {"id": beat["id"], "narration": beat["narration"], "screen": screen,
                            "playing": True, "title": beat["title"], "elapsed": 0}
            archived = dict(beat)
            if beat["visual"] == "keep" and screen:
                archived.update(screen)
            self.library.append(archived)
            self.library = self.library[-40:]
        elif phase == "progress" and self.current.get("id") == beat["id"]:
            self.current["elapsed"] = max(0, min(180, float(message.get("elapsed", 0))))
        elif phase == "finished" and self.current.get("id") == beat["id"]:
            self.current["playing"] = False
            self.history.append({"role": "assistant", "text": beat["narration"],
                                 "visual": beat["subject"], "presented": "completed"})
            self.history = self.history[-24:]
            self.pending.pop(beat["id"], None)
            if self.memory_task:
                self.memory_task.cancel()
            self.memory_task = asyncio.create_task(self.remember())
        self.save()

    def revisit(self, beat_id: str | None):
        if beat_id is None:
            self.current = {"screen": None, "playing": False}
        else:
            beat = next((b for b in self.library if b["id"] == beat_id), None)
            if not beat:
                return
            self.current = {"screen": {"image": beat["image"], "video": beat["video"], "subject": beat["subject"]}
                            if beat["image"] else None, "narration": beat["narration"],
                            "title": beat["title"], "playing": False, "revisited": True}
        self.save()

    async def remember(self):
        try:
            async with asyncio.timeout(4):
                recent = self.history[-2:]
                if len(recent) == 2 and recent[0]["role"] == "user":
                    await self.memory.remember("oddity-" + self.identity, [
                        {"role": m["role"], "content": m["text"]} for m in recent])
        except Exception:
            logger.info("Oddity remote memory unavailable; local history retained")

    async def close(self):
        await self.stop()
        if self.memory_task:
            self.memory_task.cancel()
            await asyncio.gather(self.memory_task, return_exceptions=True)
        await asyncio.gather(self.director.close(), self.images.close(), self.clips.close(), self.memory.close(),
                             return_exceptions=True)
