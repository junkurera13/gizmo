"""Stick / mic / camera events. Firmware will speak this later; laptop keys do now.

THE CONTROL CONTRACT (locked with Jun, 2026-08-31)

The body is dumb: it reports raw physical events and never interprets
them. All meaning lives in the brain (session.py), so the simulator and
the real hardware behave identically. The physical controls map to raw
events like this:

  on/off toggle (top-left)  -> Power(on=True/False)
      Shutdown and boot. Off is off: firmware sends Power(off), saves,
      and powers down. Flipping it on is the cold boot: chime + boot
      animation, every time.

  push-to-talk button        -> PushToTalk(active=True/False) on press/release
      The brain decides what a press means:
        tap  (released before ~0.35s)  -> sleep if awake, wake if asleep
        hold (past ~0.35s)             -> mic hot, talk; release commits
      The mic streams only while a hold is live.

  trackball click            -> Click
      One click: select / interrupt / close camera.
      Two fast clicks (~0.45s, brain-detected): open the camera.

  trackball hold             -> Hold   (reported, currently reserved;
      reaching a parent happens through conversation, not a gesture)
  trackball roll             -> Navigate(up/down/left/right)
  camera frame               -> Frame  (image and/or hint)
  mic audio while holding    -> MicChunk (pcm16, 24kHz mono)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Union


class BodyEventType(str, Enum):
    CLICK = "click"
    HOLD = "hold"
    POWER = "power"
    PUSH_TO_TALK = "ptt"
    NAVIGATE = "navigate"
    FRAME = "frame"
    MIC = "mic"
    TEXT = "text"  # laptop keyboard stand-in for a spoken line


@dataclass(frozen=True)
class Click:
    type: str = BodyEventType.CLICK.value


@dataclass(frozen=True)
class Hold:
    type: str = BodyEventType.HOLD.value


@dataclass(frozen=True)
class Power:
    on: bool
    type: str = BodyEventType.POWER.value


@dataclass(frozen=True)
class PushToTalk:
    active: bool
    type: str = BodyEventType.PUSH_TO_TALK.value


@dataclass(frozen=True)
class Navigate:
    direction: str
    type: str = BodyEventType.NAVIGATE.value


@dataclass(frozen=True)
class Frame:
    image: bytes | None = None
    hint: str | None = None
    mime: str = "image/jpeg"
    type: str = BodyEventType.FRAME.value


@dataclass(frozen=True)
class MicChunk:
    pcm: bytes
    type: str = BodyEventType.MIC.value


@dataclass(frozen=True)
class TextLine:
    text: str
    type: str = BodyEventType.TEXT.value


BodyEvent = Union[Click, Hold, Power, PushToTalk, Navigate, Frame, MicChunk, TextLine]


@dataclass
class WorldCamera:
    """Outward frame. Inject from the laptop until the ESP32 camera exists."""

    _frame: Frame = field(default_factory=Frame)

    def inject(self, image: bytes | None = None, hint: str | None = None, mime: str = "image/jpeg") -> None:
        self._frame = Frame(image=image, hint=hint, mime=mime)

    def grab(self) -> Frame:
        return self._frame
