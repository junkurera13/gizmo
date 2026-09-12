from __future__ import annotations

import json
import tempfile
import unittest
import wave
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from gizmo_friend.brain.memory import NullMemoryProvider
from gizmo_friend.oddity.moments import ORDER, catalog, lookup
from gizmo_friend.oddity.runtime import ExperienceSession
from test_oddity import FakeCinema, FakeDirector, FakeImages, beat


class MomentCatalogTests(unittest.TestCase):
    def test_refreshed_audio_matches_caption_and_visual_timeline(self):
        static = Path(__file__).resolve().parents[1] / 'gizmo_friend' / 'static'
        for item in catalog():
            demo = item['demo']
            replies = [demo, demo.get('followup', {})]
            for reply in replies:
                if not reply.get('reply_timed'):
                    continue
                with wave.open(str(static / reply['reply_audio'].split('/')[-1].split('?')[0])) as audio:
                    duration = audio.getnframes() / audio.getframerate()
                cues = reply['reply_timed']
                self.assertEqual([at for at, _ in cues], sorted(at for at, _ in cues))
                self.assertLessEqual(cues[-1][0], duration)
                self.assertEqual(' '.join(text for _, text in cues if text), reply['reply'])
                if item['id'] == 'birthday':
                    self.assertLess(duration, 9)
                if 'math' in demo:
                    self.assertLess(demo['math']['visual_timed'][-1][0], duration)

    def test_public_catalog_hides_seed_and_contract(self):
        public = catalog()
        self.assertEqual([item["id"] for item in public], ["birthday", "plant", "draw", "mathcheck", "rainbow", "pompeii"])
        self.assertEqual(len(public), 6)
        self.assertNotIn("seed", public[0])
        self.assertNotIn("contract", public[0])
        self.assertEqual(public[0]["demo"]["prompt_audio"], "/static/demo-birthday-kid.mp3?v=days1")
        self.assertEqual(
            public[0]["demo"]["reply"],
            "Eleven more days. That's close enough to start getting excited. "
            "Your birthday will be here before you know it.",
        )
        self.assertEqual(public[0]["demo"]["reply_audio"], "/static/demo-birthday-refreshed.wav")
        self.assertNotIn("video", public[0]["demo"])
        self.assertNotIn("image", public[0]["demo"])
        plant = public[1]["demo"]
        self.assertEqual(plant["camera"]["video"], "/static/demo-plant-camera.mp4?v=plant6")
        self.assertEqual(plant["camera"]["start_at"], 2.6)
        self.assertEqual(
            [cue["at"] for cue in plant["camera"]["cues"]],
            [3.05],
        )
        self.assertEqual(
            [cue["audio"] for cue in plant["camera"]["cues"]],
            [
                "/static/demo-plant-question.mp3?v=plant5",
            ],
        )
        self.assertEqual(plant["reply_audio"], "/static/demo-plant-refreshed.wav")
        self.assertEqual(
            [caption for _, caption in plant["reply_timed"]],
            [
                "Your plant caught a tiny fungal bug,",
                "which works just like a cold for plants!",
                "It covers the leaves with dark spots and yellow circles,",
                "making the edges brown and crispy.",
                "You can help it heal by snipping off the sick leaves",
                "and throwing them away in the trash.",
                "Just make sure to water only the dirt around the base,",
                "keeping the remaining leaves dry so the fungus can't spread.",
            ],
        )
        self.assertEqual(plant['camera']['reply_wait_ms'], 1000)
        self.assertTrue(plant['camera']['loop'])
        self.assertEqual(plant["reply_audio_rate"], 1.0)
        self.assertNotIn("touch", plant["reply"].lower())
        self.assertNotIn("soil", plant["reply"].lower())
        draw = public[2]["demo"]
        self.assertEqual(draw["prompt_audio"], "/static/demo-draw-kid.mp3?v=draw1")
        self.assertEqual(draw["reply_audio"], "/static/demo-draw-gizmo.wav?v=draw1")
        self.assertEqual(draw["image"], "/static/demo-draw-jake.png?v=draw1")
        self.assertIn("Adventure Time", draw["reply"])
        self.assertIn("Jake the Dog", draw["reply"])
        self.assertTrue(draw['keep_scene'])
        self.assertTrue(draw['fullscreen_after_reply'])
        self.assertIn("easy", draw["reply"])
        math = public[3]["demo"]
        self.assertEqual(math["prompt_audio"], "/static/demo-math-kid.mp3?v=math2")
        self.assertEqual(math["camera"], {
                "video": "/static/demo-math-camera.mp4?v=math3",
                "start_at": 0,
                "home_wait_ms": 1000,
                "reply_wait_ms": 2000,
                "loop": True,
            "cues": [{
                "at": 1.0,
                "prompt": "Gizmo, did I get this right?",
                "audio": "/static/demo-math-kid.mp3?v=math2",
            }],
        })
        self.assertEqual(math["reply_audio"], "/static/demo-mathcheck-refreshed.wav?v=math4")
        self.assertEqual(math["reply_audio_rate"], 1.3)
        self.assertEqual(math["math"]["attempt"], "26 + 16 = 43")
        self.assertEqual(math["math"]["make_ten"], "20 + 10 = 30")
        self.assertEqual(math["math"]["left"], "6 + 6 = 12")
        self.assertEqual(math["math"]["answer"], "30 + 12 = 42")
        self.assertIn("not forty-three", math["reply"])
        self.assertIn("Together, forty-two", math["reply"])
        rainbow = public[4]["demo"]
        self.assertEqual(rainbow["prompt_audio"], "/static/demo-rainbow-kid.mp3?v=rainbow2")
        self.assertEqual(rainbow["beats"][0]["rainbow"], {"focus": "overview"})
        self.assertEqual(rainbow["beats"][0]["interruption"], {
            "after_ms": 12600,
            "prompt": "Wait, why does the light split?",
            "audio": "/static/demo-rainbow-kid-followup.mp3?v=rainbow2",
            "think_wait_ms": 1200,
        })
        self.assertEqual(rainbow["beats"][1]["rainbow"], {"focus": "split"})
        self.assertIn("many colors", rainbow["beats"][1]["reply"])
        self.assertEqual(public[5]["demo"]["prompt_audio"], "/static/demo-pompeii-kid.mp3")
        self.assertEqual(public[5]["demo"]["video"], "/static/demo-pompeii-polished.mp4")
        self.assertIn('paintings', public[5]['demo']['followup']['prompt'])
        self.assertEqual(public[5]['demo']['followup']['audio'], "/static/demo-pompeii-kid-followup-user.mp3?v=pompeii1")
        self.assertEqual(public[5]['demo']['followup']['video'], "/static/demo-pompeii-followup.mp4?v=pompeii1")
        self.assertEqual(public[5]["demo"]["reply_audio"], "/static/demo-pompeii.wav")
        self.assertIn("Vesuvius", public[5]["demo"]["reply"])
        self.assertTrue(lookup("trex").contract)
        self.assertIsNone(lookup("missing"))

    def test_birthday_seed_is_eleven_days_out(self):
        with patch.dict("os.environ", {"GIZMO_TZ": "UTC"}):
            text = lookup("birthday").seed_text()
        today = datetime.now(ZoneInfo("UTC")).date()
        when = today + timedelta(days=11)
        self.assertIn(str(when.day), text)
        self.assertIn(when.strftime("%B"), text)
        self.assertIn("birthday", text.lower())


class MomentRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.tmp.name)
        self.director = FakeDirector([beat(), beat("video")])

    async def asyncTearDown(self):
        self.tmp.cleanup()

    async def _session(self, identity: str, payload: dict) -> ExperienceSession:
        directory = self.root / "oddity" / identity
        directory.mkdir(parents=True)
        directory.joinpath("session.json").write_text(json.dumps(payload))
        async def send(event): pass
        friend = ExperienceSession(self.root, identity, send, director=self.director,
                                   images=FakeImages(), cinema=FakeCinema(), memory=NullMemoryProvider())
        return friend

    async def test_seed_memory_and_contract_are_injected(self):
        friend = await self._session("b" * 32, {
            "mode": "moment", "moment": "trex",
            "seed_memory": "The kid's birthday is soon.",
            "director_addendum": "Ask what they think first.",
        })
        self.assertTrue(friend.bounded)
        await friend.load_memory()
        self.assertIn("birthday", friend.memory_context)
        await friend.begin("Could a T-Rex beat an elephant?")
        await friend.task
        self.assertEqual(self.director.requests[-1][3], friend.memory_context)
        self.assertEqual(self.director.requests[-1][4], "Ask what they think first.")
        await friend.close()

    async def test_lab_skips_media_budgets(self):
        friend = await self._session("c" * 32, {"mode": "lab"})
        self.assertFalse(friend.bounded)
        await friend.begin("What if I fell into Jupiter?")
        await friend.task
        self.assertFalse((self.root / "oddity-show-usage.json").exists())
        self.assertFalse((self.root / "oddity-motion-usage.json").exists())
        await friend.close()

    async def test_moment_sessions_still_reserve_media(self):
        friend = await self._session("d" * 32, {"mode": "moment", "moment": "pompeii"})
        self.assertTrue(friend.bounded)
        await friend.begin("What happened to Pompeii?")
        await friend.task
        # The reconstruction ask routes to film; bounded sessions still spend an allowance.
        self.assertTrue((self.root / "oddity-motion-usage.json").exists())
        await friend.close()

    async def test_moment_process_ask_reserves_film(self):
        friend = await self._session("e" * 32, {"mode": "moment", "moment": "pompeii"})
        await friend.begin("What if I fell into Jupiter?")
        await friend.task
        self.assertTrue((self.root / "oddity-motion-usage.json").exists())
        await friend.close()
