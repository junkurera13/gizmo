"""Late stills must be timed before later glass events, not after the media wait."""
import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

spec = importlib.util.spec_from_file_location(
    "story_checkpoint", Path(__file__).parents[1] / "checkpoints/story_continuity.py"
)
checkpoint = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checkpoint)


class TimingTests(unittest.IsolatedAsyncioTestCase):
    async def test_collector_keeps_reading_after_speech_finishes(self):
        queue = asyncio.Queue()
        still_consumed = asyncio.Event()
        friend = SimpleNamespace(current_show=None, _director_task=None,
                                 _show_tasks=set())

        async def media():
            await queue.put({"type": "glass", "still": "first.jpg"})
            # Collector must observe this while run_turn awaits this media task.
            async with asyncio.timeout(1):
                while not queue.empty():
                    await asyncio.sleep(0)
            still_consumed.set()
            await asyncio.sleep(0.03)
            await queue.put({"type": "glass", "still": "first.jpg", "clip": "first.mp4"})

        async def handle(event):
            await queue.put({"type": "state", "state": "listening"})
            friend._show_tasks.add(asyncio.create_task(media()))

        friend.handle = handle
        provider = SimpleNamespace(calls=[])
        with tempfile.TemporaryDirectory() as directory:
            result = await checkpoint.run_turn(friend, queue, provider, provider,
                                               provider, "story", Path(directory), 1)
        self.assertTrue(still_consumed.is_set())
        glass = [event for event in result["events"] if event["type"] == "glass"]
        self.assertGreater(glass[1]["seconds"] - glass[0]["seconds"], 0.02)
