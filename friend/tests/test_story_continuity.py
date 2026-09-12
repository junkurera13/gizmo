"""Story continuity across turns under the single per-turn director.

The director judges the ask, not the answer. What survives from the old story
contract: a setting attaches when its picture lands, a character anchor keeps
one identity across settings until a new story, and finished answers feed the
next judgment as bounded dialogue.
"""

from __future__ import annotations

import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from gizmo_friend.body_protocol import TextLine
from gizmo_friend.brain.visual_director import (
    DialogueTurn,
    GeminiVisualDirector,
    MAX_CONTEXT_TEXT,
    MAX_CONTEXT_TURNS,
    VisualDecision,
    decision_from_payload,
)
from gizmo_friend.transport.base import TransportEvent
from test_motion_session import ControlledDirector, FixedDirector, ShowSessionFixture


class StoryContinuityTests(ShowSessionFixture):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.director = FixedDirector(VisualDecision())
        self.friend.visual_director = self.director

    async def finish_answer(self, text):
        await self.friend._on_transport(TransportEvent(kind="transcript", text=text))
        await self.friend._on_transport(TransportEvent(kind="done"))

    async def finish_turn(self, text):
        """One typed ask: the judgment commits, then the held voice answer plays."""
        await self.friend.handle(TextLine(text=text))
        await asyncio.wait_for(asyncio.shield(self.friend._director_task), 1)

    async def test_character_anchor_survives_scene_change_and_resets_for_new_story(self):
        async def chapter(setting, character, new_story=False):
            self.director.decision = VisualDecision(
                route="still", subject=setting, story_setting=setting,
                story_character=character, new_story=new_story,
            )
            await self.finish_turn("Continue the story.")
            await self.finish_answer(f"The little fox was now exploring the {setting}.")
            await self.images.wait_for_calls(chapter.finished + 1)
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

    async def test_completed_answers_feed_the_next_judgment(self):
        await self.finish_turn("Tell me about a clockwork fox in a castle.")
        self.assertEqual(self.director.calls, [("Tell me about a clockwork fox in a castle.", False, "")])
        await self.finish_answer("Copper lived in a castle.")
        await self.finish_turn("Then what?")
        history = self.director.contexts[-1]["recent_dialogue"]
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].utterance, "Tell me about a clockwork fox in a castle.")
        self.assertEqual(history[0].narration, "Copper lived in a castle.")
        # A repeated completion must not append the turn twice.
        await self.friend._on_transport(TransportEvent(kind="done"))
        self.assertEqual(len(self.friend._visual_history), 1)

    async def test_cancelled_answer_feeds_nothing_forward(self):
        await self.finish_turn("Tell me a castle story.")
        await self.friend._on_transport(TransportEvent(kind="transcript", text="Unfinished castle chapter."))
        await self.friend._on_transport(TransportEvent(kind="cancelled"))
        self.assertEqual(list(self.friend._visual_history), [])
        await self.finish_turn("Tell me another story.")
        self.assertEqual(self.director.contexts[-1]["recent_dialogue"], ())

    async def test_new_ask_cancels_a_pending_judgment(self):
        director = ControlledDirector()
        self.friend.visual_director = director
        await self.friend.handle(TextLine(text="Take Copper underwater."))
        await director.wait_for_calls(1)
        task = self.friend._director_task
        self.assertFalse(task.done())
        await self.friend.handle(TextLine(text="Never mind. Tell me a joke."))
        await asyncio.gather(task, return_exceptions=True)
        self.assertTrue(task.cancelled())
        self.assertEqual(self.images.calls, [])

    async def test_setting_is_attached_only_when_its_picture_arrives(self):
        self.director.decision = VisualDecision(route="still", subject="castle armory", story_setting="castle")
        await self.finish_turn("Tell me a story.")
        await self.images.wait_for_calls(1)
        self.assertEqual(self.friend.current_story_setting, "")
        await self.finish_show()
        self.assertEqual(self.friend.current_story_setting, "castle")
        self.assertEqual(self.images.kinds, ["scene"])
        await self.friend._dismiss_show("test")
        self.assertEqual(self.friend.current_story_setting, "")

    async def test_history_is_bounded_and_cold_boot_clears_it(self):
        for index in range(MAX_CONTEXT_TURNS + 2):
            await self.finish_turn(f"Then what {index}?")
            await self.finish_answer("x" * (MAX_CONTEXT_TEXT + 10))
        self.assertEqual(len(self.friend._visual_history), MAX_CONTEXT_TURNS)
        self.assertTrue(all(len(turn.narration) == MAX_CONTEXT_TEXT for turn in self.friend._visual_history))
        await self.friend.on_power(False)
        await self.friend.on_power(True)
        self.assertEqual(list(self.friend._visual_history), [])
        self.assertFalse(self.friend._visual_turn_open)

    async def test_words_decision_leaves_the_show_alone(self):
        await self.ask_show("jellyfish")
        await self.finish_show()
        still = self.friend.current_show
        await self.finish_turn("Make it move.")
        await self.finish_answer("The jellyfish is already there.")
        self.assertIs(self.friend.current_show, still)
        self.assertFalse(self.friend.film_active())


class DecisionValidationTests(unittest.IsolatedAsyncioTestCase):
    def test_same_setting_overrules_a_redundant_model_redraw(self):
        payload = {"route": "still", "subject": "castle courtyard", "story_setting": "castle"}
        self.assertEqual(
            decision_from_payload(payload, has_visual=True, current_story_setting="castle").route,
            "words",
        )
        self.assertEqual(
            decision_from_payload(payload, has_visual=False, current_story_setting="castle").route,
            "still",
        )
        payload["redraw_requested"] = True
        self.assertEqual(
            decision_from_payload(payload, has_visual=True, current_story_setting="castle").route,
            "still",
        )
        # A separate new story in the same place may redraw.
        payload["redraw_requested"] = False
        payload["new_story"] = True
        self.assertEqual(
            decision_from_payload(payload, has_visual=True, current_story_setting="castle").route,
            "still",
        )
        # The reuse guard is for stills; a film judgment is never downgraded.
        payload = {"route": "film", "subject": "the drawbridge lowers", "story_setting": "castle"}
        self.assertEqual(
            decision_from_payload(payload, has_visual=True, current_story_setting="castle").route,
            "film",
        )

    def test_missing_subject_and_unknown_routes_become_words(self):
        for route in ("still", "film"):
            self.assertEqual(decision_from_payload({"route": route}, has_visual=False).route, "words")
        self.assertEqual(decision_from_payload({"route": "animate"}, has_visual=False).route, "words")
        self.assertEqual(decision_from_payload("not json", has_visual=False).route, "words")

    def test_thread_and_character_validate(self):
        decision = decision_from_payload(
            {"route": "still", "subject": "fox den", "thread": "bogus", "story_setting": "forest",
             "story_character": "Fen"},
            has_visual=False,
        )
        self.assertEqual(decision.thread, "new")
        self.assertEqual(decision.story_character, "Fen")
        # A character without a story setting never reaches the picture.
        decision = decision_from_payload(
            {"route": "still", "subject": "fox", "story_character": "Fen"},
            has_visual=False,
        )
        self.assertEqual(decision.story_character, "")
        # new_story without a setting is meaningless and ignored.
        decision = decision_from_payload(
            {"route": "still", "subject": "fox", "new_story": True},
            has_visual=False,
        )
        self.assertFalse(decision.new_story)

    async def test_provider_receives_bounded_dialogue_and_current_medium(self):
        generate = AsyncMock(return_value='{"route": "words"}')
        director = GeminiVisualDirector.__new__(GeminiVisualDirector)
        director.model = "fixture"
        director._client = SimpleNamespace(complete=generate)
        await director.decide(
            "Then what?", has_visual=True, current_subject="castle",
            current_medium="film", current_story_setting="castle",
            recent_dialogue=tuple(DialogueTurn(str(i), "x" * 3000) for i in range(20)),
        )
        payload = json.loads(generate.call_args.args[1])
        self.assertEqual(payload["current_medium"], "film")
        self.assertEqual(payload["current_story_setting"], "castle")
        self.assertEqual(payload["current_subject"], "castle")
        self.assertEqual(len(payload["recent_dialogue"]), MAX_CONTEXT_TURNS)
        self.assertTrue(all(len(turn["narration"]) == MAX_CONTEXT_TEXT for turn in payload["recent_dialogue"]))


if __name__ == "__main__":
    unittest.main()
