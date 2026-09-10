import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from gizmo_friend.cinema.plan import FilmBeat, FilmPlan, PreparedFilm
from gizmo_friend.cinema.runtime import CinemaSession
from gizmo_friend.server import app_factory


class FakeStream:
    def __init__(self, key, event, *, hold=None):
        self.event = event
        self.first_frame = asyncio.Event()
        self.video_ready = asyncio.Event()
        self.audio_ready = asyncio.Event()
        self.connect_started = asyncio.Event()
        self.latest_frame = None
        self.closed = False
        self.sent = []
        self.tracks = {}
        self._hold = hold

    async def connect(self):
        self.connect_started.set()
        if self._hold is not None:
            await self._hold.wait()
        if self.closed:
            return
        self.video_ready.set()
        self.audio_ready.set()

    async def answer(self, sdp, kind, **kwargs):
        async with asyncio.timeout(1):
            await self.video_ready.wait()
        if self.closed:
            raise RuntimeError("Film ended")
        return {"sdp": "answer", "type": "answer"}

    def send(self, event):
        self.sent.append(event)
        self.first_frame.set()

    async def close(self):
        self.closed = True
        self.video_ready.set()
        self.audio_ready.set()
        if self._hold is not None:
            self._hold.set()


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.root = tempfile.TemporaryDirectory()
        self.addCleanup(self.root.cleanup)
        self.plan = FilmPlan(
            title="Rocket",
            beats=[
                FilmBeat(
                    narration="Hot gas goes down. The rocket goes up.",
                    action="Show exhaust moving down as the rocket rises.",
                )
            ],
            thread="propulsion",
        )
        self.maker = AsyncMock()
        self.maker.plan.return_value = self.plan
        self.maker.synthesize.return_value = PreparedFilm(
            self.plan, "", 10, b"fake"
        )
        self.maker.upload_audio = AsyncMock(
            return_value="https://audio.fal.media/test.wav"
        )
        self.maker.upload.upload = AsyncMock(
            return_value="https://image.fal.media/frame.jpg"
        )
        self.emit = AsyncMock()
        self.session = CinemaSession(
            Path(self.root.name),
            "key",
            self.emit,
            maker=self.maker,
            stream_factory=FakeStream,
        )
        self.addAsyncCleanup(self.session.close)

    async def until(self, predicate):
        async with asyncio.timeout(1):
            while not predicate():
                await asyncio.sleep(0.001)

    async def test_only_configures_when_viewer_is_attached(self):
        await self.session.ask("Why does it fly?")
        await self.until(lambda: self.session.prepared is not None)
        stream = self.session.stream
        self.assertEqual(stream.sent, [])
        await self.session.offer("offer", self.session.revision)
        await self.until(lambda: bool(stream.sent))
        self.assertEqual(
            stream.sent[0]["audio_url"], "https://audio.fal.media/test.wav"
        )
        self.assertIn(self.plan.beats[0].narration, stream.sent[0]["prompt"])

    async def test_interruption_cancels_preparation_and_provider(self):
        started = asyncio.Event()

        async def slow(plan):
            started.set()
            await asyncio.Event().wait()

        self.maker.synthesize.side_effect = slow
        await self.session.ask("Rocket")
        await started.wait()
        stream = self.session.stream
        work = self.session.work
        await self.session.interrupt()
        self.assertTrue(work.done())
        self.assertTrue(stream.closed)
        self.assertEqual(stream.sent, [])

    def _ready_emitted(self):
        return any(call.args[0].get("type") == "ready" for call in self.emit.await_args_list)

    async def test_offer_during_tts_does_not_configure_before_wav(self):
        synthesizing = asyncio.Event()
        release = asyncio.Event()

        async def slow(plan):
            synthesizing.set()
            await release.wait()
            return PreparedFilm(self.plan, "", 10, b"fake")

        self.maker.synthesize.side_effect = slow
        await self.session.ask("Rocket")
        await synthesizing.wait()
        await self.session.offer("offer", self.session.revision)
        self.assertEqual(self.session.stream.sent, [])
        self.assertFalse(self._ready_emitted())
        release.set()
        await self.until(lambda: bool(self.session.stream.sent))
        self.assertEqual(
            self.session.stream.sent[0]["audio_url"], "https://audio.fal.media/test.wav"
        )

    async def test_does_not_configure_until_audio_url_exists(self):
        uploaded = asyncio.Event()
        release = asyncio.Event()

        async def slow_upload(wav):
            uploaded.set()
            await release.wait()
            return "https://audio.fal.media/test.wav"

        self.maker.upload_audio.side_effect = slow_upload
        await self.session.ask("Rocket")
        await uploaded.wait()
        await self.until(lambda: self.session.prepared is not None)
        self.assertFalse(self._ready_emitted())
        self.assertEqual(self.session.stream.sent, [])
        release.set()
        await self.until(self._ready_emitted)
        await self.session.offer("offer", self.session.revision)
        await self.until(lambda: bool(self.session.stream.sent))
        self.assertEqual(
            self.session.stream.sent[0]["audio_url"], "https://audio.fal.media/test.wav"
        )

    async def test_ready_does_not_wait_for_director_connect(self):
        hold = asyncio.Event()
        session = CinemaSession(
            Path(self.root.name) / "slow-connect",
            "key",
            self.emit,
            maker=self.maker,
            stream_factory=lambda key, event: FakeStream(key, event, hold=hold),
        )
        self.addAsyncCleanup(session.close)
        await session.ask("Rocket")
        await self.until(
            lambda: any(
                call.args[0].get("type") == "ready" for call in self.emit.await_args_list
            )
        )
        self.assertEqual(session.stream.sent, [])
        hold.set()
        await session.offer("offer", session.revision)
        await self.until(lambda: bool(session.stream.sent))
        self.assertEqual(
            session.stream.sent[0]["audio_url"], "https://audio.fal.media/test.wav"
        )

    async def test_continuation_image_overlaps_tts_and_survives_only_if_current(self):
        synthesizing = asyncio.Event()
        image_started = asyncio.Event()
        image_release = asyncio.Event()
        order = []

        async def slow_synthesize(plan):
            order.append("synthesize_start")
            synthesizing.set()
            await asyncio.Event().wait()

        async def slow_image(data, mime, file_name=""):
            order.append("image_start")
            image_started.set()
            await image_release.wait()
            order.append("image_done")
            return "https://image.fal.media/frame.jpg"

        (Path(self.root.name) / "last-frame.jpg").write_bytes(b"jpeg")
        self.plan.relation = "continue"
        self.maker.synthesize.side_effect = slow_synthesize
        self.maker.upload.upload.side_effect = slow_image
        await self.session.ask("Go on")
        await synthesizing.wait()
        await image_started.wait()
        self.assertEqual(set(order), {"synthesize_start", "image_start"})
        stream = self.session.stream
        await self.session.interrupt()
        image_release.set()
        await asyncio.sleep(0)
        self.assertTrue(stream.closed)
        self.assertEqual(stream.sent, [])

    async def test_overlapping_continuation_image_is_attached_after_final_wav(self):
        synthesizing = asyncio.Event()
        release = asyncio.Event()
        image_started = asyncio.Event()

        async def slow_synthesize(plan):
            synthesizing.set()
            await release.wait()
            return PreparedFilm(self.plan, "", 10, b"fake")

        async def image(data, mime, file_name=""):
            image_started.set()
            return "https://image.fal.media/frame.jpg"

        (Path(self.root.name) / "last-frame.jpg").write_bytes(b"jpeg")
        self.plan.relation = "continue"
        self.maker.synthesize.side_effect = slow_synthesize
        self.maker.upload.upload.side_effect = image
        await self.session.ask("Go on")
        await synthesizing.wait()
        await image_started.wait()
        self.assertEqual(self.session.stream.sent, [])
        release.set()
        await self.until(self._ready_emitted)
        await self.session.offer("offer", self.session.revision)
        await self.until(lambda: bool(self.session.stream.sent))
        self.assertEqual(
            self.session.stream.sent[0]["image_url"],
            "https://image.fal.media/frame.jpg",
        )
        self.assertEqual(
            self.session.stream.sent[0]["audio_url"],
            "https://audio.fal.media/test.wav",
        )

    async def test_stale_offer_after_interrupt_does_not_configure(self):
        await self.session.ask("Rocket")
        await self.until(self._ready_emitted)
        first = self.session.revision
        stream = self.session.stream
        await self.session.ask("Why oxygen?")
        await self.until(
            lambda: self.session.revision != first and self.session.stream is not stream
        )
        with self.assertRaises(ValueError):
            await self.session.offer("offer", first)
        self.assertEqual(stream.sent, [])

    async def test_interrupt_during_audio_upload_does_not_configure(self):
        uploaded = asyncio.Event()

        async def slow_upload(wav):
            uploaded.set()
            await asyncio.Event().wait()

        self.maker.upload_audio.side_effect = slow_upload
        await self.session.ask("Rocket")
        await uploaded.wait()
        stream = self.session.stream
        work = self.session.work
        await self.session.interrupt()
        self.assertTrue(work.done())
        self.assertTrue(stream.closed)
        self.assertEqual(stream.sent, [])

    async def test_old_finish_cannot_complete_new_film(self):
        await self.session.ask("Rocket")
        first = self.session.revision
        await self.session.ask("Why does it need oxygen?")
        await self.session.finish(first)
        self.assertIsNotNone(self.session.work)
        self.assertFalse(
            any("completed_narration" in row for row in self.session.context)
        )

    async def test_only_finished_narration_is_recorded_as_heard(self):
        await self.session.ask("Rocket")
        await self.until(lambda: self.session.prepared is not None)
        await self.session.interrupt()
        self.assertTrue(any("interrupted_plan" in row for row in self.session.context))
        self.assertFalse(
            any("completed_narration" in row for row in self.session.context)
        )
        await self.session.ask("Go on")
        await self.until(lambda: self.session.prepared is not None)
        await self.session.finish(self.session.revision)
        self.assertEqual(
            self.session.context[-1]["completed_narration"], self.plan.narration
        )


class RouteTests(unittest.TestCase):
    def test_cloud_preview_cannot_start_without_explicit_enablement(self):
        with (
            tempfile.TemporaryDirectory() as root,
            patch.dict(
                "os.environ",
                {
                    "RAILWAY_ENVIRONMENT_ID": "test",
                    "GIZMO_DEVICE_TOKEN": "test",
                    "GIZMO_DIRECTOR_ENABLED": "",
                    "ODDITY_LAB_TOKEN": "",
                },
            ),
            TestClient(app_factory(Path(root))) as client,
        ):
            self.assertEqual(client.get("/cinema").status_code, 200)
            response = client.post(
                "/cinema/session", headers={"Origin": "http://testserver"}
            )
            self.assertEqual(response.status_code, 503)
            self.assertEqual(
                client.post(
                    "/cinema/offer", json={"sdp": "x", "revision": 1}
                ).status_code,
                403,
            )

    def test_cross_origin_provisioning_is_rejected(self):
        with (
            tempfile.TemporaryDirectory() as root,
            TestClient(app_factory(Path(root))) as client,
        ):
            self.assertEqual(
                client.post(
                    "/cinema/session", headers={"Origin": "https://unrelated.test"}
                ).status_code,
                403,
            )


class DeviceEncodingTests(unittest.TestCase):
    def test_director_segment_uses_existing_device_media_contract(self):
        import io

        from gizmo_friend.brain.shows import ShowStore
        from gizmo_friend.cinema.device import encode_segment
        from PIL import Image

        with tempfile.TemporaryDirectory() as root:
            store = ShowStore(
                Path(root) / "devices" / "test-device", device_id="test-device"
            )
            images = [Image.new("RGB", (320, 240), (n * 10, 40, 70)) for n in range(12)]
            pcm = b"\x00\x00" * 24000
            segment = encode_segment(images, pcm, store, "Rocket")
            self.assertEqual(segment.frames, 12)
            self.assertEqual(segment.pcm, pcm)
            frames = store.mjpeg(segment.show.id)
            data = frames.path.read_bytes()
            self.assertTrue(data.startswith(b"\xff\xd8"))
            # Baseline 4:2:0 is accepted by the ESP ROM decoder; 4:4:4 was the old failure.
            first = data[: data.index(b"\xff\xd9") + 2]
            image = Image.open(io.BytesIO(first))
            self.assertEqual(image.size, (320, 240))
            self.assertEqual(
                [(component[1], component[2]) for component in image.layer],
                [(2, 2), (1, 1), (1, 1)],
            )


class AudioTimelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_parallel_beats_keep_exact_audio_and_measured_boundaries(self):
        import io
        import wave
        from types import SimpleNamespace

        from gizmo_friend.brain.narration import Narration
        from gizmo_friend.cinema.plan import FilmMaker

        maker = object.__new__(FilmMaker)
        entered = []
        barrier = asyncio.Event()

        async def narrate(text):
            entered.append(text)
            if len(entered) == 3:
                barrier.set()
            await barrier.wait()
            return Narration(
                text=text, pcm=b"\x01\x00" * 2400, model="test", latency_seconds=0
            )

        maker.voice = SimpleNamespace(narrate=narrate)
        maker.upload = SimpleNamespace(
            upload=AsyncMock(return_value="https://audio.fal.media/test.wav")
        )
        plan = FilmPlan(
            title="Test",
            beats=[FilmBeat(narration=str(n), action="move") for n in range(3)],
            thread="next",
        )
        async with asyncio.timeout(1):
            prepared = await maker.prepare(plan)
        self.assertEqual(prepared.duration, 0.3)
        self.assertEqual([row["start"] for row in prepared.timings], [0, 0.1, 0.2])
        with wave.open(io.BytesIO(prepared.wav), "rb") as audio:
            self.assertEqual(audio.readframes(audio.getnframes()), b"\x01\x00" * 7200)
        self.assertEqual(prepared.audio_url, "https://audio.fal.media/test.wav")
        synthesized = await maker.synthesize(plan)
        self.assertEqual(synthesized.audio_url, "")
        self.assertEqual(synthesized.wav, prepared.wav)


class FakeFilmSession:
    def __init__(self):
        self.asked = []
        self.interrupted = 0
        self.closed = False
        self.viewer = asyncio.Event()
        self.revision = 1
        self.prepared = None
        self.stream = None

    async def ask(self, text, **kwargs):
        self.asked.append(text)

    async def interrupt(self):
        self.interrupted += 1

    async def close(self):
        self.closed = True


class FriendCinemaTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_asks_the_existing_runtime_and_stop_interrupts(self):
        from gizmo_friend.brain.shows import ShowStore
        from gizmo_friend.cinema.capability import FriendCinema
        from gizmo_friend.cinema.routes import FilmBudget

        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        path = Path(root.name)
        session = FakeFilmSession()
        events = []
        cinema = FriendCinema(
            directory=path / "cinema" / "desk",
            device_id="desk",
            store=ShowStore(path / "devices" / "desk", device_id="desk"),
            emit=events.append,
            budget=FilmBudget(path),
            session=session,
        )
        result = await cinema.start("Why do rockets fly?")
        self.assertEqual(result, {"ok": True, "status": "preparing"})
        self.assertEqual(session.asked, ["Why do rockets fly?"])
        self.assertTrue(cinema.active)
        await cinema.stop()
        self.assertFalse(cinema.active)
        self.assertEqual(session.interrupted, 1)
        await cinema.close()
        self.assertTrue(session.closed)


class FriendSocketTests(unittest.TestCase):
    def test_director_device_env_does_not_hijack_ws(self):
        with (
            tempfile.TemporaryDirectory() as root,
            patch.dict(
                "os.environ",
                {
                    "GEMINI_API_KEY": "test",
                    "FAL_KEY": "test",
                    "GIZMO_DIRECTOR_DEVICE": "desk-1",
                    "GIZMO_DEVICE_TOKEN": "",
                },
                clear=False,
            ),
            TestClient(app_factory(Path(root))) as client,
            client.websocket_connect(
                "/ws",
                headers={"x-gizmo-device": "desk-1", "x-gizmo-glass-cues": "1"},
            ) as socket,
        ):
            hello = socket.receive_json()
            self.assertEqual(hello["type"], "hello")
            self.assertNotEqual(hello.get("transport"), "director")
            glass = socket.receive_json()
            self.assertEqual(glass["type"], "glass")
            self.assertFalse(glass.get("viewing"))

    def test_cinema_page_and_static_still_load(self):
        with (
            tempfile.TemporaryDirectory() as root,
            TestClient(app_factory(Path(root))) as client,
        ):
            self.assertEqual(client.get("/cinema").status_code, 200)
            self.assertEqual(client.get("/static/cinema.js").status_code, 200)
            self.assertEqual(client.get("/static/cinema.css").status_code, 200)
