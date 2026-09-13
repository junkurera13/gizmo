import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from gizmo_friend.cinema.demo import DEMO_MOMENTS, DeviceDemo, DemoStep, step_timings


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


def fake_segment(pcm_seconds=0.5):
    return SimpleNamespace(
        show=SimpleNamespace(
            still_url="/shows/d/x.jpg", frames_url="/shows/d/x.mjpeg"
        ),
        pcm=b"\x01\x00" * int(24_000 * pcm_seconds),
    )


class DeviceDemoTest(unittest.IsolatedAsyncioTestCase):
    async def test_ptt_release_thinks_then_plays_canned_film(self):
        socket = FakeSocket()
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
                    for event in socket.sent:
                        if (
                            event.get("type") == "glass"
                            and event.get("hold")
                            and event["cue"] not in acked
                        ):
                            acked.add(event["cue"])
                            socket.script.append(
                                {
                                    "type": "glass_ready",
                                    "cue": event["cue"],
                                    "kind": "motion",
                                    "ok": True,
                                }
                            )
                    await asyncio.sleep(0.005)
                while demo.playback and not demo.playback.done():
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

    async def test_second_ptt_runs_the_followup_step(self):
        socket = FakeSocket()
        with tempfile.TemporaryDirectory() as tmp:
            demo = DeviceDemo(socket, Path(tmp), "demo-device", "antarctica")
            for i in range(2):
                demo.steps[i] = DemoStep(
                    0.01, "v.mp4", "a.wav", f"S{i}", ((0.0, "x"),)
                )
                demo._segments[i] = [fake_segment(0.1)]
            run = asyncio.create_task(demo.run())
            try:
                for _ in range(2):
                    socket.script.append({"type": "ptt", "active": False})
                    while demo.playback is None or not demo.playback.done():
                        for event in socket.sent:
                            if event.get("type") == "glass" and event.get("hold"):
                                cue = event["cue"]
                                socket.script.append(
                                    {
                                        "type": "glass_ready",
                                        "cue": cue,
                                        "kind": "motion",
                                        "ok": True,
                                    }
                                )
                                socket.sent.remove(event)
                        await asyncio.sleep(0.005)
                    demo.playback = None
            finally:
                run.cancel()
                try:
                    await run
                except asyncio.CancelledError:
                    pass
        subjects = [e["subject"] for e in socket.sent if e.get("go")]
        self.assertEqual(subjects, ["S0", "S1"])

    def test_step_timings_chains_beats(self):
        timings = step_timings(DEMO_MOMENTS["antarctica"][0])
        self.assertEqual(timings[0]["start"], 0.0)
        self.assertEqual(timings[1]["end"], timings[2]["start"])
        self.assertGreater(timings[-1]["end"], timings[-1]["start"])

    def test_unknown_moment_name_absent(self):
        self.assertNotIn("troy", DEMO_MOMENTS)


if __name__ == "__main__":
    unittest.main()
