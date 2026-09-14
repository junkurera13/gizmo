import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import gizmo_friend.cinema.demo as demo_module
from gizmo_friend.cinema.demo import (
    DEMO_MOMENTS,
    DeviceDemo,
    DemoStep,
    pad_demo_timeline,
    spoken_seconds,
    step_timings,
)
from gizmo_friend.cinema.device import MAX_DEVICE_CAPTION_CHARS, device_caption_timings


class FakeSocket:
    def __init__(self):
        self.script = []
        self.sent = []
        self.accepted = False

    async def accept(self):
        self.accepted = True

    async def send_json(self, event):
        self.sent.append(event)

    async def receive_json(self):
        while not self.script:
            await asyncio.sleep(0.005)
        return self.script.pop(0)


def fake_segment(pcm_seconds=0.5, show_id="x"):
    return SimpleNamespace(
        show=SimpleNamespace(
            still_url=f"/shows/d/{show_id}.jpg", frames_url=f"/shows/d/{show_id}.mjpeg"
        ),
        pcm=b"\x01\x00" * int(24_000 * pcm_seconds),
    )


async def ack_holds(socket, seen):
    for event in list(socket.sent):
        if (
            event.get("type") == "glass"
            and event.get("hold")
            and event["cue"] not in seen
        ):
            seen.add(event["cue"])
            socket.script.append(
                {
                    "type": "glass_ready",
                    "cue": event["cue"],
                    "kind": "motion",
                    "ok": True,
                }
            )


class DeviceDemoTest(unittest.IsolatedAsyncioTestCase):
    async def test_ptt_release_thinks_then_plays_canned_film(self):
        socket = FakeSocket()
        demo_module.FOLLOWUP_HOLD_SECONDS = 0.05
        self.addCleanup(setattr, demo_module, "FOLLOWUP_HOLD_SECONDS", 15.0)
        with tempfile.TemporaryDirectory() as tmp:
            demo = DeviceDemo(socket, Path(tmp), "demo-device", "antarctica")
            demo.steps[0] = DemoStep(
                0.05, "v.mp4", "a.wav", "Antarctica", ((0.0, "Ice."),)
            )
            demo._segments[0] = [fake_segment(), fake_segment()]
            run = asyncio.create_task(demo.run())
            try:
                socket.script.append({"type": "ptt", "active": True})
                await asyncio.sleep(0.02)
                socket.script.append({"type": "ptt", "active": False})

                acked = set()
                deadline = asyncio.get_running_loop().time() + 10
                while len(acked) < 2:
                    self.assertLess(asyncio.get_running_loop().time(), deadline)
                    await ack_holds(socket, acked)
                    await asyncio.sleep(0.005)
                while demo.step_task and not demo.step_task.done():
                    await asyncio.sleep(0.01)
            finally:
                run.cancel()
                try:
                    await run
                except asyncio.CancelledError:
                    pass

        states = [e["state"] for e in socket.sent if e.get("type") == "state"]
        self.assertIn("thinking", states)
        self.assertIn("talking", states)
        self.assertEqual(states[-1], "listening")
        holds = [e for e in socket.sent if e.get("hold")]
        gos = [e for e in socket.sent if e.get("go")]
        self.assertEqual([e["cue"] for e in holds], [101, 102])
        self.assertEqual(len(gos), 2)
        self.assertTrue(all(e["subject"] == "Antarctica" for e in gos))
        audio = [e for e in socket.sent if e.get("type") == "audio"]
        self.assertGreater(len(audio), 0)
        self.assertEqual(
            [e for e in socket.sent if e.get("type") == "glass"][-1]["viewing"],
            False,
        )
        # An unanswered film one resets the sequence once the window lapses.
        self.assertEqual(demo.step_index, 0)

    async def test_question_mid_film_pauses_then_thinks_into_followup(self):
        socket = FakeSocket()
        demo_module.FOLLOWUP_THINK_SECONDS = 0.05
        self.addCleanup(setattr, demo_module, "FOLLOWUP_THINK_SECONDS", 3.0)
        with tempfile.TemporaryDirectory() as tmp:
            demo = DeviceDemo(socket, Path(tmp), "demo-device", "antarctica")
            demo.steps[0] = DemoStep(0.01, "v.mp4", "a.wav", "S0", ((0.0, "x"),))
            demo.steps[1] = DemoStep(0.0, "v2.mp4", "a2.wav", "S1", ((0.0, "y"),))
            demo._segments[0] = [fake_segment(3.0), fake_segment(3.0)]
            demo._segments[1] = [fake_segment(0.2)]
            run = asyncio.create_task(demo.run())
            acked = set()
            try:
                socket.script.append({"type": "ptt", "active": False})
                deadline = asyncio.get_running_loop().time() + 10
                while demo.playing_step != 0:
                    self.assertLess(asyncio.get_running_loop().time(), deadline)
                    await ack_holds(socket, acked)
                    await asyncio.sleep(0.005)
                socket.script.append({"type": "ptt", "active": True})
                await asyncio.sleep(0.02)
                self.assertTrue(
                    any(e.get("type") == "interrupted" for e in socket.sent),
                    "pressing PTT mid-film must mute and freeze immediately",
                )
                self.assertIsNone(demo.playing_step)
                socket.script.append({"type": "ptt", "active": False})
                while not any(
                    e.get("go") and e.get("subject") == "S1" for e in socket.sent
                ):
                    self.assertLess(asyncio.get_running_loop().time(), deadline)
                    await ack_holds(socket, acked)
                    await asyncio.sleep(0.005)
                while demo.followup_task and not demo.followup_task.done():
                    await ack_holds(socket, acked)
                    await asyncio.sleep(0.005)
            finally:
                run.cancel()
                try:
                    await run
                except asyncio.CancelledError:
                    pass

        states = [e["state"] for e in socket.sent if e.get("type") == "state"]
        self.assertEqual(states.count("thinking"), 1)
        subjects = [e["subject"] for e in socket.sent if e.get("go")]
        self.assertEqual(subjects[:1] + subjects[-1:], ["S0", "S1"])
        self.assertIn(201, acked)

    async def test_held_frame_covers_a_late_followup_ask(self):
        socket = FakeSocket()
        demo_module.FOLLOWUP_THINK_SECONDS = 0.05
        demo_module.FOLLOWUP_HOLD_SECONDS = 5.0
        self.addCleanup(setattr, demo_module, "FOLLOWUP_THINK_SECONDS", 3.0)
        self.addCleanup(setattr, demo_module, "FOLLOWUP_HOLD_SECONDS", 15.0)
        with tempfile.TemporaryDirectory() as tmp:
            demo = DeviceDemo(socket, Path(tmp), "demo-device", "antarctica")
            demo.steps[0] = DemoStep(0.01, "v.mp4", "a.wav", "S0", ((0.0, "x"),))
            demo.steps[1] = DemoStep(0.0, "v2.mp4", "a2.wav", "S1", ((0.0, "y"),))
            demo._segments[0] = [fake_segment(0.2)]
            demo._segments[1] = [fake_segment(0.2)]
            run = asyncio.create_task(demo.run())
            acked = set()
            try:
                socket.script.append({"type": "ptt", "active": False})
                deadline = asyncio.get_running_loop().time() + 10
                # Film one finishes with no ask — its last frame must hold.
                while not demo.held_frame:
                    self.assertLess(asyncio.get_running_loop().time(), deadline)
                    await ack_holds(socket, acked)
                    await asyncio.sleep(0.005)
                clears = [
                    e
                    for e in socket.sent
                    if e.get("type") == "glass" and e.get("viewing") is False
                ]
                self.assertEqual(len(clears), 1)  # only the connect-time clear
                # The late ask freezes, then paints, then rolls film two.
                socket.script.append({"type": "ptt", "active": True})
                await asyncio.sleep(0.02)
                socket.script.append({"type": "ptt", "active": False})
                while not any(
                    e.get("go") and e.get("subject") == "S1" for e in socket.sent
                ):
                    self.assertLess(asyncio.get_running_loop().time(), deadline)
                    await ack_holds(socket, acked)
                    await asyncio.sleep(0.005)
                thinking_clears = [
                    e
                    for e in socket.sent
                    if e.get("type") == "glass" and e.get("viewing") is False
                ]
                self.assertEqual(len(thinking_clears), 1)
                while demo.followup_task and not demo.followup_task.done():
                    await ack_holds(socket, acked)
                    await asyncio.sleep(0.005)
            finally:
                run.cancel()
                try:
                    await run
                except asyncio.CancelledError:
                    pass

        self.assertEqual(demo.step_index, 0)

    def test_step_timings_chains_beats(self):
        timings = step_timings(DEMO_MOMENTS["antarctica"][0])
        self.assertEqual(timings[0]["start"], 0.0)
        self.assertEqual(timings[1]["end"], timings[2]["start"])
        self.assertGreater(timings[-1]["end"], timings[-1]["start"])
        spoken = spoken_seconds(DEMO_MOMENTS["antarctica"][0])
        self.assertIsNotNone(spoken)
        self.assertAlmostEqual(timings[-1]["end"], spoken)

    def test_followup_captions_page_every_word_to_speech(self):
        step = DEMO_MOMENTS["antarctica"][1]
        spoken = spoken_seconds(step)
        self.assertIsNotNone(spoken)
        self.assertLess(spoken, 20.0)
        narration = " ".join(text for _, text in step.beats)
        captions = device_caption_timings(step_timings(step, duration=spoken))
        self.assertGreater(len(captions), 1)
        self.assertTrue(
            all(len(row["narration"]) <= MAX_DEVICE_CAPTION_CHARS for row in captions)
        )
        self.assertEqual(" ".join(row["narration"] for row in captions), narration)
        self.assertAlmostEqual(captions[0]["start"], 0.0)
        self.assertAlmostEqual(captions[-1]["end"], spoken)
        for row in captions:
            self.assertLess(row["start"], spoken)
        self.assertIn("icy", captions[-1]["narration"])

    def test_pad_demo_timeline_fills_a_short_last_cue(self):
        from PIL import Image

        from gizmo_friend.cinema.device import FPS, PCM_BYTES_PER_SECOND, SEGMENT_SECONDS

        last = Image.new("RGB", (320, 240), (9, 9, 9))
        images = [Image.new("RGB", (320, 240), (n, 0, 0)) for n in range(16)] + [last]
        pcm = b"\x00\x01" * 24_000 * 2  # 2s of audio
        padded, pcm_out = pad_demo_timeline(images, pcm)
        cue = FPS * SEGMENT_SECONDS
        self.assertEqual(len(padded) % cue, 0)
        self.assertGreaterEqual(len(padded), cue)
        self.assertEqual(padded[-1].tobytes(), last.tobytes())
        self.assertEqual(len(pcm_out), len(padded) * (PCM_BYTES_PER_SECOND // FPS))

    def test_pad_demo_timeline_covers_narration_longer_than_video(self):
        from PIL import Image

        from gizmo_friend.cinema.device import FPS, SEGMENT_SECONDS

        images = [Image.new("RGB", (320, 240), (1, 2, 3)) for _ in range(8)]
        pcm = b"\x00\x00" * 24_000 * 7
        padded, _pcm_out = pad_demo_timeline(images, pcm)
        self.assertGreaterEqual(len(padded), 7 * FPS)
        self.assertEqual(len(padded) % (FPS * SEGMENT_SECONDS), 0)

    def test_demo_decode_filter_uses_bilinear_cover(self):
        from gizmo_friend.cinema.demo import _decode_filter
        from gizmo_friend.cinema.device import FILM_CONTENT_SIZE

        width, height = FILM_CONTENT_SIZE
        self.assertEqual(
            _decode_filter(),
            f"fps=8,scale={width}:{height}:force_original_aspect_ratio=increase:flags=bilinear,"
            f"crop={width}:{height}:exact=1",
        )

    def test_unknown_moment_name_absent(self):
        self.assertNotIn("troy", DEMO_MOMENTS)


if __name__ == "__main__":
    unittest.main()
