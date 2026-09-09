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
      Friend owns Settings. From home, up opens the brightness/volume panel.
      Inside it, up/down move the hovered row or change the active level;
      down past Volume returns home. Camera is a body-local world: a body
      that opens Camera consumes those rocker edges and does not forward
      them, so "up from Camera" cannot be mistaken for "open Settings".
  select button              -> Select
      In Settings, selects or confirms a row. Otherwise selects the focused
      item or interrupts current output. It does not open the camera.
      While asleep, any button wakes him and does nothing else.
  reserved visual input      -> Frame  (image and/or hint)
      Current body clients do not emit this. See needs its own explicit
      interaction; it must never be inferred from push-to-talk.
  mic audio while holding    -> MicChunk (pcm16, 24kHz mono)
  held picture decoded       -> GlassReady(cue, kind, ok)
      The body's reply to a glass event carrying "cue" and "hold": the
      still or motion is on the device and waiting for "go". Storytelling
      uses it to change the picture on the sentence, not on the download.

These are Python controller events, not serialized WebSocket messages.
On /ws, microphone input and speaker output both use type="audio" with
base64 PCM in "pcm". Input type="mic" is a compatibility alias only.
See body/README.md for the JSON wire contract and PTT ordering.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Union


# Wire-level constants shared by Friend's health/hello responses. Firmware can
# reject an incompatible brain before it reports a physical input.
BODY_PROTOCOL_VERSION = 1
BODY_AUDIO_SAMPLE_RATE_HZ = 24_000
BODY_AUDIO_CHANNELS = 1
BODY_AUDIO_SAMPLE_FORMAT = "pcm_s16le"
BODY_CAMERA_MAX_WIDTH = 640
BODY_CAMERA_MAX_HEIGHT = 480
BODY_CAMERA_MAX_BYTES = 128 * 1024
BODY_SETTING_STEPS = 10


class BodyEventType(str, Enum):
    SELECT = "select"
    POWER = "power"
    PUSH_TO_TALK = "ptt"
    NAVIGATE = "navigate"
    FRAME = "frame"
    MIC = "mic"  # Internal event name; canonical /ws message type is "audio".
    TEXT = "text"  # laptop keyboard stand-in for a spoken line
    GLASS_READY = "glass_ready"


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


@dataclass(frozen=True)
class GlassReady:
    cue: int
    kind: str = "still"  # "still" or "motion"
    ok: bool = True
    type: str = BodyEventType.GLASS_READY.value


BodyEvent = Union[Select, Power, PushToTalk, Navigate, Frame, MicChunk, TextLine, GlassReady]


@dataclass
class WorldCamera:
    """Latest body-camera snapshot, held only until the current PTT turn ends."""

    _frame: Frame = field(default_factory=Frame)

    def inject(self, image: bytes | None = None, hint: str | None = None, mime: str = "image/jpeg") -> None:
        self._frame = Frame(image=image, hint=hint, mime=mime)

    def grab(self) -> Frame:
        return self._frame
