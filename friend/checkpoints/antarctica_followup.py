"""Render the short penguin follow-up with Umbriel and a matching world film."""
from __future__ import annotations

import asyncio
import os
import wave
from pathlib import Path

from dotenv import load_dotenv

from checkpoints.plant_demo import trim_silence
from checkpoints.pompeii_demo import record_film
from gizmo_friend.brain.narration import narration_provider_from_env
from gizmo_friend.cinema.plan import FilmMaker
from gizmo_friend.cinema.stream import DirectorStream
from gizmo_friend.oddity.demo_voice import DEMO_NARRATION_STYLE
from gizmo_friend.voice import AGENT_VOICE

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "friend" / "gizmo_friend" / "static"
AUDIO = STATIC / "demo-antarctica-followup-gizmo.wav"
VIDEO = STATIC / "demo-antarctica-followup.mp4"

REPLY = (
    "Yes! Penguins also live in South America, southern Africa, Australia, New Zealand, "
    "and the Galapagos Islands. Not every penguin lives somewhere icy."
)

PROMPT = """
Create a short, continuous 16:9 extension to a colorful, gentle children's
educational film about penguins. Begin on a friendly illustrated globe, then
move smoothly between five glowing coastal locations in sync with the
narration: southern South America with Magellanic penguins, southern Africa
with African penguins, southern Australia and New Zealand with little blue
penguins, and the green volcanic Galapagos Islands near the equator with
Galapagos penguins. End on the globe showing that these places are spread
through the Southern Hemisphere. Use a polished flat-vector animation style,
bright ocean blues, warm sunlight, cute but anatomically recognizable
penguins, gentle camera motion, and clean transitions. Keep every scene
kid-friendly. No danger, hunting, injury, climate disaster, crowds, flags,
captions, labels, or other written text.
""".strip()


async def main() -> None:
    load_dotenv(ROOT / ".env")
    if not os.environ.get("GEMINI_API_KEY", "").strip():
        raise RuntimeError("GEMINI_API_KEY is missing from the repository .env")
    if not os.environ.get("FAL_KEY", "").strip():
        raise RuntimeError("FAL_KEY is missing from the repository .env")

    voice = narration_provider_from_env(voice=AGENT_VOICE, style=DEMO_NARRATION_STYLE)
    maker = FilmMaker()
    stream = DirectorStream(os.environ["FAL_KEY"], lambda event: asyncio.sleep(0))
    try:
        narration = await voice.narrate(REPLY)
        if narration is None:
            raise RuntimeError("The Umbriel narration did not arrive")
        pcm = trim_silence(narration.pcm)
        with wave.open(str(AUDIO), "wb") as output:
            output.setparams((1, 2, 24_000, 0, "NONE", "not compressed"))
            output.writeframes(pcm)

        audio_url = await maker.upload_audio(AUDIO.read_bytes())
        await stream.connect()
        stream.send({
            "type": "configure",
            "protocol_version": 1,
            "prompt_version": 1,
            "resolution": "480p",
            "aspect_ratio": "16:9",
            "memory": 12,
            "prompt": PROMPT,
            "audio_url": audio_url,
        })
        await asyncio.wait_for(stream.first_frame.wait(), 45)
        duration = len(pcm) / 48_000
        await record_film(stream, duration + 0.35, VIDEO)
        print(
            f"published {AUDIO.name} + {VIDEO.name} "
            f"({duration:.2f}s, {AGENT_VOICE}, {narration.model})"
        )
    finally:
        await stream.close()
        await maker.close()
        await voice.close()


if __name__ == "__main__":
    asyncio.run(main())
