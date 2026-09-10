from __future__ import annotations

import unittest

from gizmo_friend.brain.images import SCENE_ADDENDUM, DIAGRAM_ADDENDUM, still_instruction
from gizmo_friend.brain.visual_director import (
    VisualDecision,
    decision_from_payload,
    is_bare_animate_request,
    is_explicit_film_request,
    is_explicit_visual_request,
)
from gizmo_friend.transport.gemini_live import live_config


class VisualDecisionTests(unittest.TestCase):
    def test_invalid_or_incomplete_decisions_degrade_without_spending(self):
        self.assertEqual(decision_from_payload(None, has_visual=False), VisualDecision())
        self.assertEqual(
            decision_from_payload(
                {"route": "motion", "subject": "earth layers", "motion": "none"},
                has_visual=False,
            ),
            VisualDecision(route="still", subject="earth layers"),
        )
        self.assertEqual(
            decision_from_payload(
                {"route": "motion", "subject": "rocket", "motion": ""},
                has_visual=False,
            ),
            VisualDecision(route="still", subject="rocket"),
        )

    def test_animate_requires_an_existing_visual_and_motion(self):
        payload = {"route": "animate", "subject": "ignored", "motion": "tentacles drift"}
        self.assertEqual(decision_from_payload(payload, has_visual=False), VisualDecision())
        self.assertEqual(
            decision_from_payload(payload, has_visual=True),
            VisualDecision(route="animate", motion="tentacles drift"),
        )

    def test_only_bare_animate_requests_are_locally_silent(self):
        for utterance in ("Make it move.", "please animate it", "Move it, please!"):
            self.assertTrue(is_bare_animate_request(utterance))
        for utterance in ("Make it move and explain why.", "Can it move?", "Move it to the left"):
            self.assertFalse(is_bare_animate_request(utterance))

    def test_only_explicit_standalone_visuals_can_start_before_voice(self):
        for utterance in ("Show me a volcano.", "Can you draw a jellyfish?", "Make a short video of a rocket."):
            self.assertTrue(is_explicit_visual_request(utterance))
        for utterance in ("Tell me a story about a fox.", "Show me the next story chapter.", "Then what?", "Why is the sky blue?"):
            self.assertFalse(is_explicit_visual_request(utterance))

    def test_film_requests_are_not_generic_short_videos(self):
        for utterance in (
            "Show me a film about how rockets work.",
            "Make a movie explaining orbit.",
            "A cinematic explanation of the heart.",
            "Explain this with a video.",
        ):
            self.assertTrue(is_explicit_film_request(utterance))
        for utterance in (
            "Make a short video of a jellyfish.",
            "Animate it.",
            "Show me a volcano.",
            "Tell me a story about a fox.",
        ):
            self.assertFalse(is_explicit_film_request(utterance))

    def test_film_route_is_accepted_and_never_used_for_stories(self):
        self.assertEqual(
            decision_from_payload(
                {"route": "film", "subject": "rocket exhaust", "motion": ""},
                has_visual=False,
            ),
            VisualDecision(route="film", subject="rocket exhaust"),
        )
        self.assertEqual(
            decision_from_payload(
                {
                    "route": "film",
                    "subject": "castle at dusk",
                    "motion": "clouds drift",
                    "story_setting": "castle",
                },
                has_visual=False,
            ).route,
            "still",
        )
    def test_stories_are_scenes_even_if_the_model_asks_for_a_diagram(self):
        payload = {
            "route": "motion", "subject": "submarine on the ocean floor",
            "motion": "bubbles rise", "story_setting": "ocean floor", "kind": "diagram",
        }
        self.assertEqual(decision_from_payload(payload, has_visual=False).kind, "scene")
        payload = {
            "route": "still", "subject": "heart chambers", "motion": "",
            "story_setting": "", "kind": "diagram",
        }
        self.assertEqual(decision_from_payload(payload, has_visual=False).kind, "diagram")
        payload["kind"] = "scene"
        self.assertEqual(decision_from_payload(payload, has_visual=False).kind, "scene")

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
        self.assertEqual(names, {"deep_think", "set_expression"})


if __name__ == "__main__":
    unittest.main()
