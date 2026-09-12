from __future__ import annotations

import inspect
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from gizmo_friend.brain.images import DIAGRAM_ADDENDUM, SCENE_ADDENDUM, still_instruction
from gizmo_friend.brain.visual_director import (
    DIRECTOR_INSTRUCTIONS,
    DIRECTOR_SCHEMA,
    DialogueTurn,
    GeminiVisualDirector,
    MAX_CONTEXT_TEXT,
    MAX_CONTEXT_TURNS,
    VisualDecision,
    decision_from_payload,
)
from gizmo_friend.transport.gemini_live import live_config


def payload(route="words", subject="", **updates):
    value = {
        "route": route,
        "subject": subject,
        "thread": "new",
        "story_setting": "",
        "redraw_requested": False,
        "kind": "scene",
        "story_character": "",
        "new_story": False,
    }
    value.update(updates)
    return value


class VisualDecisionTests(unittest.TestCase):
    def test_only_talk_still_and_film_are_valid_routes(self):
        self.assertEqual(DIRECTOR_SCHEMA["properties"]["route"]["enum"], ["words", "still", "film"])
        self.assertEqual(decision_from_payload(None, has_visual=False), VisualDecision())
        for invalid in ("motion", "animate", "video", ""):
            self.assertEqual(
                decision_from_payload(payload(invalid, "rocket"), has_visual=False),
                VisualDecision(),
            )

    def test_model_judgment_is_authoritative(self):
        self.assertEqual(
            decision_from_payload(payload("words"), has_visual=False).route,
            "words",
        )
        self.assertEqual(
            decision_from_payload(payload("still", "rocket"), has_visual=False),
            VisualDecision(route="still", subject="rocket"),
        )
        self.assertEqual(
            decision_from_payload(payload("film", "rocket launch"), has_visual=False),
            VisualDecision(route="film", subject="rocket launch"),
        )

    def test_missing_subject_fails_open_to_talk(self):
        for route in ("still", "film"):
            self.assertEqual(
                decision_from_payload(payload(route), has_visual=False),
                VisualDecision(),
            )

    def test_thread_and_story_identity_are_normalized(self):
        decision = decision_from_payload(
            payload(
                "film",
                "Fen reaches the ocean floor",
                thread="continue",
                story_setting="Ocean   Floor",
                story_character="Fen, small fox, violet scarf",
            ),
            has_visual=False,
        )
        self.assertEqual(decision.thread, "continue")
        self.assertEqual(decision.story_setting, "ocean floor")
        self.assertEqual(decision.story_character, "Fen, small fox, violet scarf")

    def test_same_story_still_reuse_is_an_operational_guard(self):
        same = payload("still", "castle courtyard", story_setting="castle")
        self.assertEqual(
            decision_from_payload(same, has_visual=True, current_story_setting="castle").route,
            "words",
        )
        same["redraw_requested"] = True
        self.assertEqual(
            decision_from_payload(same, has_visual=True, current_story_setting="castle").route,
            "still",
        )

    def test_stories_are_scenes_and_non_story_diagrams_are_allowed(self):
        story = payload("still", "submarine", story_setting="ocean floor", kind="diagram")
        self.assertEqual(decision_from_payload(story, has_visual=False).kind, "scene")
        diagram = payload("still", "heart chambers", kind="diagram")
        self.assertEqual(decision_from_payload(diagram, has_visual=False).kind, "diagram")

    def test_no_semantic_regex_router_remains(self):
        source = inspect.getsource(__import__(
            "gizmo_friend.brain.visual_director", fromlist=["visual_director"]
        ))
        self.assertNotIn("is_moving_explanation_ask", source)
        self.assertNotIn("is_explicit_visual_request", source)
        self.assertNotIn("prefer_film_route", source)
        self.assertIn("Never use a keyword or phrase as an automatic trigger", DIRECTOR_INSTRUCTIONS)

    def test_scene_instructions_forbid_text_and_diagrams_allow_labels(self):
        scene = still_instruction("scene")
        diagram = still_instruction("diagram")
        self.assertIn(SCENE_ADDENDUM, scene)
        self.assertNotIn(DIAGRAM_ADDENDUM, scene)
        self.assertIn(DIAGRAM_ADDENDUM, diagram)
        self.assertNotIn(SCENE_ADDENDUM, diagram)

    def test_live_voice_cannot_make_a_competing_visual_choice(self):
        config = live_config("test")
        tools = config.model_dump(mode="json", exclude_none=True)["tools"]
        names = {
            declaration["name"]
            for tool in tools
            for declaration in tool.get("function_declarations", [])
        }
        self.assertEqual(names, {"deep_think"})


class DirectorContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_provider_receives_bounded_context_and_current_medium(self):
        generate = AsyncMock(return_value=json.dumps(payload("words", thread="continue")))
        director = GeminiVisualDirector.__new__(GeminiVisualDirector)
        director.model = "fixture"
        director._client = SimpleNamespace(complete=generate)
        decision = await director.decide(
            "And then?",
            has_visual=True,
            current_subject="rocket launch",
            current_medium="film",
            recent_dialogue=tuple(DialogueTurn(str(i), "x" * 3000) for i in range(20)),
        )
        request = json.loads(generate.call_args.args[1])
        self.assertEqual(decision.thread, "continue")
        self.assertEqual(request["current_medium"], "film")
        self.assertEqual(request["current_subject"], "rocket launch")
        self.assertEqual(len(request["recent_dialogue"]), MAX_CONTEXT_TURNS)
        self.assertTrue(
            all(len(turn["narration"]) == MAX_CONTEXT_TEXT for turn in request["recent_dialogue"])
        )


if __name__ == "__main__":
    unittest.main()
