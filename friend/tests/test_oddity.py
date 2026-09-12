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
from gizmo_friend.oddity.film import FilmReady, OddityCinema
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
        self.directions = []
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()
        self.block = False
        self.fail = False
        self.available_flag = True
        self.finished = []
        self.watched = []
        self.closed = False
        self.interrupted = 0

    def available(self):
        return self.available_flag

    async def start(self, text, *, direction="", on_pending=None):
        self.asked.append(text)
        self.directions.append(direction)
        self.started.set()
        try:
            if on_pending is not None:
                await on_pending(1)
            if self.block:
                await asyncio.Event().wait()
            if self.fail:
                return None
            return FilmReady(revision=1, duration=8.0, title="Jupiter",
                             narration="Clouds race around the giant.",
                             timings=({"start": 0.0, "end": 8.0, "narration": "Clouds race around the giant."},),
                             soundtrack=b"film wave")
        except asyncio.CancelledError:
            self.cancelled.set()
            raise

    async def offer(self, sdp, revision, local=False):
        return {"sdp": "answer", "type": "answer"}

    def watch(self, revision):
        self.watched.append(revision)
        return revision == 1

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
        plan = next(e for e in self.events if e["type"] == "plan")
        self.assertEqual(plan["medium"], "film")
        beats = [e["beat"] for e in self.events if e["type"] == "beat"]
        # A film turn is the film alone: the planned face opener is dropped.
        self.assertEqual([b["index"] for b in beats], [0])
        self.assertEqual(beats[0]["visual"], "film")
        self.assertEqual(beats[0]["film"]["revision"], 1)
        self.assertEqual(beats[0]["film"]["duration"], 8.0)
        self.assertEqual(beats[0]["film"]["timings"][0]["end"], 8.0)
        self.assertEqual(beats[0]["narration"], "Clouds race around the giant.")
        self.assertIsNone(beats[0]["video"])
        self.assertIsNone(beats[0]["interaction"])
        # Cinema's own recording rides along as the voice if the stream is lost.
        self.assertTrue(urlsplit(beats[0]["audio"]).path.endswith(".wav"))
        # The raw question goes to Cinema; the director's brief rides separately.
        self.assertEqual(self.cinema.asked, ["What if I fell into Jupiter?"])
        self.assertIn("Jupiter's atmosphere", self.cinema.directions[0])
        # The glass learned the revision before the film was ready, so it could connect.
        pending = next(e for e in self.events if e["type"] == "film")
        self.assertEqual((pending["phase"], pending["revision"], pending["index"]), ("pending", 1, 0))
        self.assertLess(self.events.index(pending), self.events.index(next(
            e for e in self.events if e["type"] == "beat" and e["beat"]["visual"] == "film")))
        self.assertEqual([m["role"] for m in self.session.history], ["user"])
        self.assertFalse(any(path.suffix == ".mp4" for path in self.session.directory.glob("*")))

    async def test_film_play_starts_director_for_the_current_turn_only(self):
        await self.session.begin("What if I fell into Jupiter?"); await self.session.task
        self.assertFalse(self.session.watch({"turn": "stale", "revision": 1}))
        self.assertFalse(self.session.watch({"turn": self.session.turn, "revision": "x"}))
        self.assertTrue(self.session.watch({"turn": self.session.turn, "revision": 1}))
        self.assertEqual(self.cinema.watched, [1])

    async def test_failed_film_becomes_a_voiced_still_of_the_same_brief(self):
        self.cinema.fail = True
        await self.session.begin("What if I fell into Jupiter?"); await self.session.task
        only = [e["beat"] for e in self.events if e["type"] == "beat"][0]
        self.assertEqual(only["visual"], "image")
        self.assertIsNone(only["film"])
        self.assertTrue(only["image"])
        self.assertTrue(urlsplit(only["audio"]).path.endswith(".wav"))
        self.assertEqual(only["narration"], "A useful opening.")
        self.assertTrue(any("picture" in w for w in only["warnings"]))

    async def test_film_turn_never_asks_in_a_second_voice(self):
        from gizmo_friend.oddity.director import Interaction
        asked = beat("film").model_copy(update={"interaction": Interaction(kind="reply", prompt="What would you change?")})
        self.director.beats = [beat(), asked]
        await self.session.begin("How does a rocket actually take off?"); await self.session.task
        beats = [e["beat"] for e in self.events if e["type"] == "beat"]
        self.assertEqual([b["visual"] for b in beats], ["film"])
        self.assertIsNone(beats[0]["interaction"])
        self.assertNotIn("question_audio", beats[0])

    async def test_moment_contract_rides_in_the_film_brief(self):
        self.session.director_addendum = "Keep Vesuvius serious but not gory."
        await self.session.begin("Tell me the story of Pompeii."); await self.session.task
        self.assertIn("Moment contract: Keep Vesuvius", self.cinema.directions[0])

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

    async def test_failed_question_is_not_planning_context_for_the_next_turn(self):
        original_plan = self.director.plan

        async def fail(*args, **kwargs):
            raise RuntimeError("planner unavailable")

        self.director.plan = fail
        await self.session.begin("Why did the old request fail?")
        await self.session.task
        self.director.plan = original_plan
        await self.session.begin("What color is the moon?")
        await self.session.task
        history = self.director.requests[-1][1]
        self.assertFalse(any(row.get("text") == "Why did the old request fail?" for row in history))

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

    async def test_planner_medium_is_authoritative_no_utterance_veto(self):
        # The words of the ask no longer gate Cinema; only the plan does.
        await self.session.begin("Hi"); await self.session.task
        beats = [e["beat"] for e in self.events if e["type"] == "beat"]
        self.assertEqual([b["visual"] for b in beats], ["film"])
        self.assertEqual(self.cinema.asked, ["Hi"])

    async def test_stills_turn_never_starts_cinema(self):
        self.director.beats = [beat(), beat("image"), beat("diagram")]
        await self.session.begin("What does Jupiter look like?"); await self.session.task
        plan = next(e for e in self.events if e["type"] == "plan")
        self.assertEqual(plan["medium"], "stills")
        beats = [e["beat"] for e in self.events if e["type"] == "beat"]
        self.assertEqual([b["visual"] for b in beats], ["face", "image", "diagram"])
        self.assertEqual(self.cinema.asked, [])

    async def test_a_film_turn_is_the_film(self):
        # Stills planned around a film are dropped: nothing speaks before the
        # film and nothing retells it afterwards.
        self.director.beats = [beat("image"), beat("video"), beat("image", "The aftermath.")]
        await self.session.begin("How does a rocket actually take off?"); await self.session.task
        beats = [e["beat"] for e in self.events if e["type"] == "beat"]
        self.assertEqual([b["visual"] for b in beats], ["film"])
        self.assertIsNone(beats[0]["image"])
        self.assertEqual(self.cinema.asked, ["How does a rocket actually take off?"])

    async def test_film_finish_acks_cinema(self):
        await self.session.begin("What if I fell into Jupiter?"); await self.session.task
        film_beat = next(e["beat"] for e in self.events if e["type"] == "beat" and e["beat"]["visual"] == "film")
        ack = {"turn": self.session.turn, "id": film_beat["id"]}
        await self.session.playback({**ack, "phase": "started"})
        await self.session.playback({**ack, "phase": "finished"})
        self.assertEqual(self.cinema.finished, [1])

    async def test_planner_never_reads_back_its_own_journey_goal(self):
        # A stale goal outranked the kid's new words once; it no longer reaches the plan.
        self.session.journey = {"goal": "Explain why leaves change color",
                                "detour": "How does a rocket launch?",
                                "return_to": "Explain why leaves change color",
                                "last_presented": "The cheetah sprint.",
                                "observations": [{"kind": "reply"}]}
        await self.session.begin("How does a rocket launch?"); await self.session.task
        journey = self.director.requests[-1][2]["journey"]
        self.assertEqual(journey, {"last_presented": "The cheetah sprint.",
                                   "observations": [{"kind": "reply"}]})

    async def test_finished_film_leaves_no_screen_for_the_next_plan(self):
        await self.session.begin("What if I fell into Jupiter?"); await self.session.task
        film_id = f"{self.session.turn}-0"
        await self.session.playback({"turn": self.session.turn, "id": film_id, "phase": "started"})
        self.assertEqual(self.session.current["screen"]["kind"], "film")
        await self.session.playback({"turn": self.session.turn, "id": film_id, "phase": "finished"})
        self.assertIsNone(self.session.current["screen"])
        # A keep beat next turn keeps the face, never the ended film.
        self.director.beats = [beat("keep", "Following on.")]
        await self.session.begin("And then?"); await self.session.task
        keep_id = f"{self.session.turn}-0"
        await self.session.playback({"turn": self.session.turn, "id": keep_id, "phase": "started"})
        self.assertIsNone(self.session.current["screen"])
        # An interrupted film cannot echo forward either.
        self.session.current = {"id": "gone", "screen": {"kind": "film", "title": "X"},
                                "playing": False, "interrupted": True}
        self.director.beats = [beat("keep", "Next thought.")]
        await self.session.begin("Next?"); await self.session.task
        keep_id = f"{self.session.turn}-0"
        await self.session.playback({"turn": self.session.turn, "id": keep_id, "phase": "started"})
        self.assertIsNone(self.session.current["screen"])

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

    def test_plan_degrades_incoherent_media(self):
        # A visual beat with no drawable subject keeps the current screen
        # instead of rejecting the whole plan.
        self.assertEqual(Beat(narration="Hi", visual="video", purpose="Missing brief").visual, "keep")
        self.assertEqual(Beat(narration="Hi", visual="film", purpose="Missing brief").visual, "keep")
        # video is film, motion or not — Cinema plans the motion itself.
        self.assertEqual(Beat(narration="Hi", visual="video", subject="Jupiter", purpose="Alias").visual, "film")
        # Multiple film asks collapse to the first film; nothing else remains.
        plan = Experience(title="Too many films", beats=[beat("video"), beat("film")])
        self.assertEqual([b.visual for b in plan.beats], ["film"])
        # A beat carrying nothing at all is still rejected.
        with self.assertRaises(ValidationError): Beat(narration="", visual="face", purpose="Empty")

    def test_film_turn_shape(self):
        # A film medium with no film beat promotes its first picture.
        promoted = Experience(title="Pompeii", medium="film", beats=[beat(), beat("image"), beat("image")])
        self.assertEqual(promoted.medium, "film")
        self.assertEqual([b.visual for b in promoted.beats], ["film"])
        # A film medium with nothing to film is honest about what it is.
        talk = Experience(title="Hello", medium="film", beats=[beat(), beat("keep")])
        self.assertEqual(talk.medium, "talk")
        self.assertEqual(len(talk.beats), 2)
        # A planned film beat wins over a stills medium; the film is alone.
        planned = Experience(title="Rocket", medium="stills", beats=[beat("image"), beat("film"), beat("image")])
        self.assertEqual(planned.medium, "film")
        self.assertEqual([b.visual for b in planned.beats], ["film"])
        # Invitations anywhere in a film turn are dropped: Cinema ends the film,
        # and no question follows in a second voice.
        from gizmo_friend.oddity.director import Interaction
        for beats in (
            [beat(), beat("film"), Beat(narration="What would you change?", visual="keep", purpose="Ask",
                                        interaction=Interaction(kind="reply", prompt="What would you change?"))],
            [Beat(narration="What do you think happens?", visual="face", purpose="Ask",
                  interaction=Interaction(kind="reply", prompt="What do you think happens?")), beat("film")],
            [beat("film").model_copy(update={"interaction": Interaction(kind="reply", prompt="Why?")})],
        ):
            plan = Experience(title="Rocket", beats=beats)
            self.assertEqual([b.visual for b in plan.beats], ["film"])
            self.assertIsNone(plan.beats[0].interaction)
        # A stills turn is untouched, and still ends at its invitation.
        stills = Experience(title="Jupiter", beats=[beat(), beat("image"), beat("diagram")])
        self.assertEqual(stills.medium, "stills")
        self.assertEqual(len(stills.beats), 3)
        invited = Experience(title="Jupiter", beats=[
            beat(), Beat(narration="What do you see?", visual="keep", purpose="Ask",
                         interaction=Interaction(kind="reply", prompt="What do you see?")), beat("image"),
        ])
        self.assertEqual(len(invited.beats), 2)

    def test_runtime_does_not_call_clip_provider(self):
        import inspect

        from gizmo_friend.oddity import runtime
        source = inspect.getsource(runtime)
        self.assertNotIn("ClipProvider", source)
        self.assertNotIn("clips.animate", source)
        self.assertNotIn("H3MaxClipProvider", source)

    def test_no_utterance_heuristics_between_planner_and_cinema(self):
        import inspect

        from gizmo_friend.oddity import film, runtime
        for module in (film, runtime):
            source = inspect.getsource(module)
            self.assertNotIn("is_easy_talk", source)
            self.assertNotIn("is_moving_explanation_ask", source)


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
        }
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", environment):
            root = Path(directory)
            with TestClient(app_factory(root)) as client:
                self.assertEqual(client.get("/oddity").status_code, 200)
                self.assertEqual(client.get("/oddity/moments").status_code, 200)
                self.assertEqual(client.get("/static/oddity.js").status_code, 200)
                self.assertEqual(client.get("/static/demo-birthday-kid.mp3").status_code, 200)
                self.assertEqual(client.get("/static/demo-birthday-gizmo.wav").status_code, 200)
                self.assertEqual(client.get("/static/demo-plant-question.mp3").status_code, 200)
                self.assertEqual(client.get("/static/demo-plant-camera.mp4").status_code, 200)
                self.assertEqual(client.get("/static/demo-plant-gizmo.wav").status_code, 200)
                self.assertEqual(client.get("/static/demo-pompeii-kid.mp3").status_code, 200)
                self.assertEqual(client.get("/static/demo-pompeii.mp4").status_code, 200)
                self.assertEqual(client.get("/static/demo-pompeii.wav").status_code, 200)
                self.assertEqual(client.get("/static/demo-pompeii-kid-followup-user.mp3").status_code, 200)
                self.assertEqual(client.get("/static/demo-pompeii-followup.mp4").status_code, 200)
                self.assertEqual(client.get("/static/demo-draw-kid.mp3").status_code, 200)
                self.assertEqual(client.get("/static/demo-draw-gizmo.wav").status_code, 200)
                self.assertEqual(client.get("/static/demo-draw-jake.png").status_code, 200)
                self.assertEqual(client.get("/static/demo-math-kid.mp3").status_code, 200)
                self.assertEqual(client.get("/static/demo-math-camera.mp4").status_code, 200)
                self.assertEqual(client.get("/static/demo-math-gizmo.wav").status_code, 200)
                self.assertEqual(client.get("/static/demo-rainbow-kid.mp3").status_code, 200)
                self.assertEqual(client.get("/static/demo-rainbow-kid-followup.mp3").status_code, 200)
                self.assertEqual(client.get("/static/demo-rainbow-gizmo-intro.wav").status_code, 200)
                self.assertEqual(client.get("/static/demo-rainbow-gizmo-split.wav").status_code, 200)
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

    def test_cloud_forces_moment_sessions_and_refreshes_contract(self):
        environment = {
            "GIZMO_DEVICE_TOKEN": "device-secret",
            "RAILWAY_ENVIRONMENT_ID": "production",
            "ODDITY_PREVIEW_TOKEN": "adult-review",
        }
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", environment):
            root = Path(directory)
            with TestClient(app_factory(root)) as client:
                self.assertEqual(client.post("/oddity/session", headers={
                    "x-oddity-mode": "sandbox",
                }).status_code, 401)
                self.assertEqual(client.post("/oddity/session", headers={
                    "x-oddity-mode": "moment", "x-oddity-preview": "adult-review",
                    "x-oddity-moment": "not-a-moment",
                }).status_code, 400)
                sandbox = client.post("/oddity/session", headers={
                    "x-oddity-mode": "sandbox", "x-oddity-preview": "adult-review",
                })
                self.assertEqual(sandbox.status_code, 200)
                self.assertEqual(sandbox.json()["mode"], "moment")
                self.assertEqual(sandbox.json()["moment"], "birthday")
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

    def test_cloud_session_without_preview_token_is_unavailable(self):
        environment = {
            "GIZMO_DEVICE_TOKEN": "device-secret",
            "RAILWAY_ENVIRONMENT_ID": "production",
        }
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", environment):
            with TestClient(app_factory(Path(directory))) as client:
                self.assertEqual(client.post("/oddity/session").status_code, 503)

    def test_local_sessions_need_no_code(self):
        environment = {
            "GIZMO_DEVICE_TOKEN": "",
            "RAILWAY_ENVIRONMENT_ID": "",
            "ODDITY_PREVIEW_TOKEN": "adult-review",
        }
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", environment):
            with TestClient(app_factory(Path(directory))) as client:
                sandbox = client.post("/oddity/session")
                self.assertEqual(sandbox.status_code, 200)
                self.assertEqual(sandbox.json()["mode"], "sandbox")
                self.assertEqual(sandbox.json()["moments"], [])
                moment = client.post("/oddity/session", headers={"x-oddity-mode": "moment"})
                self.assertEqual(moment.status_code, 200)
                self.assertEqual(moment.json()["mode"], "moment")

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
        pending = []

        async def on_pending(revision):
            pending.append(revision)

        ready = await cinema.start(
            "How does a rocket actually take off?",
            direction="Show ignition, then the gas leaving.",
            on_pending=on_pending,
        )
        self.assertEqual(ready.title, "Rocket")
        self.assertEqual(ready.duration, 10)
        self.assertGreaterEqual(ready.revision, 1)
        self.assertEqual(pending, [ready.revision])
        self.assertEqual(ready.soundtrack, b"fake")
        maker.plan.assert_awaited_once()
        self.assertEqual(maker.plan.await_args.kwargs["direction"], "Show ignition, then the gas leaving.")
        # The glass connects early; Director must not be configured until watch.
        answer = await cinema.offer("offer", ready.revision)
        self.assertEqual(answer["sdp"], "answer")
        await asyncio.sleep(0.05)
        stream = cinema.session.stream
        self.assertFalse(any(m.get("type") == "configure" for m in stream.sent))
        self.assertFalse(cinema.watch(ready.revision + 7))
        self.assertTrue(cinema.watch(ready.revision))
        await asyncio.sleep(0.05)
        configure = next(m for m in stream.sent if m.get("type") == "configure")
        self.assertIn("Hot gas goes down.", configure["prompt"])
        await cinema.close()

    async def test_undirected_plan_keeps_cinema_call_shape(self):
        # `/cinema` is untouched: without a brief, FilmMaker.plan is called exactly as before.
        from unittest.mock import AsyncMock

        from gizmo_friend.cinema.plan import FilmBeat, FilmPlan, PreparedFilm
        from gizmo_friend.cinema.runtime import CinemaSession
        from test_cinema import FakeStream

        root = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(root.cleanup)
        plan = FilmPlan(title="Rocket", beats=[FilmBeat(narration="Go.", action="Lift.")], thread="t")
        maker = AsyncMock()
        maker.plan.return_value = plan
        maker.synthesize.return_value = PreparedFilm(plan, "https://audio.fal.media/t.wav", 3, b"wav")
        maker.upload_audio.return_value = "https://audio.fal.media/t.wav"
        events = []

        async def emit(event): events.append(event)
        session = CinemaSession(Path(root.name), "test", emit, maker=maker, stream_factory=FakeStream)
        await session.ask("Rocket")
        await asyncio.sleep(0.05)
        maker.plan.assert_awaited_once_with("Rocket", session.context)
        # A plain offer still starts the film, as the workbench expects.
        await session.offer("offer", session.revision)
        await asyncio.sleep(0.05)
        self.assertTrue(any(m.get("type") == "configure" for m in session.stream.sent))
        await session.close()

    def test_undelivered_marking_never_taints_a_completed_film(self):
        from unittest.mock import AsyncMock

        from gizmo_friend.cinema.runtime import CinemaSession

        root = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(root.cleanup)

        async def emit(event): pass
        session = CinemaSession(Path(root.name), "test", emit, maker=AsyncMock())
        session.context.extend([{"user": "How does a rocket launch?"},
                                {"completed_narration": "Gas goes down, rocket goes up."}])
        session._mark_undelivered()  # nothing pending: a completed film stays clean
        self.assertNotIn("undelivered", session.context[-1])
        session.pending = "How does a rocket launch?"
        session._mark_undelivered()
        self.assertIn("undelivered", session.context[0])


if __name__ == "__main__": unittest.main()
