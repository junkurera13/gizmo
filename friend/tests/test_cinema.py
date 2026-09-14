import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from fastapi.testclient import TestClient
from gizmo_friend.cinema.device import DeviceFilmPlayer
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


class DevicePlayerTests(unittest.IsolatedAsyncioTestCase):
    def test_long_narration_uses_sequential_one_line_captions(self):
        from gizmo_friend.cinema.device import (
            MAX_DEVICE_CAPTION_CHARS,
            device_caption_timings,
        )

        narration = (
            "Deep underground, pressure keeps building until hot rock forces "
            "its way upward and the mountain finally erupts into the sky."
        )
        captions = device_caption_timings(
            [{"start": 10.0, "end": 16.0, "narration": narration}]
        )

        self.assertGreater(len(captions), 1)
        self.assertTrue(
            all(len(row["narration"]) <= MAX_DEVICE_CAPTION_CHARS for row in captions)
        )
        self.assertEqual(" ".join(row["narration"] for row in captions), narration)
        self.assertEqual(captions[0]["start"], 10.0)
        self.assertEqual(captions[-1]["end"], 16.0)
        self.assertTrue(
            all(
                left["end"] == right["start"]
                for left, right in zip(captions, captions[1:])
            )
        )

    def test_overflow_caption_pages_keep_every_word(self):
        from gizmo_friend.cinema.device import (
            MAX_DEVICE_CAPTION_CHARS,
            device_caption_timings,
            wrap_device_caption,
        )

        narration = (
            "Yes! Penguins also live in South America, southern Africa, Australia, "
            "New Zealand, and the Galapagos Islands. Not every penguin lives somewhere icy."
        )
        pages = wrap_device_caption(narration)
        self.assertGreater(len(pages), 1)
        self.assertTrue(all(len(page) <= MAX_DEVICE_CAPTION_CHARS for page in pages))
        self.assertEqual(" ".join(pages), narration)
        self.assertTrue(pages[-1].endswith("icy."))

        captions = device_caption_timings(
            [{"start": 0.0, "end": 12.66, "narration": narration}]
        )
        self.assertEqual(len(captions), len(pages))
        self.assertLess(captions[-1]["start"], 12.66)
        self.assertEqual(captions[-1]["end"], 12.66)

    async def test_caption_changes_at_narration_boundary_inside_cue(self):
        track = object()
        stream = SimpleNamespace(
            video_ready=None,
            closed=False,
            tracks={"video": track},
            relay=SimpleNamespace(subscribe=Mock(return_value=track)),
        )
        cinema = SimpleNamespace(
            stream=stream,
            prepared=SimpleNamespace(
                plan=SimpleNamespace(title="Volcano"),
                timings=[
                    {"start": 0.0, "end": 0.2, "narration": "Pressure builds."},
                    {"start": 0.2, "end": 0.3, "narration": "Then it erupts."},
                ],
            ),
            revision=3,
            mark_presented=Mock(),
            interrupt=AsyncMock(),
            finish=AsyncMock(),
        )
        acks = {}
        events = []

        async def send(event):
            events.append(event)
            if event.get("hold"):
                acks[(event["cue"], "motion")].set_result(True)

        player = DeviceFilmPlayer(cinema, None, send, acks)
        segment = SimpleNamespace(
            show=SimpleNamespace(still_url="/still.jpg", frames_url="/film.mjpeg"),
            pcm=b"\0" * 14_400,
        )

        async def capture(_track, queue, _prepared, _revision):
            await queue.put(segment)
            await queue.put(None)

        player.capture = capture
        await player.play(3)

        go = next(event for event in events if event.get("go"))
        self.assertEqual(go["text"], "Pressure builds.")
        self.assertIn(
            {"type": "line", "text": "Then it erupts."},
            events,
        )
        cinema.finish.assert_awaited_once_with(3)

    async def test_narration_prefill_precedes_next_cue_download(self):
        track = object()
        stream = SimpleNamespace(
            video_ready=None,
            closed=False,
            tracks={"video": track},
            relay=SimpleNamespace(subscribe=Mock(return_value=track)),
        )
        cinema = SimpleNamespace(
            stream=stream,
            prepared=SimpleNamespace(
                plan=SimpleNamespace(title="Ship"),
                timings=[],
            ),
            revision=2,
            mark_presented=Mock(),
            interrupt=AsyncMock(),
            finish=AsyncMock(),
        )
        acks = {}
        events = []

        async def send(event):
            events.append(event)
            if event.get("hold"):
                acks[(event["cue"], "motion")].set_result(True)

        player = DeviceFilmPlayer(cinema, None, send, acks)
        segment = SimpleNamespace(
            show=SimpleNamespace(still_url="/still.jpg", frames_url="/film.mjpeg"),
            pcm=b"\0\0",
        )

        async def capture(_track, queue, _prepared, _revision):
            await queue.put(segment)
            await queue.put(segment)
            await queue.put(None)

        player.capture = capture
        await player.play(2)

        first_go = next(
            index
            for index, event in enumerate(events)
            if event.get("go") and event["cue"] == 201
        )
        first_audio = next(
            index
            for index, event in enumerate(events)
            if event.get("type") == "audio"
        )
        second_hold = next(
            index
            for index, event in enumerate(events)
            if event.get("hold") and event["cue"] == 202
        )
        self.assertLess(first_go, first_audio)
        self.assertLess(first_audio, second_hold)
        cinema.finish.assert_awaited_once_with(2)

    async def test_failed_go_does_not_discard_the_live_fallback(self):
        track = object()
        stream = SimpleNamespace(
            video_ready=None,
            closed=False,
            tracks={"video": track},
            relay=SimpleNamespace(subscribe=Mock(return_value=track)),
        )
        cinema = SimpleNamespace(
            stream=stream,
            prepared=SimpleNamespace(
                plan=SimpleNamespace(title="Rocket"),
                timings=[],
            ),
            revision=4,
            mark_presented=Mock(),
            interrupt=AsyncMock(),
            finish=AsyncMock(),
        )
        acks = {}

        async def send(event):
            if event.get("hold"):
                acks[(event["cue"], "motion")].set_result(True)
            elif event.get("go"):
                raise RuntimeError("device disconnected before playback")

        player = DeviceFilmPlayer(
            cinema,
            store=None,
            send=send,
            acks=acks,
            on_failed=AsyncMock(),
        )
        segment = SimpleNamespace(
            show=SimpleNamespace(still_url="/still.jpg", frames_url="/film.mjpeg"),
            pcm=b"\0\0",
        )

        async def capture(_track, queue, _prepared, _revision):
            await queue.put(segment)
            await queue.put(None)

        player.capture = capture
        await player.play(4)

        cinema.mark_presented.assert_not_called()
        cinema.interrupt.assert_awaited_once()
        player.on_failed.assert_awaited_once()


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.root = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
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

    async def test_exhausted_session_rejects_the_ask_before_starting_work(self):
        self.session.turns = 8
        self.assertIs(await self.session.ask("Rocket"), False)
        self.assertIsNone(self.session.work)

    async def test_prepared_but_unplayed_film_is_not_future_context(self):
        await self.session.ask("Rocket")
        await self.until(lambda: self.session.prepared is not None)
        await self.session.interrupt()
        self.assertTrue(any("undelivered" in row for row in self.session.context))
        self.assertFalse(any("interrupted_plan" in row for row in self.session.context))
        await self.session.ask("A completely different question")
        await self.until(lambda: self.maker.plan.await_count == 2)
        context = self.maker.plan.await_args_list[-1].args[1]
        self.assertFalse(any("undelivered" in row for row in context))

    async def test_only_finished_narration_is_recorded_as_heard(self):
        await self.session.ask("Rocket")
        await self.until(lambda: self.session.prepared is not None)
        self.assertTrue(self.session.mark_presented(self.session.revision))
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
            tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as root,
            patch.dict(
                "os.environ",
                {
                    "RAILWAY_ENVIRONMENT_ID": "test",
                    "GIZMO_DEVICE_TOKEN": "test",
                    "GIZMO_DIRECTOR_ENABLED": "",
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
            tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as root,
            TestClient(app_factory(Path(root))) as client,
        ):
            self.assertEqual(
                client.post(
                    "/cinema/session", headers={"Origin": "https://unrelated.test"}
                ).status_code,
                403,
            )

    def open_preview(self, root, **extra):
        return patch.dict(
            "os.environ",
            {
                "RAILWAY_ENVIRONMENT_ID": "test",
                "GIZMO_DEVICE_TOKEN": "test",
                "GIZMO_DIRECTOR_ENABLED": "1",
                "GIZMO_DIRECTOR_TOKEN": "",
                "FAL_KEY": "test",
                "GEMINI_API_KEY": "test",
                **extra,
            },
        )

    def test_open_preview_when_enabled_without_token(self):
        with (
            tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as root,
            self.open_preview(root),
            TestClient(app_factory(Path(root))) as client,
        ):
            response = client.post(
                "/cinema/session", headers={"Origin": "http://testserver"}
            )
            self.assertEqual(response.status_code, 200)
            self.assertRegex(response.json()["key"], r"^[0-9a-f]{32}$")
            self.assertIn("gizmo_cinema=", response.headers["set-cookie"])

    def test_access_code_still_gates_when_token_set(self):
        with (
            tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as root,
            self.open_preview(root, GIZMO_DIRECTOR_TOKEN="s3cret"),
            TestClient(app_factory(Path(root))) as client,
        ):
            self.assertEqual(
                client.post(
                    "/cinema/session", headers={"Origin": "http://testserver"}
                ).status_code,
                401,
            )
            self.assertEqual(
                client.post(
                    "/cinema/session",
                    headers={
                        "Origin": "http://testserver",
                        "x-gizmo-access": "s3cret",
                    },
                ).status_code,
                200,
            )

    def test_embedded_session_identity_uses_key_param(self):
        # The oddware.xyz iframe is cross-site, so the strict cookie never
        # reaches it; the page passes its key explicitly instead.
        with (
            tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as root,
            self.open_preview(root),
            TestClient(app_factory(Path(root))) as client,
        ):
            key = client.post(
                "/cinema/session", headers={"Origin": "http://testserver"}
            ).json()["key"]
            client.cookies.clear()
            again = client.post(
                "/cinema/session",
                headers={"Origin": "http://testserver", "x-gizmo-cinema": key},
            )
            self.assertEqual(again.json()["key"], key)
            with client.websocket_connect(
                f"/cinema/ws?key={key}", headers={"Origin": "http://testserver"}
            ) as socket:
                self.assertEqual(socket.receive_json()["type"], "hello")


class DeviceEncodingTests(unittest.IsolatedAsyncioTestCase):
    def test_director_segment_uses_existing_device_media_contract(self):
        import io

        from gizmo_friend.brain.shows import ShowStore
        from gizmo_friend.cinema.device import FPS, encode_segment
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
            frames = store.mjpeg(segment.show.id, fps=FPS)
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
            self.assertFalse(segment.show.clip_path.is_file())

    def test_detailed_director_segment_adapts_to_device_byte_budget(self):
        from gizmo_friend.brain.shows import ShowStore
        from gizmo_friend.cinema.device import (
            DEVICE_JPEG_QUALITY,
            MAX_DEVICE_FRAME_BYTES,
            MAX_DEVICE_SEGMENT_BYTES,
            encode_segment,
        )
        from PIL import Image

        # Deterministic high-frequency color makes fixed-quality JPEG cues far
        # larger than the physical device can download during five seconds.
        pixels = bytes(
            (index * 73 + index // 97 * 29) % 256
            for index in range(320 * 240 * 3)
        )
        image = Image.frombytes("RGB", (320, 240), pixels)
        with tempfile.TemporaryDirectory() as root:
            store = ShowStore(
                Path(root) / "devices" / "test-device", device_id="test-device"
            )
            segment = encode_segment(
                [image] * 40,
                b"\x00\x00" * 120_000,
                store,
                "Detailed world",
            )
            self.assertLessEqual(segment.mjpeg_bytes, MAX_DEVICE_SEGMENT_BYTES)
            self.assertLessEqual(segment.max_jpeg_bytes, MAX_DEVICE_FRAME_BYTES)
            self.assertLess(segment.jpeg_quality, DEVICE_JPEG_QUALITY)
            self.assertEqual(
                store.mjpeg(segment.show.id, fps=8).path.stat().st_size,
                segment.mjpeg_bytes,
            )

    def test_director_frame_uses_only_the_real_caption_band(self):
        from gizmo_friend.cinema.device import CAPTION_BAND_HEIGHT, frame_image
        from PIL import Image

        source = Image.new("RGB", (640, 360), (220, 40, 30))
        image = frame_image(SimpleNamespace(to_image=lambda: source))
        self.assertEqual(image.getpixel((160, 240 - CAPTION_BAND_HEIGHT - 1)), (220, 40, 30))
        self.assertEqual(image.getpixel((160, 240 - CAPTION_BAND_HEIGHT)), (5, 17, 31))

    def test_device_jpeg_is_baseline_420(self):
        import io

        from gizmo_friend.cinema.device import jpeg_frame
        from PIL import Image

        image = Image.new("RGB", (320, 240), (40, 80, 120))
        encoded = jpeg_frame(image, quality=65)
        self.assertIn(b"\xff\xc0", encoded)
        self.assertNotIn(b"\xff\xc2", encoded)
        decoded = Image.open(io.BytesIO(encoded))
        self.assertEqual(decoded.size, (320, 240))
        self.assertFalse(decoded.info.get("progression"))
        self.assertEqual(
            [(component[1], component[2]) for component in decoded.layer],
            [(2, 2), (1, 1), (1, 1)],
        )

    async def test_capture_skips_frozen_director_preroll(self):
        import io
        import wave

        from gizmo_friend.brain.shows import ShowStore
        from gizmo_friend.cinema.device import FPS, DeviceFilmPlayer
        from PIL import Image

        class FakeFrame:
            def __init__(self, time, color, *, key_frame=True, is_corrupt=False):
                self.time = time
                self._image = Image.new("RGB", (640, 360), color)
                self.key_frame = key_frame
                self.is_corrupt = is_corrupt

            def to_image(self):
                return self._image.copy()

        class FakeTrack:
            def __init__(self, frames):
                self._frames = list(frames)
                self.stopped = False

            async def recv(self):
                if not self._frames:
                    await asyncio.sleep(30)
                    raise asyncio.CancelledError
                return self._frames.pop(0)

            def stop(self):
                self.stopped = True

        damaged = [
            FakeFrame(-0.04, (0, 255, 0), is_corrupt=True),
            FakeFrame(-0.02, (0, 0, 255), key_frame=False),
        ]
        frozen = [(i / 50, (10, 10, 10)) for i in range(8)]
        moving = [(0.2 + i / 12, (min(i * 12, 240), 40, 80)) for i in range(16)]
        track = FakeTrack(
            damaged + [FakeFrame(t, color) for t, color in frozen + moving]
        )
        wav = io.BytesIO()
        with wave.open(wav, "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(24000)
            audio.writeframes(b"\x00\x00" * 24000)
        prepared = SimpleNamespace(
            wav=wav.getvalue(),
            duration=1.0,
            plan=SimpleNamespace(title="Rocket"),
        )
        cinema = SimpleNamespace(revision=1)
        with tempfile.TemporaryDirectory() as root:
            store = ShowStore(Path(root) / "devices" / "test-device", device_id="test-device")
            player = DeviceFilmPlayer(cinema, store, AsyncMock(), {})
            queue = asyncio.Queue()
            await asyncio.wait_for(player.capture(track, queue, prepared, 1), 2)
            segment = queue.get_nowait()
            self.assertIsNotNone(segment)
            self.assertEqual(segment.frames, FPS)
            frames = store.mjpeg(segment.show.id, fps=FPS)
            data = frames.path.read_bytes()
            first = data[: data.index(b"\xff\xd9") + 2]
            image = Image.open(io.BytesIO(first))
            # Corrupt, pre-keyframe, and frozen preroll must all be gone.
            pixel = image.getpixel((160, 96))
            self.assertLess(abs(pixel[1] - 40), 10)
            self.assertLess(abs(pixel[2] - 80), 10)


class AudioTimelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_serial_beats_keep_exact_audio_and_measured_boundaries(self):
        import io
        import wave
        from types import SimpleNamespace

        from gizmo_friend.brain.narration import Narration
        from gizmo_friend.cinema.plan import FilmMaker

        maker = object.__new__(FilmMaker)
        inflight = 0
        peak = 0
        order = []

        async def narrate(text):
            nonlocal inflight, peak
            inflight += 1
            peak = max(peak, inflight)
            order.append(text)
            await asyncio.sleep(0)
            inflight -= 1
            words = max(len(text.split()), 1)
            return Narration(
                text=text, pcm=b"\x01\x00" * (2400 * words), model="test", latency_seconds=0
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
        self.assertEqual(peak, 1)
        self.assertEqual(order, ["0 1 2"])
        self.assertEqual(prepared.duration, 0.3)
        self.assertEqual([row["start"] for row in prepared.timings], [0, 0.1, 0.2])
        with wave.open(io.BytesIO(prepared.wav), "rb") as audio:
            self.assertEqual(audio.readframes(audio.getnframes()), b"\x01\x00" * 7200)
        self.assertEqual(prepared.audio_url, "https://audio.fal.media/test.wav")
        synthesized = await maker.synthesize(plan)
        self.assertEqual(synthesized.audio_url, "")
        self.assertEqual(synthesized.wav, prepared.wav)

    async def test_directed_beats_stay_one_tts_call(self):
        from gizmo_friend.brain.narration import Narration
        from gizmo_friend.cinema.plan import DirectedFilmPlan, FilmMaker

        maker = object.__new__(FilmMaker)
        order = []

        async def narrate(text):
            order.append(text)
            words = max(len(text.split()), 1)
            return Narration(
                text=text, pcm=b"\x01\x00" * (2400 * words), model="test", latency_seconds=0
            )

        maker.voice = SimpleNamespace(narrate=narrate)
        plan = DirectedFilmPlan(
            title="Test",
            beats=[FilmBeat(narration=str(n), action="move") for n in range(4)],
            thread="next",
        )
        prepared = await maker.synthesize(plan)
        self.assertEqual(order, ["0 1 2 3"])
        self.assertEqual(prepared.duration, 0.4)


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

        root = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
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
            tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as root,
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
            tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as root,
            TestClient(app_factory(Path(root))) as client,
        ):
            page = client.get("/cinema")
            script = client.get("/static/cinema.js")
            self.assertEqual(page.status_code, 200)
            self.assertNotIn('id="sound"', page.text)
            for control in ("previous", "next", "select"):
                self.assertNotIn(f'id="{control}"', page.text)
            self.assertEqual(script.status_code, 200)
            self.assertNotIn("$('sound')", script.text)
            self.assertIn("video.muted = false", script.text)
            self.assertEqual(client.get("/static/cinema.css").status_code, 200)
