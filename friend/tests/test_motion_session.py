from __future__ import annotations

import asyncio
import dataclasses
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from gizmo_friend.body_protocol import PushToTalk, Select, TextLine
from gizmo_friend.brain.images import ConjuredStill, ImageProvider
from gizmo_friend.brain.memory import NullMemoryProvider
from gizmo_friend.brain.reasoning import NullReasoningProvider
from gizmo_friend.brain.show_budget import ShowBudget
from gizmo_friend.brain.visual_director import VisualDecision
from gizmo_friend.session import GizmoSession
from gizmo_friend.states import State
from gizmo_friend.transport.base import TransportEvent
from PIL import Image


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


class ShowSessionFixture(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
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


class FixedDirector:
    def __init__(self, decision):
        self.decision = decision
        self.calls = []
        self.contexts = []

    async def decide(self, utterance, *, has_visual, current_subject="",
                     narration="", recent_dialogue=(), narration_complete=True,
                     current_story_setting="", current_character=""):
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
                     current_story_setting="", current_character=""):
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
    async def test_no_motion_sentinels_stay_still_and_do_not_spend(self):
        for sentinel in ("none", "no motion", "still", "static", "n/a", "none needed"):
            await self.ask_show("earth layers", motion=sentinel)
            await self.finish_show()
            metadata = json.loads(self.friend.current_show.metadata_path.read_text())
            self.assertIsNone(metadata["motion"])
            self.assertNotIn("clip", self.friend.show_event() or {})
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

    async def test_explicit_visual_starts_before_any_voice_narration(self):
        cinema = StubCinema()
        self.friend._cinema = cinema
        director = FixedDirector(VisualDecision(route="motion", subject="jellyfish", motion="bell pulses"))
        self.friend.visual_director = director
        await self.friend.handle(TextLine(text="Make a short video of a jellyfish."))
        await self.images.wait_for_calls(1)
        self.assertEqual(len(director.calls), 1)
        self.assertEqual(director.contexts[0][0], "")
        self.assertEqual(cinema.started, [])
        await self.finish_show()
        await self.friend._on_transport(TransportEvent(kind="transcript", text="A jellyfish pushes water to swim."))
        await self.friend._on_transport(TransportEvent(kind="done"))
        self.assertEqual(len(director.calls), 1)
        self.assertEqual(len(self.images.calls), 1)
        metadata = json.loads(self.friend.current_show.metadata_path.read_text())
        self.assertIsNone(metadata["motion"])

    async def test_explicit_voice_request_starts_at_final_input_transcript(self):
        director = FixedDirector(VisualDecision(route="still", subject="volcano"))
        self.friend.visual_director = director
        self.friend._ask_revision += 1
        self.friend._begin_visual_turn("")
        await self.friend._on_transport(TransportEvent(kind="user_transcript", text="Show me a volcano."))
        await self.images.wait_for_calls(1)
        self.assertEqual(director.contexts[0][0], "")

    async def test_input_preview_starts_visual_at_voice_start_without_duplicate_final(self):
        director = FixedDirector(VisualDecision(route="still", subject="jellyfish"))
        self.friend.visual_director = director
        self.friend._ask_revision += 1
        self.friend._begin_visual_turn("")
        await self.friend._on_transport(TransportEvent(kind="user_transcript_preview", text="Show me a jellyfish."))
        await asyncio.sleep(0)
        self.assertEqual(director.calls, [])
        self.assertFalse(any(e.get("type") == "transcript" for e in self.events()))
        await self.friend._on_transport(TransportEvent(kind="audio", pcm=b"\x00\x00" * 240))
        await self.images.wait_for_calls(1)
        self.assertEqual(director.calls[0][0], "Show me a jellyfish.")
        await self.finish_show()
        await self.friend._on_transport(TransportEvent(kind="user_transcript", text="Show me a jellyfish."))
        await self.friend._on_transport(TransportEvent(kind="done"))
        self.assertEqual(len(director.calls), 1)
        self.assertEqual(len(self.images.calls), 1)

    async def test_story_visual_still_waits_for_narration(self):
        director = FixedDirector(VisualDecision())
        self.friend.visual_director = director
        self.friend.story_character = "Fen the fox"
        self.friend.current_story_setting = "castle"
        await self.friend.handle(TextLine(text="Show him in a submarine."))
        await asyncio.sleep(0)
        self.assertEqual(director.calls, [])
        await self.friend._on_transport(TransportEvent(kind="transcript", text="Fen stood inside a submarine beneath the ocean."))
        await self.friend._director_task
        self.assertEqual(len(director.calls), 1)

    async def test_make_it_move_keeps_the_still_without_a_clip(self):
        cinema = StubCinema()
        self.friend._cinema = cinema
        await self.ask_show("jellyfish")
        await self.finish_show()
        still = self.friend.current_show
        director = FixedDirector(VisualDecision(route="animate", motion="bell pulses slowly"))
        self.friend.visual_director = director
        await self.friend.handle(TextLine(text="Make it move."))
        await self.friend._on_transport(TransportEvent(kind="transcript", text="The jellyfish is already there."))
        await self.friend._on_transport(TransportEvent(kind="done"))
        if self.friend._director_task:
            await asyncio.wait_for(asyncio.shield(self.friend._director_task), 1)
        self.assertEqual(cinema.started, [])
        self.assertIs(self.friend.current_show, still)
        self.assertNotIn("clip", self.friend.show_event() or {})
        self.assertFalse(self.friend._suppress_live_output)
        self.assertEqual(
            await self.friend._run_tool("animate", {"motion": "again"}),
            {"ok": False, "reason": "unknown tool animate"},
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


class StubCinema:
    def __init__(self):
        self.started = []
        self.directions = []
        self.stopped = 0
        self.active = False
        self.session = None

    def available(self):
        return True

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


class FilmCapabilityTests(ShowSessionFixture):
    async def test_director_film_starts_cinema_without_a_still(self):
        cinema = StubCinema()
        self.friend._cinema = cinema
        self.friend.visual_director = FixedDirector(
            VisualDecision(route="film", subject="rocket exhaust")
        )
        await self.friend.handle(TextLine(text="How does a rocket actually take off?"))
        await asyncio.wait_for(asyncio.shield(self.friend._director_task), 1)
        self.assertEqual(cinema.started, ["How does a rocket actually take off?"])
        self.assertEqual(self.images.calls, [])
        self.assertTrue(self.friend._suppress_live_output)

    async def test_how_it_works_becomes_film_without_saying_film(self):
        cinema = StubCinema()
        self.friend._cinema = cinema
        self.friend.visual_director = FixedDirector(
            VisualDecision(route="motion", subject="rocket", motion="it lifts")
        )
        await self.friend.handle(TextLine(text="How does a rocket actually take off?"))
        await asyncio.wait_for(asyncio.shield(self.friend._director_task), 1)
        self.assertEqual(cinema.started, ["How does a rocket actually take off?"])
        self.assertEqual(self.images.calls, [])
        self.assertTrue(self.friend._suppress_live_output)

    async def test_process_ask_upgrades_a_still_decision_to_film(self):
        cinema = StubCinema()
        self.friend._cinema = cinema
        self.friend.visual_director = FixedDirector(
            VisualDecision(route="still", subject="rocket")
        )
        await self.friend.handle(TextLine(text="Why do rockets fly?"))
        await asyncio.wait_for(asyncio.shield(self.friend._director_task), 1)
        self.assertEqual(cinema.started, ["Why do rockets fly?"])
        self.assertEqual(self.images.calls, [])

    async def test_story_setting_motion_plays_cinema_with_chapter_words(self):
        cinema = StubCinema()
        self.friend._cinema = cinema
        self.friend.visual_director = FixedDirector(
            VisualDecision(
                route="motion", subject="castle courtyard", motion="clouds drift",
                story_setting="castle",
            )
        )
        await self.friend.handle(TextLine(text="Then what?"))
        await self.friend._on_transport(
            TransportEvent(kind="transcript", text="Fen crossed the castle courtyard as clouds drifted over the towers.")
        )
        await self.friend._on_transport(TransportEvent(kind="done"))
        await asyncio.wait_for(asyncio.shield(self.friend._director_task), 1)
        self.assertEqual(
            cinema.started,
            ["Fen crossed the castle courtyard as clouds drifted over the towers."],
        )
        self.assertEqual(self.friend.current_story_setting, "castle")
        self.assertEqual(self.images.calls, [])

    async def test_easy_talk_does_not_start_a_film(self):
        cinema = StubCinema()
        self.friend._cinema = cinema
        self.friend.visual_director = FixedDirector(VisualDecision())
        await self.friend.handle(TextLine(text="Hi."))
        await self.friend._on_transport(TransportEvent(kind="transcript", text="Hey."))
        await self.friend._on_transport(TransportEvent(kind="done"))
        if self.friend._director_task:
            await asyncio.wait_for(asyncio.shield(self.friend._director_task), 1)
        self.assertEqual(cinema.started, [])
        self.assertEqual(self.images.calls, [])
        self.assertFalse(self.friend.film_active())

    async def test_easy_ask_does_not_keep_a_film_decision(self):
        cinema = StubCinema()
        self.friend._cinema = cinema
        self.friend.visual_director = FixedDirector(
            VisualDecision(route="film", subject="rocket")
        )
        await self.friend.handle(TextLine(text="How do you spell rocket?"))
        await self.friend._on_transport(TransportEvent(kind="transcript", text="R-O-C-K-E-T."))
        await self.friend._on_transport(TransportEvent(kind="done"))
        await asyncio.wait_for(asyncio.shield(self.friend._director_task), 1)
        self.assertEqual(cinema.started, [])
        await self.images.wait_for_calls(1)
        self.assertEqual(self.images.calls[0][0], "rocket")
        await self.finish_show()

    async def test_make_it_move_keeps_the_still_without_a_clip_or_film(self):
        cinema = StubCinema()
        self.friend._cinema = cinema
        await self.ask_show("jellyfish")
        await self.finish_show()
        still = self.friend.current_show
        director = FixedDirector(VisualDecision(route="animate", motion="bell pulses slowly"))
        self.friend.visual_director = director
        await self.friend.handle(TextLine(text="Make it move."))
        await self.friend._on_transport(TransportEvent(kind="transcript", text="The jellyfish is already there."))
        await self.friend._on_transport(TransportEvent(kind="done"))
        if self.friend._director_task:
            await asyncio.wait_for(asyncio.shield(self.friend._director_task), 1)
        self.assertEqual(cinema.started, [])
        self.assertIs(self.friend.current_show, still)
        self.assertNotIn("clip", self.friend.show_event() or {})
        self.assertFalse(self.friend.film_active())
        self.assertFalse(self.friend._suppress_live_output)

    async def test_ptt_stops_an_active_film(self):
        cinema = StubCinema()
        self.friend._cinema = cinema
        await self.friend._start_film("Why do rockets fly?")
        self.assertTrue(self.friend.film_active())
        await self.friend.handle(PushToTalk(active=True))
        if self.friend._ptt_open_task:
            await self.friend._ptt_open_task
        await self.friend.handle(PushToTalk(active=False))
        self.assertEqual(cinema.stopped, 1)
        self.assertFalse(self.friend.film_active())

    async def test_select_stops_film(self):
        cinema = StubCinema()
        self.friend._cinema = cinema
        await self.friend._start_film("Why do rockets fly?")
        await self.friend.handle(Select())
        self.assertEqual(cinema.stopped, 1)
        self.assertFalse(self.friend.film_active())

    async def test_desk_prefer_film_skips_the_still_director(self):
        cinema = StubCinema()
        self.friend._cinema = cinema
        self.friend._prefers_device_film = True
        director = FixedDirector(VisualDecision(route="still", subject="map"))
        self.friend.visual_director = director
        await self.friend.handle(TextLine(text="Why is the sky blue?"))
        await asyncio.wait_for(asyncio.shield(self.friend._director_task), 1)
        self.assertEqual(cinema.started, ["Why is the sky blue?"])
        self.assertEqual(director.calls, [])
        self.assertEqual(self.images.calls, [])

    async def test_device_film_carries_a_directed_brief(self):
        cinema = StubCinema()
        self.friend._cinema = cinema
        self.friend.visual_director = FixedDirector(
            VisualDecision(route="film", subject="rocket exhaust")
        )
        await self.friend.handle(TextLine(text="How does a rocket actually take off?"))
        await asyncio.wait_for(asyncio.shield(self.friend._director_task), 1)
        self.assertEqual(cinema.directions, ["How does a rocket actually take off?"])

    async def test_film_preparing_thinks_and_clears_the_glass(self):
        await self.ask_show("jellyfish")
        await self.finish_show()
        self.assertIsNotNone(self.friend.current_show)
        self.events()
        await self.friend._on_film_preparing()
        self.assertIsNone(self.friend.current_show)
        self.assertEqual(self.friend.machine.state, State.THINKING)
        self.assertIn(
            {"type": "glass", "viewing": False, "reason": "film", "text": "",
             "state": "thinking", "power": True, "screen": True,
             "transport": self.friend.transport_name},
            self.events(),
        )

    async def test_film_audio_moves_from_thinking_to_talking(self):
        await self.friend._on_film_preparing()
        self.assertEqual(self.friend.machine.state, State.THINKING)
        await self.friend._start_talking()
        self.assertEqual(self.friend.machine.state, State.TALKING)
        await self.friend._on_film_idle()
        self.assertEqual(self.friend.machine.state, State.LISTENING)
        self.assertFalse(self.friend._suppress_live_output)
