"""Audio-out interface. Realtime PCM now; a Cartesia mouth can replace this later."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable

AudioHandler = Callable[[bytes], Awaitable[None]]
TextHandler = Callable[[str], Awaitable[None]]


class Mouth(ABC):
    """Whatever actually hits the speaker.

    Realtime path pushes PCM from the model.
    A later Cartesia mouth would take text (speak_text) and stream PCM itself.
    """

    @abstractmethod
    def cancel(self) -> None:
        """Drop anything not yet played. Interrupt / barge-in."""

    @abstractmethod
    async def speak_pcm(self, chunk: bytes) -> None:
        """Push a 24 kHz 16-bit mono PCM chunk."""

    @abstractmethod
    async def speak_text(self, text: str) -> None:
        """Text that would be spoken. Fake transport and future TTS use this."""

    @property
    @abstractmethod
    def played_ms(self) -> int: ...

    @abstractmethod
    def mark_playing(self) -> None: ...

    @abstractmethod
    def mark_idle(self) -> None: ...


class BroadcastMouth(Mouth):
    def __init__(
        self,
        on_pcm: AudioHandler | None = None,
        on_text: TextHandler | None = None,
    ) -> None:
        self._on_pcm = on_pcm
        self._on_text = on_text
        self._cancelled = False
        self._played_ms = 0
        self._playing = False

    def set_handlers(self, on_pcm: AudioHandler | None, on_text: TextHandler | None) -> None:
        self._on_pcm = on_pcm
        self._on_text = on_text

    def cancel(self) -> None:
        self._cancelled = True
        self._playing = False

    def mark_playing(self) -> None:
        self._cancelled = False
        self._playing = True

    def mark_idle(self) -> None:
        self._playing = False

    @property
    def played_ms(self) -> int:
        return self._played_ms

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    async def speak_pcm(self, chunk: bytes) -> None:
        if self._cancelled:
            return
        # 16-bit mono 24 kHz
        self._played_ms += int(len(chunk) / 2 / 24000 * 1000)
        if self._on_pcm:
            await self._on_pcm(chunk)

    async def speak_text(self, text: str) -> None:
        if self._cancelled or not text:
            return
        if self._on_text:
            await self._on_text(text)

    async def wait_cancel_window(self) -> None:
        await asyncio.sleep(0)
