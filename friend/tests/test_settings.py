from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from gizmo_friend.body_protocol import Navigate, Power, Select
from gizmo_friend.brain.images import NullImageProvider
from gizmo_friend.brain.memory import NullMemoryProvider
from gizmo_friend.brain.reasoning import NullReasoningProvider
from gizmo_friend.brain.show_budget import ShowBudget
from gizmo_friend.session import GizmoSession
from gizmo_friend.settings import DeviceSettings
from gizmo_friend.states import State


class DeviceSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "settings.json"
        self.settings = DeviceSettings(self.path)

    def test_up_from_home_opens_volume(self):
        self.assertEqual(self.settings.navigate("up"), "opened")
        self.assertTrue(self.settings.open)
        self.assertEqual(self.settings.focus, "volume")
        self.assertFalse(self.settings.adjusting)

    def test_down_from_home_is_ignored(self):
        self.assertEqual(self.settings.navigate("down"), "ignored")
        self.assertFalse(self.settings.open)

    def test_row_move_and_exit(self):
        self.settings.navigate("up")
        self.assertEqual(self.settings.navigate("up"), "handled")
        self.assertEqual(self.settings.focus, "brightness")
        self.assertEqual(self.settings.navigate("down"), "handled")
        self.assertEqual(self.settings.focus, "volume")
        self.assertEqual(self.settings.navigate("down"), "closed")
        self.assertFalse(self.settings.open)

    def test_select_adjusts_and_persists_volume(self):
        self.settings.navigate("up")
        self.assertTrue(self.settings.select())
        before = self.settings.volume
        self.settings.navigate("up")
        self.assertEqual(self.settings.volume, min(10, before + 1))
        loaded = DeviceSettings(self.path)
        self.assertEqual(loaded.volume, self.settings.volume)
        self.assertFalse(loaded.open)


class SettingsSessionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        transport = SimpleNamespace(**{
            name: AsyncMock() for name in [
                "send_text", "close", "interrupt", "submit_tool_output",
                "send_image", "clear_pending_image", "begin_audio",
                "send_audio", "commit_audio",
            ]
        })
        self.friend = GizmoSession(
            self.root / "devices" / "test-settings",
            user_id="test-settings",
            gemini_key="",
            memory_provider=NullMemoryProvider(),
            reasoning_provider=NullReasoningProvider(),
            image_provider=NullImageProvider(),
            show_budget=ShowBudget(self.root),
            transport_factory=lambda handle: transport,
            idle_sleep_s=0,
        )
        self.friend.machine.state = State.LISTENING
        self.friend._transport = transport
        self.friend._connected = True
        self.friend._touch()
        self.queue = self.friend.subscribe()
        self.addAsyncCleanup(self.friend.close)

    def settings_events(self):
        items = []
        while not self.queue.empty():
            items.append(self.queue.get_nowait())
        return [event for event in items if event.get("type") == "settings"]

    async def test_home_up_emits_open_settings(self):
        await self.friend.handle(Navigate(direction="up"))
        events = self.settings_events()
        self.assertEqual(len(events), 1)
        self.assertTrue(events[0]["open"])
        self.assertEqual(events[0]["focus"], "volume")
        self.assertFalse(events[0]["adjusting"])

    async def test_select_toggles_adjust_then_volume_nudge(self):
        await self.friend.handle(Navigate(direction="up"))
        await self.friend.handle(Select())
        start = self.friend.settings.volume
        await self.friend.handle(Navigate(direction="down"))
        events = self.settings_events()
        last = events[-1]
        self.assertTrue(last["adjusting"])
        self.assertEqual(last["focus"], "volume")
        self.assertEqual(last["volume"], max(0, start - 1))

    async def test_power_off_closes_settings(self):
        await self.friend.handle(Navigate(direction="up"))
        self.assertTrue(self.friend.settings.open)
        await self.friend.handle(Power(on=False))
        self.assertFalse(self.friend.settings.open)
        events = self.settings_events()
        self.assertFalse(events[-1]["open"])
