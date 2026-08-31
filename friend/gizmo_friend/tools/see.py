from __future__ import annotations

import asyncio
import os

from gizmo_friend.body_protocol import WorldCamera

# Real hardware takes a beat to point, focus, and look. Holding the seeing
# state open keeps the viewfinder on the glass long enough to aim.
_DWELL_ENV = "GIZMO_SEE_DWELL_S"


async def see(camera: WorldCamera, image: str | None = None) -> dict:
    """Name what's in the outward frame in one beat. Fast. Does not block listen."""
    del image  # body provides the frame
    try:
        dwell = float(os.environ.get(_DWELL_ENV, "2.5"))
    except ValueError:
        dwell = 2.5
    if dwell > 0:
        await asyncio.sleep(dwell)
    frame = camera.grab()
    if frame.hint:
        beat = _one_beat(frame.hint)
        return {"beat": beat, "has_image": frame.image is not None}
    if frame.image:
        return {"beat": "something in the frame. I see it.", "has_image": True}
    return {"beat": "dark. nothing to name yet.", "has_image": False}


def _one_beat(hint: str) -> str:
    text = hint.strip()
    if not text:
        return "dark. nothing to name yet."
    # one beat, not a caption dump
    first = text.split(".")[0].strip()
    if len(first) > 80:
        first = first[:77] + "…"
    if first[0].islower():
        first = first[0].upper() + first[1:]
    return first if first.endswith(".") else first + "."
