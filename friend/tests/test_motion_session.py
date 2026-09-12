from __future__ import annotations

import asyncio
import dataclasses
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from PIL import Image

from gizmo_friend.body_protocol import PushToTalk, Select, TextLine
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
        subject="rocket",
        jpeg=encoded.getvalue(),
        prompt="fixture",
        model="fixture",
        width=512,
        height=384,
        source_width=512,
        source_height=384,
        latency_seconds=0,
    )


class ControlledImages(ImageProvider):
    def __init__(self):
        self.calls = []
        self.kinds = []
        self.identities = []

    async def conjure(self, subject, *, kind="scene", character="", reference=None):
        future = asyncio.get_running_loop().create_future()
        self.calls.append((subject, future))
        self.kinds.append(kind)
        self.identities.append((character, reference))
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


class FixedDirector:
    def __init__(self, decision):
        self.decision = decision
        self.calls = []
        self.contexts = []

    async def decide(
        self,
        utterance,
        *,
        has_visual,
        current_subject="",
        narration="",
        recent_dialogue=(),
        narration_complete=True,
        current_story_setting="",
        current_character="",
        current_medium="talk",
    ):
        self.calls.append((utterance, has_visual, current_subject))
        self.contexts.append({
            "narration": narration,
            "recent_dialogue": recent_dialogue,
            "current_story_setting": current_story_setting,
            "current_character": current_character,
            "current_medium": current_medium,
        })
        return self.decision

    async def close(self):
        return


class ControlledDirector:
    def __init__(self):
        self.calls = []

    async def decide(
        self,
        utterance,
        *,
        has_visual,
        current_subject="",
        narration="",
        recent_dialogue=(),
        narration_complete=True,
        current_story_setting="",
        current_character="",
        current_medium="talk",
    ):
        future = asyncio.get_running_loop().create_future()
        self.calls.append((utterance, has_visual, current_subject, future, current_medium))
        return await future

    async def wait_for_calls(self, count):
        async with asyncio.timeout(1):
            while len(self.calls) < count:
                await asyncio.sleep(0.001)

    def finish(self, index, decision):
        self.calls[index][3].set_result(decision)

    async def close(self):
        for call in self.calls:
            if not call[3].done():
                call[3].cancel()


class ShowSessionFixture(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.images = ControlledImages()
        self.transport = SimpleNamespace(**{
            name: AsyncMock()
            for name in [
                "send_text", "close", "interrupt", "submit_tool_output",
                "send_image", "clear_pending_image", "begin_audio",
                "send_audio", "commit_audio",
            ]
        })
        self.friend = GizmoSession(
            self.root / "devices" / "test-a",
            user_id="test-a",
            gemini_key="",
            memory_provider=NullMemoryProvider(),
            reasoning_provider=NullReasoningProvider(),
            image_provider=self.images,
            show_budget=ShowBudget(self.root),
            transport_factory=lambda handle: self.transport,
            idle_sleep_s=0,
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
        result = await self.friend._run_tool("show", {"subject": subject, **arguments})
        self.assertTrue(result["ok"], result)
        await self.images.wait_for_calls(next_call)
        return result

    async def finish_show(self, index=-1):
        self.images.finish(index)
        await asyncio.wait_for(asyncio.shield(self.friend._show_task), 1)
        self.assertIsNotNone(self.friend.current_show)


class StubCinema:
    def __init__(self):
        self.started = []
        self.directions = []
        self.stopped = 0
        self.active = False
        self.session = None

    async def start(self, text, *, direction=""):
        self.started.append(text)
        self.directions.append(direction)
        self.active = True
        return {"ok": True, "status": "preparing"}

    async def stop(self):
        self.stopped += 1
        self.active = False

    def on_glass_ready(self, cue, kind, ok):
        del cue, kind, ok

    async def close(self):
        self.active = False


class TurnRoutingTests(ShowSessionFixture):
    async def test_every_typed_ask_gets_one_judgment_and_talk_releases_voice(self):
        director = FixedDirector(VisualDecision())
        self.friend.visual_director = director
        await self.friend.handle(TextLine(text="Hi."))
        await self.friend._on_transport(TransportEvent(kind="audio", pcm=b"\x01\x00" * 20))
        await self.friend._on_transport(TransportEvent(kind="transcript", text="Hey."))
        await self.friend._on_transport(TransportEvent(kind="done"))
        await asyncio.wait_for(asyncio.shield(self.friend._director_task), 1)
        self.assertEqual(director.calls, [("Hi.", False, "")])
        self.assertIsNone(self.friend._hold)
        self.assertTrue(any(event.get("type") == "audio" for event in self.events()))

    async def test_still_decision_starts_one_image_and_releases_voice(self):
        director = FixedDirector(VisualDecision(route="still", subject="Silk Road map", kind="diagram"))
        self.friend.visual_director = director
        await self.friend.handle(TextLine(text="Where was the Silk Road?"))
        await self.friend._on_transport(TransportEvent(kind="audio", pcm=b"\x01\x00" * 20))
        await self.images.wait_for_calls(1)
        self.assertIsNone(self.friend._hold)
        self.assertEqual(self.images.calls[0][0], "Silk Road map")
        self.assertEqual(self.images.kinds, ["diagram"])
        await self.finish_show()

    async def test_preview_is_speculative_and_equal_final_reuses_it(self):
        director = ControlledDirector()
        self.friend.visual_director = director
        self.friend._ask_revision += 1
        self.friend._begin_visual_turn("")
        self.friend._begin_hold()
        ask = "Show me a jellyfish."
        await self.friend._on_transport(TransportEvent(kind="user_transcript_preview", text=ask))
        await director.wait_for_calls(1)
        director.finish(0, VisualDecision(route="still", subject="jellyfish"))
        await asyncio.sleep(0)
        self.assertEqual(self.images.calls, [])
        self.assertIsNotNone(self.friend._hold)
        await self.friend._on_transport(TransportEvent(kind="user_transcript", text=ask))
        await self.images.wait_for_calls(1)
        self.assertEqual(len(director.calls), 1)
        await self.finish_show()

    async def test_changed_final_cancels_preview_judgment(self):
        director = ControlledDirector()
        self.friend.visual_director = director
        self.friend._ask_revision += 1
        self.friend._begin_visual_turn("")
        self.friend._begin_hold()
        await self.friend._on_transport(TransportEvent(kind="user_transcript_preview", text="Show me a rocket"))
        await director.wait_for_calls(1)
        await self.friend._on_transport(TransportEvent(kind="user_transcript", text="Show me a rocket engine"))
        await director.wait_for_calls(2)
        self.assertTrue(director.calls[0][3].cancelled())
        director.finish(1, VisualDecision(route="still", subject="rocket engine"))
        await self.images.wait_for_calls(1)
        self.assertEqual(self.images.calls[0][0], "rocket engine")

    async def test_route_deadline_fails_open_to_talk(self):
        director = ControlledDirector()
        self.friend.visual_director = director
        with patch("gizmo_friend.session.TURN_ROUTE_GRACE_SECONDS", 0.001):
            await self.friend.handle(TextLine(text="Tell me something."))
            timer = self.friend._hold_timer
            await director.wait_for_calls(1)
            await self.friend._on_transport(TransportEvent(kind="audio", pcm=b"\x01\x00" * 20))
            await timer
        self.assertTrue(director.calls[0][3].cancelled())
        self.assertIsNone(self.friend._hold)
        self.assertTrue(any(event.get("type") == "audio" for event in self.events()))

    async def test_deadline_does_not_fail_open_after_film_is_judged(self):
        cinema = StubCinema()
        self.friend._cinema = cinema
        self.friend._ask_revision += 1
        self.friend._begin_visual_turn("Show how a rocket launches")
        self.friend._begin_hold()
        self.friend._director_committed = True
        self.friend._director_decision = VisualDecision(route="film", subject="rocket launch")
        await self.friend._on_transport(TransportEvent(kind="audio", pcm=b"\x01\x00" * 20))
        with patch("gizmo_friend.session.TURN_ROUTE_GRACE_SECONDS", 0.001):
            self.friend._arm_committed_route_deadline()
            await self.friend._hold_timer
        self.assertIsNotNone(self.friend._hold)
        self.assertEqual(self.friend._directed_ask_revision, -1)
        self.assertEqual(cinema.started, [])

    async def test_live_audio_before_transcript_does_not_spend_the_route_deadline(self):
        director = ControlledDirector()
        cinema = StubCinema()
        self.friend._cinema = cinema
        self.friend.visual_director = director
        self.friend._ask_revision += 1
        self.friend._begin_visual_turn("")
        self.friend._begin_hold()
        await self.friend._on_transport(TransportEvent(kind="audio", pcm=b"\x01\x00" * 20))
        self.assertIsNone(self.friend._hold_timer)
        self.assertEqual(self.friend._directed_ask_revision, -1)
        await self.friend._on_transport(
            TransportEvent(kind="user_transcript", text="Show how a rocket launches")
        )
        self.assertIsNotNone(self.friend._hold_timer)
        await director.wait_for_calls(1)
        director.finish(0, VisualDecision(route="film", subject="rocket launch"))
        await asyncio.wait_for(asyncio.shield(self.friend._director_task), 1)
        self.assertEqual(cinema.started, ["Show how a rocket launches"])
        self.assertTrue(self.friend._suppress_live_output)

    async def test_new_ask_cancels_stale_judgment(self):
        director = ControlledDirector()
        self.friend.visual_director = director
        await self.friend.handle(TextLine(text="What did a castle look like?"))
        await director.wait_for_calls(1)
        await self.friend.handle(TextLine(text="Where was the Silk Road?"))
        await director.wait_for_calls(2)
        self.assertTrue(director.calls[0][3].cancelled())
        director.finish(1, VisualDecision(route="still", subject="Silk Road map"))
        await self.images.wait_for_calls(1)

    async def test_authoritative_still_is_not_upgraded_by_question_words(self):
        cinema = StubCinema()
        self.friend._cinema = cinema
        self.friend.visual_director = FixedDirector(VisualDecision(route="still", subject="rocket"))
        await self.friend.handle(TextLine(text="Why do rockets fly?"))
        await self.images.wait_for_calls(1)
        self.assertEqual(cinema.started, [])

    async def test_authoritative_film_is_not_downgraded_by_easy_wording(self):
        cinema = StubCinema()
        self.friend._cinema = cinema
        self.friend.visual_director = FixedDirector(VisualDecision(route="film", subject="lettering sequence"))
        await self.friend.handle(TextLine(text="How do you spell rocket?"))
        await asyncio.wait_for(asyncio.shield(self.friend._director_task), 1)
        self.assertEqual(cinema.started, ["How do you spell rocket?"])


class FilmCapabilityTests(ShowSessionFixture):
    async def test_film_uses_directed_brief_and_no_still(self):
        cinema = StubCinema()
        self.friend._cinema = cinema
        self.friend.visual_director = FixedDirector(
            VisualDecision(route="film", subject="rocket exhaust and upward thrust")
        )
        await self.friend.handle(TextLine(text="How does a rocket take off?"))
        await asyncio.wait_for(asyncio.shield(self.friend._director_task), 1)
        self.assertEqual(cinema.started, ["How does a rocket take off?"])
        self.assertEqual(cinema.directions, ["rocket exhaust and upward thrust"])
        self.assertEqual(self.images.calls, [])
        self.assertTrue(self.friend._suppress_live_output)

    async def test_film_failure_replays_voice_buffered_before_and_after_start(self):
        cinema = StubCinema()
        self.friend._cinema = cinema
        self.friend._begin_hold()
        first = b"\x01\x00" * 20
        second = b"\x02\x00" * 20
        await self.friend._on_transport(TransportEvent(kind="audio", pcm=first))
        await self.friend._start_film("Why do rockets fly?", direction="thrust")
        await self.friend._on_transport(TransportEvent(kind="audio", pcm=second))
        self.assertEqual(len(self.friend._film_live_fallback), 2)
        self.events()
        cinema.active = False
        await self.friend._on_film_failed()
        await self.friend._on_film_idle()
        audio = [event for event in self.events() if event.get("type") == "audio"]
        self.assertEqual(len(audio), 2)

    async def test_first_presented_segment_discards_voice_fallback(self):
        cinema = StubCinema()
        self.friend._cinema = cinema
        self.friend._begin_hold()
        await self.friend._on_transport(TransportEvent(kind="audio", pcm=b"\x01\x00" * 20))
        await self.friend._start_film("Why do rockets fly?")
        await self.friend._on_film_presenting()
        self.assertIsNone(self.friend._film_live_fallback)
        cinema.active = False
        await self.friend._on_film_idle()
        self.assertFalse(any(event.get("type") == "audio" for event in self.events()))

    async def test_continuation_judgment_sees_previous_film_medium(self):
        first = FixedDirector(VisualDecision(route="film", subject="Titanic voyage"))
        cinema = StubCinema()
        self.friend._cinema = cinema
        self.friend.visual_director = first
        await self.friend.handle(TextLine(text="What was the Titanic?"))
        await asyncio.wait_for(asyncio.shield(self.friend._director_task), 1)
        cinema.active = False
        await self.friend._on_film_idle()
        second = FixedDirector(VisualDecision(route="film", subject="the collision and sinking", thread="continue"))
        self.friend.visual_director = second
        await self.friend.handle(TextLine(text="And then?"))
        await asyncio.wait_for(asyncio.shield(self.friend._director_task), 1)
        self.assertEqual(second.contexts[0]["current_medium"], "film")

    async def test_ptt_and_select_stop_active_film(self):
        cinema = StubCinema()
        self.friend._cinema = cinema
        await self.friend._start_film("Why do rockets fly?")
        await self.friend.handle(PushToTalk(active=True))
        if self.friend._ptt_open_task:
            await self.friend._ptt_open_task
        await self.friend.handle(PushToTalk(active=False))
        self.assertEqual(cinema.stopped, 1)
        await self.friend._start_film("Why do rockets fly?")
        await self.friend.handle(Select())
        self.assertEqual(cinema.stopped, 2)

    async def test_film_preparing_uses_silent_thinking_state(self):
        await self.friend._on_film_preparing()
        events = self.events()
        self.assertEqual(self.friend.machine.state, State.THINKING)
        self.assertTrue(any(event.get("type") == "glass" and event.get("reason") == "film" for event in events))
        self.assertFalse(any(event.get("type") in {"audio", "transcript_delta"} for event in events))

    async def test_live_tool_call_cannot_spend_a_still_inside_a_film(self):
        cinema = StubCinema()
        self.friend._cinema = cinema
        self.friend.visual_director = FixedDirector(VisualDecision(route="film", subject="the sinking"))
        await self.friend.handle(TextLine(text="How did the Titanic sink?"))
        await asyncio.wait_for(asyncio.shield(self.friend._director_task), 1)
        await self.friend._on_transport(TransportEvent(
            kind="function_call", name="show", arguments={"subject": "iceberg"}, call_id="c1",
        ))
        self.transport.submit_tool_output.assert_awaited_with(
            "c1", json.dumps({"ok": False, "reason": "film owns the turn"})
        )
        self.assertEqual(self.images.calls, [])

    async def test_deep_think_cannot_move_the_thinking_state_during_a_film(self):
        cinema = StubCinema()
        self.friend._cinema = cinema
        await self.friend._start_film("How did the Titanic sink?")
        await self.friend._on_film_preparing()
        self.assertEqual(self.friend.machine.state, State.THINKING)
        await self.friend._on_transport(TransportEvent(
            kind="function_call", name="deep_think", arguments={"question": "why"}, call_id="c2",
        ))
        self.assertEqual(self.friend.machine.state, State.THINKING)
        self.assertTrue(self.transport.submit_tool_output.await_count >= 1)


class FilmAckTests(unittest.TestCase):
    def test_ack_lines_are_a_dry_wait(self):
        from gizmo_friend.session import FILM_ACK_LINES, FILM_ACK_STYLE
        joined = " ".join(FILM_ACK_LINES).lower()
        self.assertNotIn("ooh", joined)
        self.assertNotIn("cook", joined)
        self.assertNotIn("—", " ".join(FILM_ACK_LINES))
        self.assertIn("brisk", FILM_ACK_STYLE.lower())
        self.assertIn("breathy", FILM_ACK_STYLE.lower())


if __name__ == "__main__":
    unittest.main()
