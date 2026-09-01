from __future__ import annotations

from typing import Protocol


class FutureMediaProvider(Protocol):
    """Reserved boundary for Adaptive Media; deliberately unimplemented in V1."""

    async def show_image(self, prompt: str) -> str: ...

    async def show_video(self, prompt: str) -> str: ...
