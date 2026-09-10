"""The conductor cuts pictures to the voice: cue, ready, go, then the words."""

from __future__ import annotations

import asyncio
import io
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from gizmo_friend.brain.images import ConjuredStill, ImageProvider
from gizmo_friend.brain.narration import Narration, NarrationProvider
from gizmo_friend.brain.show_budget import ShowBudget
from gizmo_friend.brain.shows import ShowStore
from gizmo_friend.brain.story import Beat, StoryContext, StoryIntent, StoryPlanner, Storyboard
from gizmo_friend.story_run import StoryRun


def still_bytes() -> bytes:
    encoded = io.BytesIO()
    Image.new("RGB", (512, 384), "orange").save(encoded, "JPEG")
    return encoded.getvalue()


def board(*beats: str, finished: bool = False, character: str = "", motion: str = "") -> Storyboard:
    return Storyboard(
        title="t", setting="s", character=character,
        beats=tuple(Beat(narration=text, scene=f"scene of {text}", motion=motion) for text in beats),
        remaining="" if finished else "more", finished=finished,
    )


class ScriptedPlanner(StoryPlanner):
    def __init__(self, *boards: Storyboard | None):
        self.boards = list(boards)
        self.plans: list[tuple[StoryContext, str]] = []
        self.gate = asyncio.Event()
        self.gate.set()

    async def scout(self, utterance, context):
        return StoryIntent()

    async def plan(self, context, *, beats=3, edit=""):
        self.plans.append((context, edit))
        await self.gate.wait()
        return self.boards.pop(0) if self.boards else None


class ControlledImages(ImageProvider):
    """Every conjure blocks on a future the test resolves, so timing is explicit."""

    def __init__(self, auto: bool = False):
        self.calls: list[tuple[str, asyncio.Future]] = []
        self.auto = auto

    async def conjure(self, subject, *, kind="scene", character="", reference=None):
        future = asyncio.get_running_loop().create_future()
        self.calls.append((subject, future))
        if self.auto:
            future.set_result(self._still(subject))
        return await future

    @staticmethod
    def _still(subject):
        return ConjuredStill(subject=subject, jpeg=still_bytes(), prompt="p", model="m",
                             width=512, height=384, source_width=512, source_height=384, latency_seconds=0)

    async def wait_for_calls(self, count):
        async with asyncio.timeout(2):
            while len(self.calls) < count:
                await asyncio.sleep(0.001)

    def finish(self, index):
        subject, future = self.calls[index]
        if not future.done():
            future.set_result(self._still(subject))


class InstantNarration(NarrationProvider):
    def __init__(self):
        self.texts: list[str] = []

    async def narrate(self, text):
        self.texts.append(text)
        return Narration(text=text, pcm=b"\x00\x00" * 2400, model="fake", latency_seconds=0)


class RecordingStage:
    """Records what the body and voice were asked to do, in order."""

    def __init__(self, ready: bool = True, speak_seconds: float = 0.0):
        self.log: list[tuple] = []
        self.ready = ready
        self.speak_seconds = speak_seconds
        self.spoken = asyncio.Event()
        self.rested = asyncio.Event()

    async def play_film(self, utterance):
        self.log.append(("play_film", utterance))

    async def cue_still(self, stored, subject, cue):
        self.log.append(("cue_still", cue, subject))

    async def wait_ready(self, cue, kind, timeout):
        self.log.append(("wait_ready", cue, kind))
        return self.ready

    async def go(self, cue, stored, subject, motion):
        self.log.append(("go", cue, motion))

    async def speak(self, narration):
        self.log.append(("speak", narration.text))
        self.spoken.set()
        if self.speak_seconds:
            await asyncio.sleep(self.speak_seconds)

    async def rest(self):
        self.log.append(("rest",))
        self.rested.set()

    async def remember(self, text):
        self.log.append(("remember", text))

    def kinds(self):
        return [entry[0] for entry in self.log]


class StoryRunFixture(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Budget writes run via to_thread; a cancelled task's thread can finish
        # its write after close() returns, racing this cleanup's rmtree.
        self.temporary = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def run_for(self, planner, images, stage, **overrides) -> StoryRun:
        options = dict(
            stage=stage, planner=planner, narration=InstantNarration(), images=images,
            shows=ShowStore(self.root / "devices" / "d1", device_id="d1"),
            show_budget=ShowBudget(self.root),
            user_id="d1", session_id="s1", premise="pompeii", ready_timeout=0.2, still_wait=0.5,
            narration_wait=0.5, silent_beat=0.01,
        )
        options.update(overrides)
        return StoryRun(**options)

    async def wait_until(self, predicate, seconds=2.0):
        async with asyncio.timeout(seconds):
            while not predicate():
                await asyncio.sleep(0.001)


class PlaybackOrderTests(StoryRunFixture):
    async def test_picture_lands_before_its_words_and_next_beat_is_prefetched(self):
        stage = RecordingStage(speak_seconds=0.05)
        run = self.run_for(ScriptedPlanner(board("one", "two", finished=True)), ControlledImages(auto=True), stage)
        self.assertTrue(await run.begin("Right. Pompeii."))
        await stage.rested.wait()
        await run.close()

        self.assertEqual(stage.log[0], ("speak", "Right. Pompeii."))
        # Beat one: cue, ready, go, then speak. Beat two is cued (held) while beat one is spoken,
        # and its go comes before its words.
        self.assertEqual(stage.log[1:5], [
            ("cue_still", 1, "scene of one"), ("wait_ready", 1, "still"), ("go", 1, False), ("speak", "one"),
        ])
        rest = stage.log[5:]
        self.assertEqual(rest[0], ("cue_still", 2, "scene of two"))
        self.assertLess(rest.index(("go", 2, False)), rest.index(("speak", "two")))
        self.assertEqual(rest[-2:], [("remember", "one two"), ("rest",)])
        # A single cue per beat: prefetch and play never double-cue the same picture twice.
        self.assertEqual(sum(1 for entry in stage.log if entry[0] == "cue_still"), 2)
        self.assertTrue(run.finished)

    async def test_late_picture_does_not_hold_the_words_hostage(self):
        stage = RecordingStage()
        images = ControlledImages()
        run = self.run_for(ScriptedPlanner(board("one", finished=True)), images, stage, still_wait=0.05)
        await run.begin("Opener.")
        await stage.rested.wait()
        await run.close()
        self.assertEqual(stage.kinds(), ["speak", "speak", "remember", "rest"])

    async def test_missing_still_provider_plays_words_only(self):
        stage = RecordingStage()
        from gizmo_friend.brain.images import NullImageProvider
        run = self.run_for(ScriptedPlanner(board("one", "two", finished=True)), NullImageProvider(), stage)
        await run.begin("")
        await stage.rested.wait()
        await run.close()
        self.assertEqual(stage.kinds(), ["speak", "speak", "remember", "rest"])

    async def test_failed_plan_returns_false_and_stays_quiet(self):
        stage = RecordingStage()
        run = self.run_for(ScriptedPlanner(None), ControlledImages(auto=True), stage)
        self.assertFalse(await run.begin("Opener."))
        await run.close()
        self.assertEqual(stage.kinds(), ["speak"])


class ChapterTests(StoryRunFixture):
    async def test_chapter_end_rests_and_warms_the_next_chapter(self):
        stage = RecordingStage()
        planner = ScriptedPlanner(board("one"), board("two", finished=True))
        images = ControlledImages(auto=True)
        run = self.run_for(planner, images, stage)
        await run.begin("Opener.")
        await stage.rested.wait()
        await self.wait_until(lambda: len(planner.plans) == 2)
        # The next chapter was written with what has been told so far.
        context, edit = planner.plans[1]
        self.assertEqual(context.told, "one")
        self.assertEqual(context.remaining, "more")
        self.assertEqual(context.chapter, 1)
        self.assertEqual(edit, "")
        # ...and its pictures are already rendering while he waits for the kid.
        await images.wait_for_calls(2)
        self.assertFalse(run.playing)
        self.assertFalse(run.finished)

        stage.rested.clear()
        self.assertTrue(await run.continue_())
        await stage.rested.wait()
        await run.close()
        self.assertIn(("speak", "two"), stage.log)
        self.assertEqual(sum(1 for entry in stage.log if entry[0] == "cue_still"), 2)
        self.assertTrue(run.finished)
        self.assertFalse(await run.continue_())

    async def test_plan_only_prefetch_renders_pictures_when_the_chapter_is_taken(self):
        stage = RecordingStage()
        planner = ScriptedPlanner(board("one"), board("two", finished=True))
        images = ControlledImages(auto=True)
        run = self.run_for(planner, images, stage, prefetch="plan")
        await run.begin("")
        await stage.rested.wait()
        await self.wait_until(lambda: len(planner.plans) == 2)
        await asyncio.sleep(0.01)
        self.assertEqual(len(images.calls), 1)
        stage.rested.clear()
        await run.continue_()
        await stage.rested.wait()
        await run.close()
        self.assertEqual(len(images.calls), 2)
        self.assertIn(("go", 2, False), stage.log)


class MotionTests(StoryRunFixture):
    async def test_moving_chapter_plays_cinema(self):
        stage = RecordingStage()
        images = ControlledImages(auto=True)
        run = self.run_for(
            ScriptedPlanner(board("one", "two", finished=True, motion="clouds drift")),
            images, stage,
        )
        await run.begin("Right.")
        await stage.rested.wait()
        await run.close()
        self.assertEqual(stage.log, [
            ("speak", "Right."),
            ("play_film", "one two"),
            ("remember", "one two"),
            ("rest",),
        ])
        self.assertEqual(images.calls, [])

    async def test_still_chapter_does_not_play_film(self):
        stage = RecordingStage()
        run = self.run_for(
            ScriptedPlanner(board("one", finished=True)),
            ControlledImages(auto=True), stage,
        )
        await run.begin("")
        await stage.rested.wait()
        await run.close()
        self.assertNotIn("play_film", stage.kinds())
        self.assertIn(("speak", "one"), stage.log)


class InterruptionTests(StoryRunFixture):
    async def test_pause_mid_chapter_resumes_the_interrupted_beat(self):
        stage = RecordingStage(speak_seconds=0.2)
        run = self.run_for(ScriptedPlanner(board("one", "two", finished=True)), ControlledImages(auto=True), stage)
        await run.begin("")
        await self.wait_until(lambda: ("speak", "one") in stage.log)
        run.pause()
        await asyncio.sleep(0.01)
        self.assertTrue(run.paused_mid_chapter)
        self.assertFalse(run.playing)
        self.assertTrue(await run.continue_())
        await stage.rested.wait()
        await run.close()
        speaks = [entry for entry in stage.log if entry[0] == "speak"]
        self.assertEqual(speaks, [("speak", "one"), ("speak", "one"), ("speak", "two")])

    async def test_steer_rewrites_from_the_spoken_point(self):
        stage = RecordingStage(speak_seconds=0.2)
        planner = ScriptedPlanner(board("one", "two", "three"), board("dragon", finished=True))
        run = self.run_for(planner, ControlledImages(auto=True), stage)
        await run.begin("")
        await self.wait_until(lambda: ("speak", "two") in stage.log)
        self.assertTrue(await run.steer("add a dragon", "A dragon. Fine."))
        await stage.rested.wait()
        await run.close()
        context, edit = planner.plans[1]
        self.assertEqual(edit, "add a dragon")
        self.assertEqual(context.told, "one")  # beat two was cut off; only beat one counts as heard
        self.assertEqual(context.chapter, 0)
        spoken = [entry[1] for entry in stage.log if entry[0] == "speak"]
        self.assertEqual(spoken, ["one", "two", "A dragon. Fine.", "dragon"])
        self.assertNotIn(("speak", "three"), stage.log)

    async def test_interrupted_opener_keeps_the_chapter_for_the_next_line(self):
        stage = RecordingStage(speak_seconds=0.3)
        planner = ScriptedPlanner(board("one", finished=True))
        run = self.run_for(planner, ControlledImages(auto=True), stage)
        begin = asyncio.create_task(run.begin("A long opener."))
        await self.wait_until(lambda: ("speak", "A long opener.") in stage.log)
        begin.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await begin
        self.assertTrue(await run.continue_())
        await stage.rested.wait()
        await run.close()
        self.assertEqual(len(planner.plans), 1)
        self.assertIn(("speak", "one"), stage.log)

    async def test_end_stops_everything(self):
        stage = RecordingStage(speak_seconds=0.5)
        images = ControlledImages()
        run = self.run_for(ScriptedPlanner(board("one", "two")), images, stage)
        begin = asyncio.create_task(run.begin(""))
        await images.wait_for_calls(2)
        images.finish(0)
        await self.wait_until(lambda: ("speak", "one") in stage.log)
        run.end()
        await run.close()
        await begin
        self.assertFalse(run.playing)
        self.assertFalse(await run.continue_())
        self.assertNotIn(("speak", "two"), stage.log)


if __name__ == "__main__":
    unittest.main()

class StoryLifecycleRegressionTests(StoryRunFixture):
    async def test_interrupted_plan_stays_available_then_close_joins_it(self):
        planner = ScriptedPlanner(board("one"))
        planner.gate.clear()
        run = self.run_for(planner, ControlledImages(auto=True), RecordingStage())
        opening = asyncio.create_task(run.begin(""))
        await self.wait_until(lambda: bool(planner.plans))
        opening.cancel()
        await asyncio.gather(opening, return_exceptions=True)
        self.assertIsNotNone(run._next)
        self.assertFalse(run._next.cancelled())
        tasks = tuple(run._tasks)
        await run.close()
        self.assertTrue(all(task.done() for task in tasks))
        self.assertFalse(run._tasks)

    async def test_close_joins_prefetched_render_work(self):
        planner = ScriptedPlanner(board("one"), board("two"))
        images = ControlledImages(auto=True)
        stage = RecordingStage()
        run = self.run_for(planner, images, stage)
        await run.begin("")
        await stage.rested.wait()
        await self.wait_until(lambda: len(planner.plans) == 2)
        await run.close()
        self.assertFalse(run._tasks)

    async def test_character_scenes_wait_for_first_reference(self):
        class ReferenceImages(ControlledImages):
            def __init__(self):
                super().__init__()
                self.references = []

            async def conjure(self, subject, **kwargs):
                self.references.append(kwargs.get("reference"))
                return await super().conjure(subject, **kwargs)

        images = ReferenceImages()
        run = self.run_for(ScriptedPlanner(board("one", "two", character="tiny robot")), images, RecordingStage())
        await run.begin("")
        await images.wait_for_calls(1)
        await asyncio.sleep(0.02)
        self.assertEqual(len(images.calls), 1)
        images.finish(0)
        await images.wait_for_calls(2)
        self.assertEqual(images.references, [None, still_bytes()])
        await run.close()

    async def test_body_preloads_picture_while_narration_is_pending(self):
        class PendingNarration(NarrationProvider):
            def __init__(self):
                self.gate = asyncio.Event()

            async def narrate(self, text):
                await self.gate.wait()
                return Narration(text=text, pcm=b"\x00\x00" * 2400, model="fake", latency_seconds=0)

        narration = PendingNarration()
        stage = RecordingStage()
        run = self.run_for(ScriptedPlanner(board("one", finished=True)), ControlledImages(auto=True), stage,
                           narration=narration)
        await run.begin("")
        await self.wait_until(lambda: "cue_still" in stage.kinds())
        self.assertNotIn("speak", stage.kinds())
        narration.gate.set()
        await stage.rested.wait()
        self.assertIn("go", stage.kinds())
        await run.close()
