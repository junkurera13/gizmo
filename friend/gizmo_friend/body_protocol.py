"""Physical device events. Firmware will speak this later; the simulator does now.

THE CONTROL CONTRACT (locked with Jun, 2026-09-01)

Oddity OS reports raw physical events and never assigns conversational
meaning to them. The session controller interprets the events, so the
simulator and real hardware behave identically.

  on/off toggle (top)       -> Power(on=True/False)
      Off is hard-off. On cold-boots the device.

  push-to-talk button        -> PushToTalk(active=True/False) on press/release
      The session controller decides what a press means while power is on:
        tap  (released before ~0.35s)  -> sleep if awake, wake if asleep
        hold (past ~0.35s)             -> mic hot, talk; release commits
      The mic streams only while a hold is live.

  up/down rocker             -> Navigate(up/down)
  select button              -> Select
      Selects the focused item or interrupts current output. It does not
      open the camera; camera capture is requested by the agent's see path.
  camera frame               -> Frame  (image and/or hint)
  mic audio while holding    -> MicChunk (pcm16, 24kHz mono)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Union


class BodyEventType(str, Enum):
    SELECT = "select"
    POWER = "power"
    PUSH_TO_TALK = "ptt"
    NAVIGATE = "navigate"
    FRAME = "frame"
    MIC = "mic"
    TEXT = "text"  # laptop keyboard stand-in for a spoken line


@dataclass(frozen=True)
class Select:
    type: str = BodyEventType.SELECT.value


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


BodyEvent = Union[Select, Power, PushToTalk, Navigate, Frame, MicChunk, TextLine]


@dataclass
class WorldCamera:
    """Outward frame. Inject from the laptop until the ESP32 camera exists."""

    _frame: Frame = field(default_factory=Frame)

    def inject(self, image: bytes | None = None, hint: str | None = None, mime: str = "image/jpeg") -> None:
        self._frame = Frame(image=image, hint=hint, mime=mime)

    def grab(self) -> Frame:
        return self._frame
