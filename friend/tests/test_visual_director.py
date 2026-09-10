from __future__ import annotations

import unittest

from gizmo_friend.brain.images import SCENE_ADDENDUM, DIAGRAM_ADDENDUM, still_instruction
from gizmo_friend.brain.visual_director import (
    VisualDecision,
    decision_from_payload,
    is_bare_animate_request,
    is_explicit_visual_request,
    is_moving_explanation_ask,
    prefer_film_route,
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

    def test_animate_payload_stays_words(self):
        payload = {"route": "animate", "subject": "ignored", "motion": "tentacles drift"}
        self.assertEqual(decision_from_payload(payload, has_visual=False), VisualDecision())
        self.assertEqual(decision_from_payload(payload, has_visual=True), VisualDecision())

    def test_bare_make_it_move_is_not_a_moving_explanation(self):
        for utterance in ("Make it move.", "please animate it", "Move it, please!"):
            self.assertTrue(is_bare_animate_request(utterance))
        for utterance in ("Make it move and explain why.", "Can it move?", "Move it to the left"):
            self.assertFalse(is_bare_animate_request(utterance))

    def test_only_explicit_standalone_visuals_can_start_before_voice(self):
        for utterance in ("Show me a volcano.", "Can you draw a jellyfish?", "Make a short video of a rocket."):
            self.assertTrue(is_explicit_visual_request(utterance))
        for utterance in ("Tell me a story about a fox.", "Show me the next story chapter.", "Then what?", "Why is the sky blue?"):
            self.assertFalse(is_explicit_visual_request(utterance))

    def test_moving_explanations_are_gated_by_difficulty_not_vocabulary(self):
        for utterance in (
            "How does a rocket actually take off?",
            "What happens when ice melts?",
            "Why is the sky blue?",
            "Why do rockets fly?",
            "How does a heart pump blood?",
            "Explain how rain forms.",
            "Show me how the Moon orbits.",
            "How do airplanes stay up?",
        ):
            self.assertTrue(is_moving_explanation_ask(utterance), utterance)
        for utterance in (
            "Hi.",
            "Tell me a joke.",
            "How are you?",
            "I'm sad.",
            "Make it move.",
            "Show me a volcano.",
            "Make a short video of a jellyfish.",
            "Make a cinematic film of a rocket.",
            "Where was the Silk Road?",
            "What does a trilobite look like?",
            "What color is the sky?",
            "How do you spell rocket?",
            "Tell me a story about a fox.",
            "How old is the Moon?",
            "How many hearts does an octopus have?",
        ):
            self.assertFalse(is_moving_explanation_ask(utterance), utterance)

    def test_cinema_is_only_for_hard_asks_and_moving_story_scenes(self):
        motion = VisualDecision(route="motion", subject="rocket", motion="it lifts")
        self.assertEqual(
            prefer_film_route(motion, "How does a rocket actually take off?").route,
            "film",
        )
        self.assertEqual(
            prefer_film_route(
                VisualDecision(route="still", subject="rocket"),
                "Why do rockets fly?",
            ).route,
            "film",
        )
        self.assertEqual(
            prefer_film_route(motion, "Make a short video of a jellyfish.").route,
            "still",
        )
        self.assertEqual(
            prefer_film_route(
                VisualDecision(route="film", subject="rocket"),
                "Hi.",
            ).route,
            "still",
        )
        self.assertEqual(
            prefer_film_route(
                VisualDecision(route="still", subject="Silk Road map"),
                "Where was the Silk Road?",
            ).route,
            "still",
        )
        self.assertEqual(
            prefer_film_route(
                VisualDecision(route="still", subject="rocket"),
                "How do you spell rocket?",
            ).route,
            "still",
        )
        story = prefer_film_route(
            VisualDecision(route="motion", subject="castle", motion="clouds drift", story_setting="castle"),
            "Then what?",
        )
        self.assertEqual(story.route, "film")
        self.assertEqual(story.story_setting, "castle")
        self.assertEqual(
            prefer_film_route(
                VisualDecision(route="still", subject="castle", story_setting="castle"),
                "How does a rocket work?",
            ).route,
            "still",
        )
        self.assertEqual(
            prefer_film_route(
                VisualDecision(route="animate", motion="bell pulses"),
                "Make it move.",
            ).route,
            "words",
        )

    def test_film_route_is_accepted_for_explanations_and_story_scenes(self):
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
            "film",
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
