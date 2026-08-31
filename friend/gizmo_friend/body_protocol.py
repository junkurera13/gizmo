"""Stick / mic / camera events. Firmware will speak this later; laptop keys do now."""

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
