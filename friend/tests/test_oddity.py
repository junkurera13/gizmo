from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlsplit

from fastapi.testclient import TestClient
from gizmo_friend.brain.memory import NullMemoryProvider
from gizmo_friend.oddity.director import Beat, Experience
from gizmo_friend.oddity.film import FilmReady, OddityCinema, route_moving_picture
from gizmo_friend.oddity.runtime import ExperienceSession
from gizmo_friend.server import app_factory
from pydantic import ValidationError


def beat(visual="face", narration="A useful opening."):
    return Beat(narration=narration, visual=visual,
                subject="Jupiter's atmosphere" if visual in {"video", "image", "film", "diagram"} else "",
                motion="Cloud bands circle the planet" if visual == "video" else "", purpose="Explain the idea")


class FakeDirector:
    def __init__(self, beats):
        self.beats = beats
        self.requests = []

    async def plan(self, text, history, current, memory="", contract=""):
        self.requests.append((text, list(history), dict(current), memory, contract))
        return Experience(title="Jupiter", beats=self.beats)

    async def speech(self, text): return b"test wave"
    async def close(self): pass


class FakeImages:
    async def conjure(self, *args, **kwargs): return SimpleNamespace(jpeg=b"test image")
    async def close(self): pass


class FakeCinema:
    def __init__(self):
        self.asked = []
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()
        self.block = False
        self.fail = False
        self.available_flag = True
        self.finished = []
        self.closed = False
        self.interrupted = 0

    def available(self):
        return self.available_flag

    async def start(self, text):
        self.asked.append(text)
        self.started.set()
        try:
            if self.block:
                await asyncio.Event().wait()
            if self.fail:
                return None
            return FilmReady(revision=1, duration=8.0, title="Jupiter",
                             narration="Clouds race around the giant.")
        except asyncio.CancelledError:
            self.cancelled.set()
            raise

    async def offer(self, sdp, revision, local=False):
        return {"sdp": "answer", "type": "answer"}

    async def finish(self, revision):
        self.finished.append(revision)

    async def interrupt(self):
        self.interrupted += 1

    async def close(self):
        self.closed = True
        await self.interrupt()


class OddityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True); self.root = Path(self.tmp.name)
        self.events = []
        self.director = FakeDirector([beat(), beat("video")])
        self.cinema = FakeCinema()
        async def send(event): self.events.append(event)
        self.session = ExperienceSession(self.root, "a" * 32, send, director=self.director,
                                         images=FakeImages(), cinema=self.cinema, memory=NullMemoryProvider())

    async def asyncTearDown(self):
        await self.session.close(); self.tmp.cleanup()

    async def test_prepares_ordered_film_with_cinema_and_no_mp4(self):
        await self.session.begin("What if I fell into Jupiter?"); await self.session.task
        beats = [e["beat"] for e in self.events if e["type"] == "beat"]
        self.assertEqual([b["index"] for b in beats], [0, 1])
        self.assertEqual(beats[1]["visual"], "film")
        self.assertEqual(beats[1]["film"]["revision"], 1)
        self.assertEqual(beats[1]["film"]["duration"], 8.0)
        self.assertIsNone(beats[1]["video"])
        self.assertIsNone(beats[1]["audio"])
        self.assertTrue(urlsplit(beats[0]["audio"]).path.endswith(".wav"))
        self.assertEqual(self.cinema.asked, ["What if I fell into Jupiter?"])
        self.assertEqual([m["role"] for m in self.session.history], ["user"])
        self.assertFalse(any(path.suffix == ".mp4" for path in self.session.directory.glob("*")))

    async def test_interrupt_cancels_cinema_and_never_records_unseen_script(self):
        self.cinema.block = True
        await self.session.begin("What if I fell into Jupiter?"); old_turn = self.session.turn
        await asyncio.wait_for(self.cinema.started.wait(), 2)
        await self.session.stop()
        self.assertTrue(self.cinema.cancelled.is_set())
        self.assertGreaterEqual(self.cinema.interrupted, 1)
        self.assertFalse(any(m["role"] == "assistant" for m in self.session.history))
        self.assertFalse(any(e["type"] == "beat" and e["beat"]["visual"] == "film" for e in self.events))
        before = len(self.events)
        await self.session.event("beat", old_turn, beat={})
        self.assertEqual(before, len(self.events))

    async def test_acknowledgements_ignore_forgery_duplicates_and_stale_turns(self):
        await self.session.begin("Jupiter"); await self.session.task
        one = next(e["beat"] for e in self.events if e["type"] == "beat")
        ack = {"turn": self.session.turn, "id":one["id"]}
        await self.session.playback({**ack, "phase":"finished"})
        self.assertEqual(len(self.session.history), 1)
        await self.session.playback({**ack, "phase":"started", "turn":"stale"})
        self.assertEqual(self.session.current, {})
        await self.session.playback({**ack, "phase":"started"})
        await self.session.playback({**ack, "phase":"finished"})
        await self.session.playback({**ack, "phase":"finished"})
        self.assertEqual(len(self.session.history), 2)
        self.assertEqual(self.session.history[-1]["text"], one["narration"])

    async def test_interruption_context_survives_restart(self):
        await self.session.begin("Jupiter"); await self.session.task
        one = next(e["beat"] for e in self.events if e["type"] == "beat")
        await self.session.playback({"turn":self.session.turn, "id":one["id"], "phase":"started"})
        await self.session.stop()
        self.assertTrue(self.session.current["interrupted"])
        async def send(event): pass
        restored = ExperienceSession(self.root, "a"*32, send, director=FakeDirector([beat()]),
                                     images=FakeImages(), cinema=FakeCinema(), memory=NullMemoryProvider())
        self.assertEqual(restored.current["narration"], one["narration"])
        self.assertEqual(len(restored.history), 1)
        await restored.close()

    async def test_image_failure_is_explicit_and_does_not_start_cinema(self):
        self.director.beats = [beat(), beat("image")]
        async def no_image(*args, **kwargs): return None
        self.session.images.conjure = no_image
        await self.session.begin("Show me Jupiter."); await self.session.task
        two = [e["beat"] for e in self.events if e["type"] == "beat"][1]
        self.assertEqual(two["visual"], "keep")
        self.assertTrue(two["warnings"])
        self.assertIsNone(two["film"])
        self.assertEqual(self.cinema.asked, [])

    async def test_easy_ask_does_not_start_cinema(self):
        await self.session.begin("Hi"); await self.session.task
        beats = [e["beat"] for e in self.events if e["type"] == "beat"]
        self.assertEqual(beats[1]["visual"], "image")
        self.assertIsNone(beats[1]["film"])
        self.assertTrue(beats[1]["image"])
        self.assertEqual(self.cinema.asked, [])

    async def test_only_one_film_per_turn(self):
        self.director.beats = [beat("image"), beat("video")]
        await self.session.begin("How does a rocket actually take off?"); await self.session.task
        beats = [e["beat"] for e in self.events if e["type"] == "beat"]
        self.assertEqual([b["visual"] for b in beats], ["film", "image"])
        self.assertEqual(self.cinema.asked, ["How does a rocket actually take off?"])

    async def test_film_finish_acks_cinema(self):
        await self.session.begin("What if I fell into Jupiter?"); await self.session.task
        film_beat = next(e["beat"] for e in self.events if e["type"] == "beat" and e["beat"]["visual"] == "film")
        ack = {"turn": self.session.turn, "id": film_beat["id"]}
        await self.session.playback({**ack, "phase": "started"})
        await self.session.playback({**ack, "phase": "finished"})
        self.assertEqual(self.cinema.finished, [1])

    async def test_kept_scene_is_revisitable_and_home_clears_director_context(self):
        self.director.beats = [beat("image"), beat("keep")]
        await self.session.begin("Jupiter"); await self.session.task
        beats = [e["beat"] for e in self.events if e["type"] == "beat"]
        for item in beats:
            for phase in ["started", "finished"]:
                await self.session.playback({"turn":self.session.turn, "id":item["id"], "phase":phase})
        self.assertEqual(self.session.library[-1]["image"], beats[0]["image"])
        self.session.revisit(beats[1]["id"])
        self.assertEqual(self.session.current["screen"]["subject"], beats[0]["subject"])
        self.session.revisit(None)
        self.assertIsNone(self.session.current["screen"])

    def test_plan_rejects_incoherent_media(self):
        with self.assertRaises(ValidationError): Beat(narration="Hi", visual="video", purpose="Missing brief")
        with self.assertRaises(ValidationError): Beat(narration="Hi", visual="film", purpose="Missing brief")
        with self.assertRaises(ValidationError): Experience(title="Too many films", beats=[beat("video"), beat("film")])

    def test_runtime_does_not_call_clip_provider(self):
        import inspect

        from gizmo_friend.oddity import runtime
        source = inspect.getsource(runtime)
        self.assertNotIn("ClipProvider", source)
        self.assertNotIn("clips.animate", source)
        self.assertNotIn("H3MaxClipProvider", source)

    def test_moving_picture_gate_matches_friend(self):
        filmed = route_moving_picture(Experience(title="Jupiter", beats=[beat(), beat("video")]),
                                      "What if I fell into Jupiter?")
        self.assertEqual([b.visual for b in filmed.beats], ["face", "film"])
        stills = route_moving_picture(Experience(title="Hello", beats=[beat(), beat("video")]), "Hi")
        self.assertEqual([b.visual for b in stills.beats], ["face", "image"])
        diagram = route_moving_picture(Experience(title="Map", beats=[beat("diagram")]),
                                       "How does a rocket actually take off?")
        self.assertEqual(diagram.beats[0].visual, "diagram")


class OddityRouteTests(unittest.TestCase):
    def test_provisioned_identity_and_media_isolation(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {"GIZMO_DEVICE_TOKEN":"", "RAILWAY_ENVIRONMENT_ID":""}):
            root = Path(directory)
            with TestClient(app_factory(root)) as first, TestClient(app_factory(root)) as second:
                response = first.get("/oddity")
                self.assertEqual(response.status_code, 200)
                provisioned = first.post("/oddity/session")
                self.assertEqual(provisioned.status_code, 200)
                self.assertIn("HttpOnly", provisioned.headers["set-cookie"])
                identity = provisioned.json()["session"]
                name = "b"*32 + ".jpg"
                (root / "oddity" / identity / name).write_bytes(b"private")
                self.assertEqual(first.get("/oddity/media/" + name, params={"session": identity}).status_code, 200)
                other = second.post("/oddity/session").json()["session"]
                self.assertNotEqual(identity, other)
                self.assertEqual(second.get("/oddity/media/" + name, params={"session": other}).status_code, 404)
                self.assertEqual(first.get("/oddity/media/session.json").status_code, 404)
                self.assertEqual(first.get("/health").status_code, 200)

    def test_cloud_preview_is_public_shell_with_gated_session(self):
        environment = {
            "GIZMO_DEVICE_TOKEN": "device-secret",
            "RAILWAY_ENVIRONMENT_ID": "production",
            "ODDITY_PREVIEW_TOKEN": "adult-review",
            "ODDITY_LAB_TOKEN": "lab-secret",
        }
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", environment):
            root = Path(directory)
            with TestClient(app_factory(root)) as client:
                self.assertEqual(client.get("/oddity").status_code, 200)
                self.assertEqual(client.get("/oddity/moments").status_code, 200)
                self.assertEqual(client.get("/static/oddity.js").status_code, 200)
                self.assertEqual(client.get("/static/demo-birthday-kid.mp3").status_code, 200)
                self.assertEqual(client.get("/static/demo-birthday-gizmo.wav").status_code, 200)
                self.assertEqual(client.get("/static/demo-pompeii-kid.mp3").status_code, 200)
                self.assertEqual(client.get("/static/demo-pompeii-2-loop.mp4").status_code, 200)
                self.assertEqual(client.get("/").status_code, 401)
                self.assertEqual(client.post("/oddity/session").status_code, 401)
                response = client.post("/oddity/session", headers={"x-oddity-preview": "adult-review"})
                self.assertEqual(response.status_code, 200)
                body = response.json()
                self.assertRegex(body["session"], r"^[0-9a-f]{32}$")
                self.assertEqual(body["mode"], "moment")
                self.assertEqual(body["moment"], "birthday")
                saved = json.loads((root / "oddity" / body["session"] / "session.json").read_text())
                self.assertIn("birthday", saved["seed_memory"])
                self.assertTrue(saved["director_addendum"])

    def test_lab_and_moment_tokens_are_isolated_and_lab_skips_caps(self):
        environment = {
            "GIZMO_DEVICE_TOKEN": "device-secret",
            "RAILWAY_ENVIRONMENT_ID": "production",
            "ODDITY_PREVIEW_TOKEN": "adult-review",
            "ODDITY_LAB_TOKEN": "lab-secret",
        }
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", environment):
            root = Path(directory)
            with TestClient(app_factory(root)) as client:
                self.assertEqual(client.post("/oddity/session", headers={
                    "x-oddity-mode": "lab", "x-oddity-preview": "adult-review",
                }).status_code, 401)
                self.assertEqual(client.post("/oddity/session", headers={
                    "x-oddity-mode": "moment", "x-oddity-lab": "lab-secret",
                }).status_code, 401)
                self.assertEqual(client.post("/oddity/session", headers={
                    "x-oddity-mode": "moment", "x-oddity-preview": "adult-review",
                    "x-oddity-moment": "not-a-moment",
                }).status_code, 400)
                lab = client.post("/oddity/session", headers={
                    "x-oddity-mode": "lab", "x-oddity-lab": "lab-secret",
                })
                self.assertEqual(lab.status_code, 200)
                self.assertEqual(lab.json()["mode"], "lab")
                self.assertEqual(lab.json()["moments"], [])
                saved = json.loads((root / "oddity" / lab.json()["session"] / "session.json").read_text())
                self.assertEqual(saved["mode"], "lab")
                first = client.post("/oddity/session", headers={
                    "x-oddity-mode": "moment", "x-oddity-preview": "adult-review",
                    "x-oddity-moment": "draw",
                })
                second = client.post("/oddity/session", headers={
                    "x-oddity-mode": "moment", "x-oddity-preview": "adult-review",
                    "x-oddity-moment": "pompeii",
                    "x-oddity-session": first.json()["session"],
                })
                self.assertNotEqual(first.json()["session"], second.json()["session"])
                reuse = client.post("/oddity/session", headers={
                    "x-oddity-mode": "moment", "x-oddity-preview": "adult-review",
                    "x-oddity-moment": "pompeii",
                    "x-oddity-session": second.json()["session"],
                })
                self.assertEqual(reuse.json()["session"], second.json()["session"])
                reused_path = root / "oddity" / reuse.json()["session"] / "session.json"
                reused = json.loads(reused_path.read_text())
                reused["director_addendum"] = "stale contract"
                reused_path.write_text(json.dumps(reused))
                client.post("/oddity/session", headers={
                    "x-oddity-mode": "moment", "x-oddity-preview": "adult-review",
                    "x-oddity-moment": "pompeii",
                    "x-oddity-session": reuse.json()["session"],
                })
                refreshed = json.loads(reused_path.read_text())
                self.assertNotEqual(refreshed["director_addendum"], "stale contract")

    def test_cloud_lab_without_token_is_unavailable(self):
        environment = {
            "GIZMO_DEVICE_TOKEN": "device-secret",
            "RAILWAY_ENVIRONMENT_ID": "production",
            "ODDITY_PREVIEW_TOKEN": "adult-review",
        }
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", environment):
            with TestClient(app_factory(Path(directory))) as client:
                self.assertEqual(client.post("/oddity/session", headers={"x-oddity-mode": "lab"}).status_code, 503)

    def test_websocket_rejects_cross_origin(self):
        from starlette.websockets import WebSocketDisconnect
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {"GIZMO_DEVICE_TOKEN":"", "RAILWAY_ENVIRONMENT_ID":""}):
            with TestClient(app_factory(Path(directory))) as client:
                session = client.post("/oddity/session").json()["session"]
                with self.assertRaises(WebSocketDisconnect):
                    with client.websocket_connect(
                        "/oddity/ws?session=" + session,
                        headers={"origin":"https://unrelated.example"},
                    ): pass

    def test_offer_requires_same_origin_live_session(self):
        with (
            tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory,
            patch.dict("os.environ", {"GIZMO_DEVICE_TOKEN": "", "RAILWAY_ENVIRONMENT_ID": ""}),
            TestClient(app_factory(Path(directory))) as client,
        ):
            payload = {"sdp": "v=0", "revision": 1}
            self.assertEqual(client.post("/oddity/offer", json=payload).status_code, 403)
            session = client.post("/oddity/session").json()["session"]
            missing = client.post(
                "/oddity/offer", json=payload, params={"session": session},
                headers={"origin": "http://testserver"},
            )
            self.assertEqual(missing.status_code, 404)
            self.assertEqual(client.get("/cinema").status_code, 200)
            self.assertEqual(client.get("/static/cinema.js").status_code, 200)


class OddityCinemaTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_reuses_cinema_runtime_and_offer_attaches(self):
        from unittest.mock import AsyncMock

        from gizmo_friend.cinema.plan import FilmBeat, FilmPlan, PreparedFilm
        from test_cinema import FakeStream

        root = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(root.cleanup)
        plan = FilmPlan(
            title="Rocket",
            beats=[FilmBeat(narration="Hot gas goes down.", action="Show exhaust moving down.")],
            thread="propulsion",
        )
        maker = AsyncMock()
        maker.plan.return_value = plan
        maker.synthesize.return_value = PreparedFilm(plan, "https://audio.fal.media/test.wav", 10, b"fake")
        maker.upload_audio.return_value = "https://audio.fal.media/test.wav"
        cinema = OddityCinema(
            directory=Path(root.name) / "oddity" / ("a" * 32),
            fal_key="test",
            maker=maker,
            stream_factory=FakeStream,
        )
        ready = await cinema.start("How does a rocket actually take off?")
        self.assertEqual(ready.title, "Rocket")
        self.assertEqual(ready.duration, 10)
        self.assertGreaterEqual(ready.revision, 1)
        answer = await cinema.offer("offer", ready.revision)
        self.assertEqual(answer["sdp"], "answer")
        await cinema.close()


if __name__ == "__main__": unittest.main()
