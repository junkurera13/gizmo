from __future__ import annotations

import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from gizmo_friend.body_protocol import TextLine
from gizmo_friend.brain.visual_director import (
    DialogueTurn,
    FalVisualDirector,
    MAX_CONTEXT_TEXT,
    MAX_CONTEXT_TURNS,
    VisualDecision,
    decision_from_payload,
    opening_narration,
)
from gizmo_friend.transport.base import TransportEvent
from test_motion_session import FixedDirector, ShowSessionFixture


class StoryContinuityTests(ShowSessionFixture):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.director = FixedDirector(VisualDecision())
        self.friend.visual_director = self.director

    async def finish_narration(self, text):
        await self.friend._on_transport(TransportEvent(kind="transcript", text=text))
        await self.friend._on_transport(TransportEvent(kind="done"))
        if self.friend._director_task:
            await self.friend._director_task

    async def test_character_anchor_survives_scene_change_and_resets_for_new_story(self):
        async def chapter(setting, character, new_story=False):
            self.director.decision = VisualDecision(
                route="still", subject=setting, story_setting=setting,
                story_character=character, new_story=new_story,
            )
            await self.friend.handle(TextLine(text="Continue the story."))
            await self.finish_narration(f"The little fox was now exploring the {setting}.")
            async with asyncio.timeout(1):
                while len(self.images.calls) <= chapter.finished:
                    await asyncio.sleep(0.001)
            await self.finish_show()
            chapter.finished += 1
        chapter.finished = 0
        identity = "Fen, small fox, large triangular ears, pink tail tip, violet scarf"
        await chapter("forest", identity, True)
        anchor = self.friend._character_reference
        self.assertIsNotNone(anchor)
        self.assertEqual(self.images.identities[0], (identity, None))
        await self.friend._dismiss_show("select")
        await chapter("submarine", "accidental different model description")
        self.assertEqual(self.images.identities[1], (identity, anchor))
        self.assertIs(self.friend._character_reference, anchor)
        await chapter("forest", "Pip, tiny owl with round glasses", True)
        self.assertEqual(self.images.identities[2], ("Pip, tiny owl with round glasses", None))

    async def test_director_reads_actual_chapter_and_prior_edit_once(self):
        await self.friend.handle(TextLine(text="Tell me about a clockwork fox in a castle."))
        await asyncio.sleep(0)
        self.assertEqual(self.director.calls, [])
        await self.friend._on_transport(TransportEvent(kind="transcript", text="Copper lived in a castle."))
        self.assertEqual(self.director.calls, [])
        await self.friend._on_transport(TransportEvent(kind="transcript", text="His brass ear heard a bell."))
        await self.friend._on_transport(TransportEvent(kind="done"))
        await self.friend._director_task
        first = "Copper lived in a castle. His brass ear heard a bell."
        self.assertEqual(self.director.contexts[0], (first, ()))

        await self.friend.handle(TextLine(text="Actually, he is afraid of bells."))
        await self.finish_narration("Copper hid beneath the castle stairs when it rang.")
        await self.friend.handle(TextLine(text="Then what?"))
        await self.finish_narration("Copper left the castle and reached a moonlit forest.")
        narration, history = self.director.contexts[-1]
        self.assertIn("moonlit forest", narration)
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0].narration, first)
        self.assertIn("afraid of bells", history[1].utterance)
        # A repeated completion must not direct or append the chapter twice.
        await self.friend._on_transport(TransportEvent(kind="done"))
        self.assertEqual(len(self.director.calls), 3)
        self.assertEqual(len(self.friend._visual_history), 3)

    async def test_voice_transcription_can_arrive_after_narration(self):
        self.friend._ask_revision += 1
        self.friend._begin_visual_turn("")
        await self.friend._on_transport(TransportEvent(kind="transcript", text="Copper entered the forest."))
        await self.friend._on_transport(TransportEvent(kind="user_transcript", text="Take him into the forest."))
        await self.friend._on_transport(TransportEvent(kind="done"))
        await self.friend._director_task
        self.assertEqual(self.director.calls[0][0], "Take him into the forest.")
        self.assertEqual(self.director.contexts[0][0], "Copper entered the forest.")

    async def test_streamed_opening_directs_before_chapter_finishes(self):
        await self.friend.handle(TextLine(text="Take Copper underwater."))
        await self.friend._on_transport(TransportEvent(kind="transcript_delta", text="On the ocean floor, Copper's submarine"))
        self.assertEqual(self.director.calls, [])
        opening = "On the ocean floor, Copper's submarine rested beside a reef."
        await self.friend._on_transport(TransportEvent(kind="transcript_delta", text=" rested beside a reef. "))
        await self.friend._director_task
        self.assertEqual(self.director.contexts, [(opening, ())])
        await self.finish_narration(opening + " Tremor heard a bell outside.")
        self.assertEqual(len(self.director.calls), 1)
        self.assertIn("bell outside", self.friend._visual_history[-1].narration)

    async def test_deferred_story_rechecks_completed_narration_without_duplicate_media(self):
        calls = []

        async def decide(utterance, **context):
            calls.append(context)
            if not context["narration_complete"]:
                return VisualDecision(follow_narration=True)
            return VisualDecision(route="still", subject="ocean floor")

        self.friend.visual_director.decide = decide
        await self.friend.handle(TextLine(text="Take Copper underwater."))
        opening = "Copper and the dragon found a drain below the castle."
        await self.friend._on_transport(TransportEvent(kind="transcript_delta", text=opening))
        await asyncio.sleep(0)
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.images.calls, [])
        await self.friend._on_transport(TransportEvent(kind="transcript", text=opening + " They reached the ocean floor in a submarine."))
        await self.friend._on_transport(TransportEvent(kind="done"))
        await self.friend._director_task
        await self.images.wait_for_calls(1)
        await self.finish_show()
        self.assertEqual(len(calls), 2)
        self.assertTrue(calls[1]["narration_complete"])
        self.assertIn("ocean floor", calls[1]["narration"])
        self.assertEqual(calls[0]["recent_dialogue"], calls[1]["recent_dialogue"])
        self.assertEqual(len(self.images.calls), 1)

    async def test_new_ask_cancels_a_story_waiting_for_its_ending(self):
        self.director.decision = VisualDecision(follow_narration=True)
        await self.friend.handle(TextLine(text="Take Copper underwater."))
        await self.friend._on_transport(TransportEvent(kind="transcript_delta", text="Copper and the dragon found a drain below the castle."))
        task = self.friend._director_task
        await asyncio.sleep(0)
        self.assertFalse(task.done())
        await self.friend.handle(TextLine(text="Never mind. Tell me a joke."))
        await asyncio.gather(task, return_exceptions=True)
        self.assertTrue(task.cancelled())
        self.assertEqual(self.images.calls, [])

    async def test_setting_is_attached_only_when_its_picture_arrives(self):
        self.director.decision = VisualDecision(route="still", subject="castle armory", story_setting="castle")
        await self.friend.handle(TextLine(text="Tell me a story."))
        await self.finish_narration("Copper lives in a castle.")
        await self.images.wait_for_calls(1)
        self.assertEqual(self.friend.current_story_setting, "")
        await self.finish_show()
        self.assertEqual(self.friend.current_story_setting, "castle")
        self.assertEqual(self.images.kinds, ["scene"])
        await self.friend._dismiss_show("test")
        self.assertEqual(self.friend.current_story_setting, "")

    async def test_cancelled_or_missing_narration_cannot_invent_a_scene(self):
        await self.friend.handle(TextLine(text="Tell me a castle story."))
        await self.friend._on_transport(TransportEvent(kind="transcript", text="An unfinished castle chapter."))
        await self.friend._on_transport(TransportEvent(kind="cancelled"))
        await self.friend._on_transport(TransportEvent(kind="done"))
        await self.friend.handle(TextLine(text="Tell me another story."))
        await self.friend._on_transport(TransportEvent(kind="done"))
        self.assertEqual(self.director.calls, [])
        self.assertEqual(list(self.friend._visual_history), [])
        self.assertEqual(self.images.calls, [])

    async def test_new_ask_discards_unfinished_chapter_context(self):
        await self.friend.handle(TextLine(text="Tell me a castle story."))
        await self.friend._on_transport(TransportEvent(kind="transcript", text="Unfinished castle chapter."))
        await self.friend.handle(TextLine(text="What is six times seven?"))
        await self.finish_narration("Forty-two.")
        self.assertEqual(self.director.contexts, [("Forty-two.", ())])
        self.assertEqual(self.images.calls, [])

    async def test_history_is_bounded_and_cold_boot_clears_it(self):
        for index in range(MAX_CONTEXT_TURNS + 2):
            await self.friend.handle(TextLine(text=f"Then what {index}?"))
            await self.finish_narration("x" * (MAX_CONTEXT_TEXT + 10))
        self.assertEqual(len(self.friend._visual_history), MAX_CONTEXT_TURNS)
        self.assertTrue(all(len(turn.narration) == MAX_CONTEXT_TEXT for turn in self.friend._visual_history))
        await self.friend.on_power(False)
        await self.friend.on_power(True)
        self.assertEqual(list(self.friend._visual_history), [])
        self.assertFalse(self.friend._visual_turn_open)

    async def test_make_it_move_does_not_start_a_film_or_clip(self):
        await self.ask_show("jellyfish")
        await self.finish_show()
        still = self.friend.current_show
        await self.friend.handle(TextLine(text="Make it move."))
        await self.finish_narration("The jellyfish is already there.")
        self.assertIs(self.friend.current_show, still)
        self.assertNotIn("clip", self.friend.show_event() or {})
        self.assertFalse(self.friend.film_active())


class DirectorContextTests(unittest.IsolatedAsyncioTestCase):
    def test_only_provisional_story_words_wait_for_narration(self):
        payload = {"route": "words", "story_setting": "castle"}
        self.assertTrue(decision_from_payload(payload, has_visual=True, narration_complete=False).follow_narration)
        self.assertFalse(decision_from_payload(payload, has_visual=True, narration_complete=True).follow_narration)
        for payload in ({"route": "words"}, {"route": "invalid", "story_setting": "castle"}):
            self.assertFalse(decision_from_payload(payload, has_visual=True, narration_complete=False).follow_narration)

    def test_same_setting_overrules_a_redundant_model_redraw(self):
        payload = {"route": "motion", "subject": "castle courtyard", "motion": "clouds drift", "story_setting": "castle"}
        self.assertEqual(decision_from_payload(payload, has_visual=True, current_story_setting="castle").route, "words")
        self.assertEqual(decision_from_payload(payload, has_visual=False, current_story_setting="castle").route, "film")
        payload["redraw_requested"] = True
        self.assertEqual(decision_from_payload(payload, has_visual=True, current_story_setting="castle").route, "film")
        payload["redraw_requested"] = False
        payload["story_setting"] = "ocean floor"
        self.assertEqual(decision_from_payload(payload, has_visual=True, current_story_setting="castle").route, "film")

    def test_sentence_boundary_waits_for_more_than_a_short_acknowledgement(self):
        self.assertEqual(opening_narration("Right. Copper went"), "")
        text = "Right. Copper entered the underwater city. Another sentence."
        self.assertEqual(opening_narration(text), "Right. Copper entered the underwater city.")

    async def test_provider_receives_bounded_dialogue_and_current_narration(self):
        generate = AsyncMock(return_value='{"route": "words"}')
        director = FalVisualDirector.__new__(FalVisualDirector)
        director.model = "fixture"
        director._client = SimpleNamespace(complete=generate)
        await director.decide(
            "Then what?", has_visual=True, current_subject="castle",
            narration="He enters a forest.",
            recent_dialogue=tuple(DialogueTurn(str(i), "x" * 3000) for i in range(20)),
        )
        payload = json.loads(generate.call_args.args[1])
        self.assertEqual(payload["narration"], "He enters a forest.")
        self.assertEqual(payload["current_subject"], "castle")
        self.assertEqual(len(payload["recent_dialogue"]), MAX_CONTEXT_TURNS)
        self.assertTrue(all(len(turn["narration"]) == MAX_CONTEXT_TEXT for turn in payload["recent_dialogue"]))
