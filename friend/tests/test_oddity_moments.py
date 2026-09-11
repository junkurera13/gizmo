from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from gizmo_friend.brain.memory import NullMemoryProvider
from gizmo_friend.oddity.moments import ORDER, catalog, lookup
from gizmo_friend.oddity.runtime import ExperienceSession
from test_oddity import FakeCinema, FakeDirector, FakeImages, beat


class MomentCatalogTests(unittest.TestCase):
    def test_public_catalog_hides_seed_and_contract(self):
        public = catalog()
        self.assertEqual([item["id"] for item in public], ["birthday", "plant", "draw", "mathcheck", "pompeii"])
        self.assertEqual(len(public), 5)
        self.assertNotIn("seed", public[0])
        self.assertNotIn("contract", public[0])
        self.assertEqual(public[0]["demo"]["prompt_audio"], "/static/demo-birthday-kid.mp3?v=days1")
        self.assertEqual(
            public[0]["demo"]["reply"],
            "Eleven more days. That's close enough to start getting excited. "
            "Your birthday will be here before you know it.",
        )
        self.assertEqual(public[0]["demo"]["reply_audio"], "/static/demo-birthday-gizmo.wav?v=days1")
        self.assertNotIn("video", public[0]["demo"])
        self.assertNotIn("image", public[0]["demo"])
        plant = public[1]["demo"]
        self.assertEqual(plant["camera"]["video"], "/static/demo-plant-camera.mp4?v=plant5")
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
        self.assertEqual(plant["reply_audio"], "/static/demo-plant-gizmo.wav?v=plant8")
        self.assertEqual(plant["reply_audio_rate"], 1.0)
        self.assertNotIn("touch", plant["reply"].lower())
        self.assertNotIn("soil", plant["reply"].lower())
        draw = public[2]["demo"]
        self.assertEqual(draw["prompt_audio"], "/static/demo-draw-kid.mp3?v=draw1")
        self.assertEqual(draw["reply_audio"], "/static/demo-draw-gizmo.wav?v=draw1")
        self.assertEqual(draw["image"], "/static/demo-draw-jake.png?v=draw1")
        self.assertIn("Adventure Time", draw["reply"])
        self.assertIn("Jake the Dog", draw["reply"])
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
        self.assertEqual(math["reply_audio"], "/static/demo-math-gizmo.wav?v=math1")
        self.assertEqual(math["math"]["attempt"], "27 + 16 = 42")
        self.assertEqual(math["math"]["answer"], "40 + 3 = 43")
        self.assertIn("only one away", math["reply"])
        self.assertIn("forty-three", math["reply"])
        self.assertEqual(public[4]["demo"]["prompt_audio"], "/static/demo-pompeii-kid.mp3")
        self.assertEqual(public[4]["demo"]["video"], "/static/demo-pompeii.mp4")
        self.assertEqual(public[4]["demo"]["reply_audio"], "/static/demo-pompeii.wav")
        self.assertIn("Vesuvius", public[4]["demo"]["reply"])
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
