from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import imageio_ffmpeg
from PIL import Image

from gizmo_friend.body_protocol import PushToTalk, Select, TextLine
from gizmo_friend.brain.clips import ClipProvider, ConjuredClip, NullClipProvider
from gizmo_friend.brain.images import ConjuredStill, ImageProvider
from gizmo_friend.brain.memory import NullMemoryProvider
from gizmo_friend.brain.reasoning import NullReasoningProvider
from gizmo_friend.brain.show_budget import ShowBudget
from gizmo_friend.brain.visual_director import VisualDecision
from gizmo_friend.session import GizmoSession
from gizmo_friend.states import State
from gizmo_friend.transport.base import TransportEvent


def sample_still() -> ConjuredStill:
    encoded = io.BytesIO()
    Image.new("RGB", (512, 384), "purple").save(encoded, "JPEG")
    return ConjuredStill(
        subject="rocket", jpeg=encoded.getvalue(), prompt="fixture", model="fixture",
        width=512, height=384, source_width=512, source_height=384, latency_seconds=0,
    )


class ControlledImages(ImageProvider):
    def __init__(self):
        self.calls = []
        self.kinds = []

    async def conjure(self, subject, *, kind="scene"):
        future = asyncio.get_running_loop().create_future()
        self.calls.append((subject, future))
        self.kinds.append(kind)
        return await future

    async def close(self):
        for _, future in self.calls:
            if not future.done():
                future.set_result(None)

    async def wait_for_calls(self, count):
        async with asyncio.timeout(1):
            while len(self.calls) < count:
                await asyncio.sleep(0.001)

    def finish(self, index=-1, *, empty=False):
        subject, future = self.calls[index]
        future.set_result(None if empty else dataclasses.replace(sample_still(), subject=subject))


class ShowSessionFixture(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.images = ControlledImages()
        self.transport = SimpleNamespace(**{
            name: AsyncMock() for name in ["send_text", "close", "interrupt", "submit_tool_output",
                                           "send_image", "clear_pending_image", "begin_audio",
                                           "send_audio", "commit_audio"]
        })
        self.friend = GizmoSession(
            self.root / "devices" / "test-a", user_id="test-a", gemini_key="",
            memory_provider=NullMemoryProvider(), reasoning_provider=NullReasoningProvider(),
            image_provider=self.images, show_budget=ShowBudget(self.root),
            clip_provider=NullClipProvider(),
            transport_factory=lambda handle: self.transport, idle_sleep_s=0,
        )
        self.friend.machine.state = State.LISTENING
        self.friend._transport = self.transport
        self.friend._connected = True
        self.friend._touch()
        self.queue = self.friend.subscribe()
        self.addAsyncCleanup(self.friend.close)

    def events(self):
        items = []
        while not self.queue.empty():
            items.append(self.queue.get_nowait())
        return items

    async def ask_show(self, subject="rocket", **arguments):
        next_call = len(self.images.calls) + 1
        await self.friend.handle(TextLine(text=f"show {subject}"))
        result = await self.friend._run_tool("show", {"subject": subject, **arguments})
        self.assertTrue(result["ok"], result)
        await self.images.wait_for_calls(next_call)
        return result

    async def finish_show(self, index=-1):
        self.images.finish(index)
        await asyncio.wait_for(asyncio.shield(self.friend._show_task), 1)
        self.assertIsNotNone(self.friend.current_show)


class ControlledClips(ClipProvider):
    def __init__(self, mp4):
        self.mp4 = mp4
        self.calls = []

    async def animate(self, still, motion):
        future = asyncio.get_running_loop().create_future()
        self.calls.append((still, motion, future))
        return await future

    async def wait_for_calls(self, count):
        async with asyncio.timeout(1):
            while len(self.calls) < count:
                await asyncio.sleep(0.001)

    def finish(self, index=-1, *, empty=False):
        still, motion, future = self.calls[index]
        future.set_result(None if empty else ConjuredClip(
            motion=motion, mp4=self.mp4, prompt="synthetic lifecycle fixture",
            model="fixture", request_id=f"fixture-{index}-{len(self.calls)}",
            source_image_sha256=hashlib.sha256(still).hexdigest(),
            latency_seconds=0, expanded_prompt=None, timings={},
        ))


class FixedDirector:
    def __init__(self, decision):
        self.decision = decision
        self.calls = []
        self.contexts = []

    async def decide(self, utterance, *, has_visual, current_subject="",
                     narration="", recent_dialogue=(), narration_complete=True,
                     current_story_setting=""):
        self.calls.append((utterance, has_visual, current_subject))
        self.contexts.append((narration, recent_dialogue))
        return self.decision

    async def close(self):
        return


class ControlledDirector:
    def __init__(self):
        self.calls = []

    async def decide(self, utterance, *, has_visual, current_subject="",
                     narration="", recent_dialogue=(), narration_complete=True,
                     current_story_setting=""):
        future = asyncio.get_running_loop().create_future()
        self.calls.append((utterance, has_visual, current_subject, future))
        return await future

    async def wait_for_calls(self, count):
        async with asyncio.timeout(1):
            while len(self.calls) < count:
                await asyncio.sleep(0.001)

    def finish(self, index, decision):
        self.calls[index][3].set_result(decision)

    async def close(self):
        for *_, future in self.calls:
            if not future.done():
                future.cancel()


class MotionSessionTests(ShowSessionFixture):
    @classmethod
    def setUpClass(cls):
        fixture = tempfile.TemporaryDirectory()
        cls.addClassCleanup(fixture.cleanup)
        source = Path(fixture.name) / "still.jpg"
        target = source.with_suffix(".mp4")
        source.write_bytes(sample_still().jpeg)
        subprocess.run([
            imageio_ffmpeg.get_ffmpeg_exe(), "-nostdin", "-v", "error", "-y",
            "-loop", "1", "-i", str(source), "-t", "0.25", "-r", "24",
            "-c:v", "libx264", "-threads", "1", "-pix_fmt", "yuv420p", str(target),
        ], check=True, capture_output=True, timeout=10)
        cls.mp4 = target.read_bytes()

    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.clips = ControlledClips(self.mp4)
        self.friend.clips = self.clips

    async def moving_show(self, subject="rocket"):
        next_call = len(self.clips.calls) + 1
        await self.ask_show(subject, motion="moves slowly")
        await self.finish_show()
        await self.clips.wait_for_calls(next_call)
        return self.friend.current_show

    async def finish_clip(self, index=-1, *, empty=False):
        tasks = tuple(self.friend._clip_tasks)
        self.clips.finish(index, empty=empty)
        await asyncio.wait_for(asyncio.gather(*tasks), 2)

    async def ask_animate(self):
        await self.friend.handle(TextLine(text="make it move"))
        return await self.friend._run_tool("animate", {"motion": "moves slowly"})

    def motion_count(self):
        return json.loads((self.root / "motion-usage.json").read_text())["motions"]

    async def test_no_motion_sentinels_stay_still_and_do_not_spend(self):
        for sentinel in ("none", "no motion", "still", "static", "n/a", "none needed"):
            await self.ask_show("earth layers", motion=sentinel)
            await self.finish_show()
            metadata = json.loads(self.friend.current_show.metadata_path.read_text())
            self.assertIsNone(metadata["motion"])
        self.assertEqual(self.clips.calls, [])
        self.assertFalse((self.root / "motion-usage.json").exists())

    async def test_director_routes_text_to_one_still_and_stages_it_for_follow_up(self):
        director = FixedDirector(VisualDecision(route="still", subject="Silk Road map"))
        self.friend.visual_director = director
        await self.friend.handle(TextLine(text="Where was the Silk Road?"))
        await self.friend._on_transport(TransportEvent(kind="transcript", text="Routes connected Asia and Europe."))
        await self.friend._on_transport(TransportEvent(kind="done"))
        await self.images.wait_for_calls(1)
        await self.finish_show()
        await asyncio.wait_for(asyncio.shield(self.friend._director_task), 1)
        self.assertEqual(director.calls, [("Where was the Silk Road?", False, "")])
        self.assertEqual(self.images.calls[0][0], "Silk Road map")
        self.assertEqual(self.transport.send_image.await_count, 1)
        metadata = json.loads(self.friend.current_show.metadata_path.read_text())
        self.assertIsNone(metadata["motion"])

    async def test_director_animate_uses_the_existing_show_and_stays_one_per_ask(self):
        await self.ask_show("jellyfish")
        await self.finish_show()
        director = FixedDirector(VisualDecision(route="animate", motion="bell pulses slowly"))
        self.friend.visual_director = director
        await self.friend.handle(TextLine(text="Make it move."))
        await self.clips.wait_for_calls(1)
        await asyncio.wait_for(asyncio.shield(self.friend._director_task), 1)
        self.assertEqual(director.calls, [("Make it move.", True, "jellyfish")])
        self.assertEqual(self.clips.calls[0][1], "bell pulses slowly")
        self.assertEqual(self.transport.interrupt.await_count, 1)
        self.assertEqual(
            await self.friend._run_tool("animate", {"motion": "again"}),
            {"ok": False, "reason": "one per ask"},
        )

    async def test_new_ask_cancels_a_stale_director_choice(self):
        director = ControlledDirector()
        self.friend.visual_director = director
        await self.friend.handle(TextLine(text="What did a castle look like?"))
        await self.friend._on_transport(TransportEvent(kind="transcript", text="A stone castle with towers."))
        await self.friend._on_transport(TransportEvent(kind="done"))
        await director.wait_for_calls(1)
        await self.friend.handle(TextLine(text="Where was the Silk Road?"))
        await self.friend._on_transport(TransportEvent(kind="transcript", text="Routes connected Asia and Europe."))
        await self.friend._on_transport(TransportEvent(kind="done"))
        await director.wait_for_calls(2)
        self.assertTrue(director.calls[0][3].cancelled())
        director.finish(1, VisualDecision(route="still", subject="Silk Road map"))
        await asyncio.wait_for(asyncio.shield(self.friend._director_task), 1)
        await self.images.wait_for_calls(1)
        self.assertEqual(self.images.calls[0][0], "Silk Road map")

    async def test_new_ask_cancels_an_unfinished_still_before_it_reaches_glass(self):
        await self.ask_show("castle at dusk")
        pending = self.friend._show_task
        self.assertIsNotNone(pending)
        await self.friend.handle(TextLine(text="Tell me a joke about socks."))
        await asyncio.gather(pending, return_exceptions=True)

        self.assertTrue(pending.cancelled())
        self.assertTrue(self.images.calls[0][1].cancelled())
        self.assertIsNone(self.friend.current_show)
        self.assertFalse(
            any(
                event.get("type") == "glass" and event.get("viewing")
                for event in self.events()
            )
        )

    async def test_ptt_press_also_cancels_an_unfinished_still(self):
        await self.ask_show("castle at dusk")
        pending = self.friend._show_task
        self.assertIsNotNone(pending)
        await self.friend.handle(PushToTalk(active=True))
        await asyncio.gather(pending, return_exceptions=True)
        if self.friend._ptt_open_task:
            await self.friend._ptt_open_task
        await self.friend.handle(PushToTalk(active=False))

        self.assertTrue(pending.cancelled())
        self.assertTrue(self.images.calls[0][1].cancelled())
        self.assertIsNone(self.friend.current_show)
        self.assertFalse(
            any(
                event.get("type") == "glass" and event.get("viewing")
                for event in self.events()
            )
        )

    async def test_final_voice_transcript_schedules_the_same_director(self):
        director = FixedDirector(VisualDecision(route="still", subject="heart diagram"))
        self.friend.visual_director = director
        self.friend._ask_revision += 1
        self.friend._begin_visual_turn("")
        await self.friend._on_transport(
            TransportEvent(kind="user_transcript", text="What are the heart chambers?")
        )
        await self.friend._on_transport(TransportEvent(kind="transcript", text="Two atria and two ventricles."))
        await self.friend._on_transport(TransportEvent(kind="done"))
        await self.images.wait_for_calls(1)
        await self.finish_show()
        self.assertEqual(director.calls, [("What are the heart chambers?", False, "")])


    async def test_select_drops_late_clip_from_glass_but_saves_it(self):
        saved = await self.moving_show()
        await self.friend.handle(Select())
        self.events()
        await self.finish_clip()
        self.assertEqual(self.events(), [])
        self.assertIsNone(self.friend.show_event())
        self.assertTrue(self.friend.shows.clip_path(saved.id).exists())
        self.transport.clear_pending_image.assert_awaited_once()

    async def test_replacement_cannot_receive_old_clip_and_clears_snapshot(self):
        old = await self.moving_show()
        await self.ask_show("trilobite")
        await self.images.wait_for_calls(2)
        await self.finish_show(1)
        current = self.friend.current_show
        self.events()
        await self.finish_clip()
        self.assertEqual(self.events(), [])
        self.assertTrue(old.clip_path.exists())
        self.assertEqual(self.friend.current_show, current)
        self.assertNotIn("clip", self.friend.show_event())


    async def test_duplicate_animate_during_and_after_clip_does_not_spend_again(self):
        await self.moving_show()
        result = await self.ask_animate()
        self.assertEqual(result["status"], "conjuring")
        self.assertEqual(await self.friend._run_tool("animate", {"motion": "again"}),
                         {"ok": False, "reason": "one per ask"})
        await self.finish_clip()
        self.assertEqual((await self.ask_animate())["status"], "moving")
        self.assertEqual(len(self.clips.calls), 1)
        self.assertEqual(self.motion_count(), 1)
