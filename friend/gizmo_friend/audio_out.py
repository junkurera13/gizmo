"""Speaker-side bookkeeping for the realtime PCM stream."""

from __future__ import annotations


class Mouth:
    """Tracks what has been played so interruption and barge-in stay honest.

    The bytes themselves travel to the device over the body WebSocket; this
    only knows whether output is live and how much of it has gone out.
    """

    def __init__(self) -> None:
        self._cancelled = False
        self._played_ms = 0
        self._playing = False

    def cancel(self) -> None:
        """Drop anything not yet played. Interrupt / barge-in."""
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

    def speak_pcm(self, chunk: bytes) -> None:
        """Account for a 24 kHz 16-bit mono chunk that is going out to the device."""
        if self._cancelled:
            return
        self._played_ms += int(len(chunk) / 2 / 24000 * 1000)
