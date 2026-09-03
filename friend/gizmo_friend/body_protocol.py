"""Physical device events. Firmware will speak this later; the simulator does now.

THE CONTROL CONTRACT (locked with Jun, 2026-09-01)

Oddity OS reports raw physical events and never assigns conversational
meaning to them. The session controller interprets the events, so the
simulator and real hardware behave identically.

  on/off toggle (top)       -> Power(on=True/False)
      Off is hard-off. On cold-boots the device.

  push-to-talk button        -> PushToTalk(active=True/False) on press/release
      One meaning: down, he listens; up, he answers. A press while asleep
      wakes him and the same press keeps listening. There is no tap
      gesture and no sleep button; sleep is idle-only (see idle_sleep_s).
      The mic streams only while the button is down.

  up/down rocker             -> Navigate(up/down)
  select button              -> Select
      Selects the focused item or interrupts current output. It does not
      open the camera; camera frames arrive independently from Oddity OS.
      While asleep, any button wakes him and does nothing else.
  camera frame               -> Frame  (image and/or hint)
  mic audio while holding    -> MicChunk (pcm16, 24kHz mono)

These are Python controller events, not serialized WebSocket messages.
On /ws, microphone input and speaker output both use type="audio" with
base64 PCM in "pcm". Input type="mic" is a compatibility alias only.
See body/README.md for the JSON wire contract and PTT ordering.
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
    MIC = "mic"  # Internal event name; canonical /ws message type is "audio".
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
    """Latest body-camera snapshot, held only until the current PTT turn ends."""

    _frame: Frame = field(default_factory=Frame)

    def inject(self, image: bytes | None = None, hint: str | None = None, mime: str = "image/jpeg") -> None:
        self._frame = Frame(image=image, hint=hint, mime=mime)

    def grab(self) -> Frame:
        return self._frame
