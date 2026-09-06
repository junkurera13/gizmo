"""Device settings world: brightness and volume.

The body reports raw up/down/select. Friend owns the menu so the simulator,
the laptop reference client, and firmware stay on one behavior. Bodies render
the snapshot and apply the two analog outputs (glass backlight, speaker gain).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from gizmo_friend.body_protocol import BODY_SETTING_STEPS

SETTING_STEPS = BODY_SETTING_STEPS
DEFAULT_STEP = 8
SETTINGS_FOCI = ("brightness", "volume")

NavigateResult = Literal["ignored", "opened", "handled", "closed"]


def _clamp_step(value: object) -> int:
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DEFAULT_STEP
    return max(0, min(SETTING_STEPS, number))


class DeviceSettings:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.open = False
        self.focus = "volume"
        self.adjusting = False
        self.brightness = DEFAULT_STEP
        self.volume = DEFAULT_STEP
        self._load()

    def snapshot(self) -> dict[str, Any]:
        return {
            "type": "settings",
            "open": self.open,
            "focus": self.focus,
            "adjusting": self.adjusting,
            "brightness": self.brightness,
            "volume": self.volume,
            "steps": SETTING_STEPS,
        }

    def public(self) -> dict[str, Any]:
        payload = self.snapshot()
        payload.pop("type")
        return payload

    def close_panel(self) -> bool:
        changed = self.open or self.adjusting or self.focus != "volume"
        self.open = False
        self.adjusting = False
        self.focus = "volume"
        return changed

    def navigate(self, direction: str) -> NavigateResult:
        if direction not in {"up", "down"}:
            return "ignored"
        if self.open:
            if self.adjusting:
                self._nudge(1 if direction == "up" else -1)
                return "handled"
            if direction == "up":
                if self.focus == "volume":
                    self.focus = "brightness"
                return "handled"
            if self.focus == "brightness":
                self.focus = "volume"
                return "handled"
            self.close_panel()
            return "closed"
        if direction == "up":
            self.open = True
            self.adjusting = False
            self.focus = "volume"
            return "opened"
        return "ignored"

    def select(self) -> bool:
        if not self.open:
            return False
        self.adjusting = not self.adjusting
        return True

    def _nudge(self, delta: int) -> None:
        if self.focus == "brightness":
            self.brightness = _clamp_step(self.brightness + delta)
        else:
            self.volume = _clamp_step(self.volume + delta)
        self._save()

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(raw, dict):
            return
        self.brightness = _clamp_step(raw.get("brightness", self.brightness))
        self.volume = _clamp_step(raw.get("volume", self.volume))

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"brightness": self.brightness, "volume": self.volume}
        self.path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
