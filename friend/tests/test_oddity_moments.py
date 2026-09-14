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
                if item['id'] == 'plant':
                    self.assertLess(duration / demo['reply_audio_rate'], 21.2)
                    self.assertGreater(duration / demo['reply_audio_rate'], 20.5)
                if 'math' in demo:
                    self.assertLess(demo['math']['visual_timed'][-1][0], duration)

    def test_public_catalog_hides_seed_and_contract(self):
        public = catalog()
        self.assertEqual(
            [item["id"] for item in public],
            ["birthday", "plant", "draw", "mathcheck", "rainbow", "antarctica", "pompeii"],
        )
        self.assertEqual(len(public), 7)
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
        self.assertEqual(plant["reply_audio"], "/static/demo-plant-refreshed.wav?v=plant2")
        self.assertEqual(
            [caption for _, caption in plant["reply_timed"]],
            [
                "Your plant caught a tiny fungal bug,",
                "which causes dark spots, yellow circles,",
                "and crispy brown edges.",
                "Help it heal by snipping off the sick leaves",
                "and throwing them in the trash.",
                "Water only the dirt around the base,",
                "keeping the other leaves dry so the fungus can't spread.",
            ],
        )
        self.assertEqual(plant['camera']['reply_wait_ms'], 1000)
        self.assertTrue(plant['camera']['loop'])
        self.assertEqual(plant["reply_audio_rate"], 0.92)
        self.assertNotIn("touch", plant["reply"].lower())
        self.assertNotIn("soil", plant["reply"].lower())
        draw = public[2]["demo"]
        self.assertEqual(draw["prompt_audio"], "/static/demo-draw-kid.mp3?v=draw1")
        self.assertEqual(draw["reply_audio"], "/static/demo-draw-gizmo.wav?v=draw1")
        self.assertEqual(draw["image"], "/static/demo-draw-jake.png?v=draw1")
        self.assertIn("Adventure Time", draw["reply"])
        self.assertIn("Jake the Dog", draw["reply"])
        self.assertFalse(draw.get('keep_scene', False))
        self.assertTrue(draw['fullscreen_after_reply'])
        self.assertEqual(draw['post_reply_hold_ms'], 5000)
        self.assertIn("easy", draw["reply"])
        math = public[3]["demo"]
        self.assertEqual(math["prompt_audio"], "/static/demo-math-kid.mp3?v=math2")
        self.assertEqual(math["camera"], {
                "video": "/static/demo-math-fraction-camera.mp4?v=fraction2",
                "start_at": 0,
                "home_wait_ms": 1000,
                "post_question_hold_ms": 4000,
                "reply_wait_ms": 900,
                "loop": True,
            "cues": [{
                "at": 0.8,
                "prompt": "Gizmo, did I get this right?",
                "audio": "/static/demo-math-kid.mp3?v=math2",
            }],
        })
        self.assertEqual(math["reply_audio"], "/static/demo-math-fraction-gizmo.wav?v=fraction1")
        self.assertEqual(math["reply_audio_rate"], 1.0)
        self.assertEqual(math["math"]["attempt"], "2/3")
        self.assertEqual(math["math"]["shaded"], "shaded parts")
        self.assertEqual(math["math"]["total"], "equal parts")
        self.assertEqual(math["math"]["answer"], "2/4 = 1/2")
        self.assertIn("two blue parts", math["reply"])
        self.assertIn("same as one-half", math["reply"])
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
        antarctica = public[5]["demo"]
        self.assertEqual(antarctica["prompt_audio"], "/static/demo-antarctica-kid.mp3?v=antarctica1")
        self.assertEqual(antarctica["reply_audio"], "/static/demo-antarctica-gizmo.wav?v=antarctica3")
        self.assertEqual(antarctica["video"], "/static/demo-antarctica.mp4?v=antarctica1")
        self.assertIn("South Pole", antarctica["reply"])
        self.assertIn("penguins", antarctica["reply"])
        self.assertEqual(len(antarctica["beats"]), 2)
        self.assertEqual(
            antarctica["beats"][0]["reply_timed"],
            [
                [0.0, "Antarctica is the icy continent at the very bottom of Earth."],
                [5.3, "On a globe, it wraps around the South Pole."],
                [9.1, "Most of it is covered by a huge sheet of ice,"],
                [12.45, "with bright glaciers, tall mountains, and deep blue cracks."],
                [18.1, "Along the coast, you can see floating icebergs and penguins."],
            ],
        )
        interruption = antarctica["beats"][0]["interruption"]
        self.assertEqual(interruption["after_ms"], 22000)
        self.assertTrue(interruption["fullscreen_during_prompt"])
        self.assertEqual(
            interruption["audio"],
            "/static/demo-antarctica-followup-kid.mp3?v=penguin1",
        )
        self.assertIn("anywhere else", interruption["prompt"])
        self.assertEqual(
            antarctica["beats"][1]["reply_audio"],
            "/static/demo-antarctica-followup-gizmo.wav?v=penguin1",
        )
        self.assertEqual(
            antarctica["beats"][1]["video"],
            "/static/demo-antarctica-followup.mp4?v=penguin1",
        )
        self.assertIn("South America", antarctica["beats"][1]["reply"])
        self.assertIn("Galapagos", antarctica["beats"][1]["reply"])
        self.assertEqual(public[6]["demo"]["prompt_audio"], "/static/demo-pompeii-kid.mp3")
        self.assertEqual(public[6]["demo"]["video"], "/static/demo-pompeii-polished.mp4")
        self.assertIn('paintings', public[6]['demo']['followup']['prompt'])
        self.assertEqual(public[6]['demo']['followup']['audio'], "/static/demo-pompeii-kid-followup-user.mp3?v=pompeii1")
        self.assertEqual(public[6]['demo']['followup']['video'], "/static/demo-pompeii-followup.mp4?v=pompeii1")
        self.assertEqual(public[6]["demo"]["reply_audio"], "/static/demo-pompeii.wav")
        self.assertIn("Vesuvius", public[6]["demo"]["reply"])
        self.assertTrue(lookup("trex").contract)
        self.assertIsNone(lookup("missing"))

    def test_math_visual_uses_fraction_circle_without_agent_characters(self):
        html = (Path(__file__).resolve().parents[1] / "gizmo_friend" / "static" / "oddity.html").read_text()
        self.assertIn('class="fraction-model"', html)
        self.assertEqual(html.count('fraction-piece is-shaded'), 2)
        self.assertIn('id="math-shaded"', html)
        self.assertIn('id="math-total"', html)
        self.assertNotIn('class="math-pals"', html)
        self.assertNotIn('class="math-face"', html)

    def test_camera_caption_bar_stays_visible_while_gizmo_words_swap(self):
        css = (Path(__file__).resolve().parents[1] / "gizmo_friend" / "static" / "oddity-device.css").read_text()
        self.assertIn("background:#05070b;", css)
        self.assertNotIn("background:#05070bf2;", css)
        self.assertIn(
            ".stage[data-glass=camera] .caption.is-swapping{opacity:1;color:transparent",
            css,
        )

    def test_power_bar_links_to_standalone_cinema(self):
        html = (Path(__file__).resolve().parents[1] / "gizmo_friend" / "static" / "oddity.html").read_text()
        power_bar = html[html.index('<div class="power-bar">'):html.index('<div id="device"')]
        demo_rail = html[html.index('<div id="moments"'):html.index('</section>', html.index('<div id="moments"'))]
        self.assertIn(
            'id="power-cinema" href="https://oddware.xyz/gizmo/cinema" target="_top"',
            power_bar,
        )
        self.assertNotIn("power-cinema", demo_rail)

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
