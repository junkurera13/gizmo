"""Story mode in the session: hold-and-decide, routing, the stage, and the controls."""

from __future__ import annotations

import asyncio
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from PIL import Image

from gizmo_friend.body_protocol import GlassReady, PushToTalk, Select, TextLine
from gizmo_friend.brain.images import ConjuredStill, ImageProvider
from gizmo_friend.brain.memory import NullMemoryProvider
from gizmo_friend.brain.narration import Narration, NarrationProvider
from gizmo_friend.brain.reasoning import NullReasoningProvider
from gizmo_friend.brain.show_budget import ShowBudget
from gizmo_friend.brain.story import Beat, StoryIntent, StoryPlanner, Storyboard
from gizmo_friend.session import GizmoSession
from gizmo_friend.states import State
from gizmo_friend.transport.base import TransportEvent


def board(*beats: str, finished: bool = True) -> Storyboard:
    return Storyboard(
        title="t", setting="s", character="",
        beats=tuple(Beat(narration=text, scene=f"scene {text}", motion="") for text in beats),
        remaining="" if finished else "more", finished=finished,
    )


class ScriptedPlanner(StoryPlanner):
    """The scout answers from a script keyed by utterance; plans come from a queue."""

    def __init__(self, *boards: Storyboard | None):
        self.boards = list(boards)
        self.routes: dict[str, StoryIntent] = {}
        self.scouted: list[tuple[str, bool]] = []
        self.scout_gate = asyncio.Event()
        self.scout_gate.set()

    async def scout(self, utterance, context):
        self.scouted.append((utterance, context.active))
        await self.scout_gate.wait()
        return self.routes.get(utterance, StoryIntent())

    async def plan(self, context, *, beats=3, edit=""):
        return self.boards.pop(0) if self.boards else None


class InstantImages(ImageProvider):
    async def conjure(self, subject, *, kind="scene", character="", reference=None):
        encoded = io.BytesIO()
        Image.new("RGB", (512, 384), "teal").save(encoded, "JPEG")
        return ConjuredStill(subject=subject, jpeg=encoded.getvalue(), prompt="p", model="m",
                             width=512, height=384, source_width=512, source_height=384, latency_seconds=0)


class InstantNarration(NarrationProvider):
    def __init__(self, seconds: float = 0.05):
        self.seconds = seconds
        self.texts: list[str] = []

    async def narrate(self, text):
        self.texts.append(text)
        return Narration(text=text, pcm=b"\x00\x00" * int(24_000 * self.seconds), model="fake", latency_seconds=0)


class StorySessionFixture(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Budget writes run via to_thread; a cancelled task's thread can finish
        # its write after close() returns, racing this cleanup's rmtree.
        self.temporary = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.planner = ScriptedPlanner(board("one", "two"))
        self.narration = InstantNarration()
        self.transport = SimpleNamespace(**{
            name: AsyncMock() for name in [
                "send_text", "close", "interrupt", "submit_tool_output", "send_image",
                "clear_pending_image", "begin_audio", "send_audio", "commit_audio", "remember",
            ]
        })
        self.friend = GizmoSession(
            self.root / "devices" / "test-a", user_id="test-a", gemini_key="",
            memory_provider=NullMemoryProvider(), reasoning_provider=NullReasoningProvider(),
            image_provider=InstantImages(), show_budget=ShowBudget(self.root),
            story_planner=self.planner,
            narration_provider=self.narration,
            transport_factory=lambda handle: self.transport, idle_sleep_s=0, show_idle_s=0,
        )
        self.friend._story_audio_lead = 10.0  # tests do not wait for real-time pacing
        self.friend._glass_ready_timeout = 0.02
        self.friend.machine.state = State.LISTENING
        self.friend._transport = self.transport
        self.friend._connected = True
        self.friend._touch()
        self.queue = self.friend.subscribe(glass_cues=True)
        self.addAsyncCleanup(self.friend.close)

    def events(self):
        items = []
        while not self.queue.empty():
            items.append(self.queue.get_nowait())
        return items

    async def live(self, kind, **fields):
        await self.friend._on_transport(TransportEvent(kind=kind, **fields))

    async def wait_until(self, predicate, seconds=2.0):
        async with asyncio.timeout(seconds):
            while not predicate():
                await asyncio.sleep(0.005)

    async def story_rested(self):
        await self.wait_until(lambda: self.friend.story is not None and not self.friend.story.playing
                              and self.friend.story.context.at_boundary and self.friend.story.context.chapter > 0)


class HoldAndDecideTests(StorySessionFixture):
    async def test_ordinary_text_never_pays_for_the_scout(self):
        await self.friend.handle(TextLine(text="how far is the moon"))
        await self.live("audio", pcm=b"\x01\x00" * 10)
        self.assertEqual(self.planner.scouted, [])
        self.assertIn("audio", [event["type"] for event in self.events()])
        self.assertIsNone(self.friend.story)

    async def test_story_ask_holds_live_then_drops_it_and_plays_the_piece(self):
        ask = "tell me the story of pompeii"
        self.planner.routes[ask] = StoryIntent(route="begin", premise="pompeii", opener="Right. Pompeii.")
        self.planner.scout_gate.clear()
        await self.friend.handle(TextLine(text=ask))
        await self.live("audio", pcm=b"\x01\x00" * 10)
        await self.live("transcript_delta", text="Sure, so")
        # Nothing of Live's answer reached the body while the scout decides.
        self.assertNotIn("audio", [event["type"] for event in self.events()])
        self.planner.scout_gate.set()
        await self.story_rested()
        self.transport.interrupt.assert_awaited()
        events = self.events()
        kinds = [event["type"] for event in events]
        self.assertNotIn("transcript_delta", kinds)
        self.assertEqual(self.narration.texts, ["Right. Pompeii.", "one", "two"])
        glass = [event for event in events if event["type"] == "glass"]
        self.assertEqual([(g.get("cue"), g.get("hold"), g.get("go")) for g in glass], [
            (1, True, None), (1, None, True), (2, True, None), (2, None, True),
        ])
        self.assertTrue(all(g["viewing"] for g in glass))
        # The last picture stays, and the voice model was told what he narrated.
        self.assertIsNotNone(self.friend.current_show)
        self.transport.remember.assert_awaited_with("one two")
        self.assertEqual(self.friend.state, State.LISTENING)

    async def test_gate_miss_on_voice_releases_at_first_audio(self):
        await self.friend.handle(PushToTalk(active=True))
        await self.friend.handle(PushToTalk(active=False))
        await self.live("user_transcript_preview", text="what's a black hole")
        await self.live("audio", pcm=b"\x01\x00" * 10)
        self.assertEqual(self.planner.scouted, [])
        self.assertIn("audio", [event["type"] for event in self.events()])
        self.assertIsNone(self.friend._hold)

    async def test_voice_story_ask_scouts_once_the_voice_starts(self):
        ask = "tell me the story of the moon landing"
        self.planner.routes[ask] = StoryIntent(route="begin", premise="moon landing", opener="")
        await self.friend.handle(PushToTalk(active=True))
        await self.friend.handle(PushToTalk(active=False))
        await self.live("user_transcript_preview", text="tell me the story")
        self.assertEqual(self.planner.scouted, [])  # partial words: keep waiting
        await self.live("user_transcript_preview", text=ask)
        self.assertEqual(self.planner.scouted, [])
        await self.live("audio", pcm=b"\x01\x00" * 10)
        await self.wait_until(lambda: self.planner.scouted == [(ask, False)])
        await self.story_rested()
        self.assertNotIn("transcript_delta", [event["type"] for event in self.events()])

    async def test_late_scout_fails_open(self):
        ask = "tell me the story of rome"
        self.planner.scout_gate.clear()
        await self.friend.handle(TextLine(text=ask))
        await self.live("audio", pcm=b"\x01\x00" * 10)
        self.friend._cancel_hold_timer()
        self.friend._hold_started_at = 0.0
        # Simulate the timer firing without waiting HOLD_STORY_SECONDS.
        self.friend._cancel_scout()
        await self.friend._release_hold()
        self.assertIn("audio", [event["type"] for event in self.events()])
        self.assertIsNone(self.friend.story)


class RunningStoryTests(StorySessionFixture):
    async def begin(self):
        ask = "tell me the story of pompeii"
        self.planner.routes[ask] = StoryIntent(route="begin", premise="pompeii", opener="")
        await self.friend.handle(TextLine(text=ask))
        await self.live("audio", pcm=b"\x01\x00" * 10)
        await self.story_rested()
        self.events()

    async def test_side_question_is_answered_then_the_story_goes_on(self):
        self.planner.boards = [board("three")]
        await self.begin()
        self.planner.routes["why did they stay"] = StoryIntent(route="question")
        await self.friend.handle(TextLine(text="why did they stay"))
        await self.live("audio", pcm=b"\x01\x00" * 10)
        await self.wait_until(lambda: self.friend._hold is None)
        self.assertIn("audio", [event["type"] for event in self.events()])  # Live's answer played
        await self.live("done")
        await self.wait_until(lambda: "three" in self.narration.texts, seconds=3)

    async def test_leave_ends_the_story_and_lets_live_answer(self):
        await self.begin()
        self.planner.routes["what's for dinner"] = StoryIntent(route="leave")
        await self.friend.handle(TextLine(text="what's for dinner"))
        await self.live("audio", pcm=b"\x01\x00" * 10)
        await self.wait_until(lambda: self.friend.story is None)
        self.assertIn("audio", [event["type"] for event in self.events()])

    async def test_ptt_pauses_and_select_dismisses(self):
        self.narration.seconds = 1.0
        ask = "tell me the story of pompeii"
        self.planner.routes[ask] = StoryIntent(route="begin", premise="pompeii", opener="")
        await self.friend.handle(TextLine(text=ask))
        await self.live("audio", pcm=b"\x01\x00" * 10)
        await self.wait_until(lambda: self.friend.state is State.TALKING)
        self.events()
        await self.friend.handle(PushToTalk(active=True))
        self.assertFalse(self.friend.story.playing)
        self.assertEqual(self.friend.state, State.LISTENING)
        self.assertIn("interrupted", [event["type"] for event in self.events()])
        await self.friend.handle(PushToTalk(active=False))
        await self.friend.handle(Select())
        self.assertIsNone(self.friend.story)
        self.assertIsNone(self.friend.current_show)

    async def test_glass_tools_are_refused_while_a_story_runs(self):
        await self.begin()
        result = await self.friend._run_tool("show", {"subject": "a volcano"})
        self.assertEqual(result, {"ok": False, "reason": "story running"})

    async def test_failed_plan_falls_back_to_words(self):
        self.planner.boards = []
        ask = "tell me the story of pompeii"
        self.planner.routes[ask] = StoryIntent(route="begin", premise="pompeii", opener="Right.")
        await self.friend.handle(TextLine(text=ask))
        await self.live("audio", pcm=b"\x01\x00" * 10)
        await self.wait_until(lambda: self.friend.story is None and self.transport.send_text.await_count == 2)
        nudge = self.transport.send_text.await_args_list[-1].args[0]
        self.assertIn("in words", nudge)


class GlassAckTests(StorySessionFixture):
    async def test_go_waits_for_the_body_ack_when_the_body_acks(self):
        self.friend._glass_ready_timeout = 6.0
        ask = "tell me the story of pompeii"
        self.planner.routes[ask] = StoryIntent(route="begin", premise="pompeii", opener="")
        await self.friend.handle(TextLine(text=ask))
        await self.live("audio", pcm=b"\x01\x00" * 10)
        await self.wait_until(lambda: any(e.get("hold") for e in self.peek()))
        await asyncio.sleep(0.05)
        self.assertFalse(any(e.get("go") for e in self.peek()))
        await self.friend.handle(GlassReady(cue=1, kind="still"))
        await self.wait_until(lambda: any(e.get("go") for e in self.peek()))

    def peek(self):
        return list(self.queue._queue)  # noqa: SLF001 - inspect without consuming


if __name__ == "__main__":
    unittest.main()

class StoryRegressionTests(StorySessionFixture):
    async def test_real_hold_timer_replays_across_suspending_delivery(self):
        from unittest.mock import patch
        delivered = []
        original = self.friend._on_transport

        async def suspended(event):
            await asyncio.sleep(0)
            delivered.append(event.kind)
            await original(event)

        self.friend._begin_hold()
        self.friend._hold.append(TransportEvent(kind="audio", pcm=b"\x00\x00"))
        self.friend._on_transport = suspended
        with patch("gizmo_friend.session.HOLD_PROVISIONAL_SECONDS", 0.001):
            self.friend._arm_hold_timer()
            timer = self.friend._hold_timer
            await timer
        self.assertEqual(delivered, ["audio"])
        self.assertFalse(timer.cancelled())

    async def test_legacy_listener_only_sees_scene_when_it_goes_live(self):
        legacy = self.friend.subscribe()
        self.addCleanup(self.friend.unsubscribe, legacy)
        await self.friend.emit({"type": "glass", "cue": 1, "hold": True, "still": "/future.jpg"})
        self.assertTrue(legacy.empty())
        self.assertTrue(self.queue.get_nowait()["hold"])
        await self.friend.emit({"type": "glass", "cue": 1, "go": True, "still": "/future.jpg"})
        self.assertTrue(legacy.get_nowait()["go"])

    async def test_unissued_ack_is_ignored_and_new_stories_do_not_reuse_cues(self):
        await self.friend.handle(GlassReady(cue=999999, kind="still"))
        self.assertEqual(self.friend._glass_ready, {})
        self.friend._start_story("first", "")
        first = self.friend.story._issue_cue()
        await self.friend._end_story()
        self.friend._start_story("second", "")
        self.assertGreater(self.friend.story._issue_cue(), first)

    async def test_missing_narration_returns_to_live_without_remembering_unheard_words(self):
        from gizmo_friend.brain.narration import NullNarrationProvider
        self.friend.narration = NullNarrationProvider()
        self.friend._start_story("pompeii", "")
        await self.wait_until(lambda: self.friend.story is None)
        self.transport.send_text.assert_awaited_once()
        self.transport.remember.assert_not_awaited()

    async def test_disabled_story_mode_does_not_hold_a_story_request(self):
        self.friend._story_enabled = False
        await self.friend.handle(TextLine(text="tell me a story about a rocket"))
        await self.live("audio", pcm=b"\x00\x00" * 10)
        self.assertIsNone(self.friend._hold)
        self.assertEqual(self.planner.scouted, [])
        self.assertIn("audio", [event["type"] for event in self.events()])
