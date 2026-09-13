import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import gizmo_friend.cinema.demo as demo_module
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

    async def test_question_mid_film_rolls_followup_with_no_thinking(self):
        socket = FakeSocket()
        demo_module.FOLLOWUP_GAP_SECONDS = 0.05
        self.addCleanup(setattr, demo_module, "FOLLOWUP_GAP_SECONDS", 4.7)
        with tempfile.TemporaryDirectory() as tmp:
            demo = DeviceDemo(socket, Path(tmp), "demo-device", "antarctica")
            demo.steps[0] = DemoStep(0.01, "v.mp4", "a.wav", "S0", ((0.0, "x"),))
            demo.steps[1] = DemoStep(0.0, "v2.mp4", "a2.wav", "S1", ((0.0, "y"),))
            # Film one must outlast the question + gap.
            demo._segments[0] = [fake_segment(3.0), fake_segment(3.0)]
            demo._segments[1] = [fake_segment(0.2)]
            run = asyncio.create_task(demo.run())
            acked = set()
            try:
                socket.script.append({"type": "ptt", "active": False})
                # Wait until film one is actually on screen.
                deadline = asyncio.get_running_loop().time() + 10
                while demo.playing_step != 0:
                    self.assertLess(asyncio.get_running_loop().time(), deadline)
                    await ack_holds(socket, acked)
                    await asyncio.sleep(0.005)
                # The interruption: ask over the still-playing film.
                socket.script.append({"type": "ptt", "active": True})
                await asyncio.sleep(0.02)
                self.assertFalse(
                    any(e.get("type") == "interrupted" for e in socket.sent),
                    "pressing PTT mid-film must not interrupt the take",
                )
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
        demo_module.FOLLOWUP_GAP_SECONDS = 0.05
        demo_module.FOLLOWUP_HOLD_SECONDS = 5.0
        self.addCleanup(setattr, demo_module, "FOLLOWUP_GAP_SECONDS", 4.7)
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
                # The late ask rides the frozen frame into film two.
                socket.script.append({"type": "ptt", "active": True})
                await asyncio.sleep(0.02)
                socket.script.append({"type": "ptt", "active": False})
                while not any(
                    e.get("go") and e.get("subject") == "S1" for e in socket.sent
                ):
                    self.assertLess(asyncio.get_running_loop().time(), deadline)
                    await ack_holds(socket, acked)
                    await asyncio.sleep(0.005)
                clears = [
                    e
                    for e in socket.sent
                    if e.get("type") == "glass" and e.get("viewing") is False
                ]
                self.assertEqual(
                    len(clears), 1, "no home flash between film one and two"
                )
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

    def test_unknown_moment_name_absent(self):
        self.assertNotIn("troy", DEMO_MOMENTS)


if __name__ == "__main__":
    unittest.main()
