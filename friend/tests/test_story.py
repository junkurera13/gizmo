from __future__ import annotations

import unittest

from gizmo_friend.brain.narration import NARRATION_RATE, pcm_from_part
from gizmo_friend.brain.story import intent_from_payload, storyboard_from_payload, story_gate


class StoryGateTests(unittest.TestCase):
    def test_narrative_asks_pass(self):
        for line in [
            "tell me the story of pompeii",
            "what happened at chernobyl",
            "show me step by step how volcanoes form with clips",
            "once upon a time there was a fox, keep going",
        ]:
            self.assertTrue(story_gate(line), line)

    def test_ordinary_questions_do_not_pay_for_a_scout(self):
        for line in ["how far is the moon", "what's a black hole", "tell me about tigers", "I'm bored"]:
            self.assertFalse(story_gate(line), line)


class IntentParsingTests(unittest.TestCase):
    def test_begin_needs_a_premise(self):
        self.assertEqual(intent_from_payload({"route": "begin", "premise": ""}, story_active=False).route, "none")
        intent = intent_from_payload(
            {"route": "begin", "premise": "the eruption of Vesuvius in 79 AD", "opener": "Right. Pompeii."},
            story_active=False,
        )
        self.assertEqual((intent.route, intent.opener), ("begin", "Right. Pompeii."))

    def test_story_routes_need_a_running_story(self):
        for route in ["continue", "steer", "question", "leave"]:
            self.assertEqual(intent_from_payload({"route": route}, story_active=False).route, "none")
            self.assertEqual(intent_from_payload({"route": route}, story_active=True).route, route)

    def test_garbage_is_none(self):
        self.assertEqual(intent_from_payload(None, story_active=True).route, "none")
        self.assertEqual(intent_from_payload({"route": "explode"}, story_active=True).route, "none")


class StoryboardParsingTests(unittest.TestCase):
    def test_beats_are_cleaned_and_bounded(self):
        board = storyboard_from_payload({
            "title": "Pompeii",
            "setting": "  Roman  Bay of Naples ",
            "character": "",
            "beats": [
                {"narration": "Morning.\n\nThe bakers are up.", "scene": "a bakery", "motion": "smoke rising"},
                {"narration": "", "scene": "skipped"},
                "junk",
            ] + [{"narration": f"beat {n}", "scene": "x", "motion": ""} for n in range(6)],
            "remaining": "the eruption itself",
            "finished": "yes",
        }, beats=3)
        self.assertEqual(board.beats[0].narration, "Morning. The bakers are up.")
        self.assertEqual(board.setting, "roman bay of naples")
        self.assertEqual(len(board.beats), 3)  # first 5 considered, two rejected
        self.assertFalse(board.finished)
        self.assertEqual(board.remaining, "the eruption itself")

    def test_running_character_wins_over_a_new_description(self):
        board = storyboard_from_payload(
            {"beats": [{"narration": "a", "scene": "b", "motion": ""}], "character": "a fox in a red cap"},
            beats=3, current_character="a fox with one white ear",
        )
        self.assertEqual(board.character, "a fox with one white ear")

    def test_no_usable_beats_is_none(self):
        self.assertIsNone(storyboard_from_payload({"beats": []}, beats=3))
        self.assertIsNone(storyboard_from_payload({"beats": "nope"}, beats=3))


class NarrationPcmTests(unittest.TestCase):
    def test_native_rate_passes_through(self):
        pcm = b"\x01\x00" * 480
        self.assertEqual(pcm_from_part("audio/L16;codec=pcm;rate=24000", pcm), pcm)

    def test_other_rates_resample_to_the_wire_rate(self):
        source = b"\x00\x10" * 4800  # 0.1 s at 48 kHz
        out = pcm_from_part("audio/L16;rate=48000", source)
        self.assertAlmostEqual(len(out) / 2 / NARRATION_RATE, 0.1, places=2)

    def test_odd_byte_is_trimmed_and_non_pcm_rejected(self):
        self.assertEqual(len(pcm_from_part("audio/pcm;rate=24000", b"\x00" * 7)), 6)
        with self.assertRaises(ValueError):
            pcm_from_part("audio/mpeg", b"\x00" * 10)


if __name__ == "__main__":
    unittest.main()
