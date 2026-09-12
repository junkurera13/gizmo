"""Render the Antarctica Oddity demo through the real Cinema pipeline."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from checkpoints.pompeii_demo import record_film, synthesize_with_leads
from gizmo_friend.cinema.plan import FilmBeat, FilmMaker, FilmPlan
from gizmo_friend.cinema.stream import DirectorStream
from gizmo_friend.oddity.demo_voice import DEMO_NARRATION_STYLE

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "friend" / "gizmo_friend" / "static"

PLAN = FilmPlan(
    title="The Continent at the Bottom of the World",
    thread="Locate Antarctica, then travel from its ice sheet to its coast.",
    relation="new",
    beats=[
        FilmBeat(
            narration=(
                "Antarctica is the icy continent at the very bottom of Earth. "
                "On a globe, it wraps around the South Pole."
            ),
            action=(
                "A geographically accurate, friendly illustrated globe floats in deep blue space. "
                "The camera smoothly rotates south and Antarctica glows bright white at the bottom, "
                "clearly shaped as one continent around the South Pole. No labels or written text."
            ),
        ),
        FilmBeat(
            narration=(
                "Most of it is covered by a huge sheet of ice, with bright glaciers, "
                "tall mountains, and deep blue cracks."
            ),
            action=(
                "Continue in one fluid camera move, diving from the globe into a wide cinematic view "
                "of Antarctica's enormous white ice sheet, blue glaciers, rugged mountains, and safe "
                "distant crevasses sparkling in soft polar sunlight."
            ),
        ),
        FilmBeat(
            narration=(
                "Along the coast, you can see floating icebergs and penguins, while the middle "
                "is a cold, windy white desert."
            ),
            action=(
                "Glide to an Antarctic coast with turquoise water, sculpted floating icebergs, and a "
                "small cheerful group of penguins. Then sweep inland toward a vast, windy white plateau. "
                "Polished colorful children's educational film, gentle motion, no text."
            ),
        ),
    ],
)


async def main() -> None:
    load_dotenv(ROOT / ".env")
    maker = FilmMaker()
    stream = DirectorStream(os.environ["FAL_KEY"], lambda event: asyncio.sleep(0))
    try:
        maker.voice.style = DEMO_NARRATION_STYLE
        prepared = await synthesize_with_leads(maker, PLAN)
        print(f"narration: {prepared.duration:.1f}s")
        (STATIC / "demo-antarctica.wav").write_bytes(prepared.wav)
        audio_url = await maker.upload_audio(prepared.wav)
        await stream.connect()
        stream.send(
            {
                "type": "configure",
                "protocol_version": 1,
                "prompt_version": 1,
                "resolution": "480p",
                "aspect_ratio": "16:9",
                "memory": 12,
                "prompt": PLAN.direction()
                + "\nAudio timeline in seconds: "
                + json.dumps(prepared.timings),
                "audio_url": audio_url,
            }
        )
        await asyncio.wait_for(stream.first_frame.wait(), 45)
        await record_film(
            stream,
            prepared.duration + 0.35,
            STATIC / "demo-antarctica.mp4",
        )
        print("published demo-antarctica.mp4 + .wav")
    finally:
        await stream.close()
        await maker.close()


if __name__ == "__main__":
    asyncio.run(main())
