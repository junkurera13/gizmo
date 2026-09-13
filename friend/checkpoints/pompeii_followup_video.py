"""Generate the kid-safe visual continuation for the Pompeii follow-up."""
from __future__ import annotations

import asyncio
import os
import wave
from pathlib import Path

from dotenv import load_dotenv

from gizmo_friend.cinema.plan import FilmMaker
from gizmo_friend.cinema.stream import DirectorStream
from checkpoints.pompeii_demo import record_film


ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "friend" / "gizmo_friend" / "static"
AUDIO = STATIC / "demo-pompeii-followup-refreshed.wav"
OUTPUT = STATIC / "demo-pompeii-followup.mp4"

PROMPT = """
Create one continuous 16:9 continuation of a gentle, colorful, kid-friendly
flat-vector animated film about ancient Pompeii. Begin on a soft cross-section
of grey volcanic ash covering a Roman room. Show the ash layer acting like a
protective blanket around red and gold painted walls, keeping rain and wind
away. Then transition to two friendly modern archaeologists in straw hats
carefully brushing the ash aside to reveal a bright intact bird-and-vine wall
painting. End with a slow, warm camera push toward the restored painting.
Match a polished children's educational animation: rounded shapes, warm light,
subtle parallax, expressive but restrained movement, no text on screen. Never
show injury, bodies, remains, panic, fire, or frightening imagery.
""".strip()


async def main() -> None:
    load_dotenv(ROOT / ".env")
    if not os.environ.get("FAL_KEY", "").strip():
        raise RuntimeError("FAL_KEY is missing from the repository .env")
    with wave.open(str(AUDIO)) as source:
        duration = source.getnframes() / source.getframerate()
    maker = FilmMaker()
    stream = DirectorStream(os.environ["FAL_KEY"], lambda event: asyncio.sleep(0))
    try:
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
        await record_film(stream, duration + 0.35, OUTPUT)
        print(f"published {OUTPUT.name} ({duration + 0.35:.1f}s)")
    finally:
        await stream.close()
        await maker.close()


if __name__ == "__main__":
    asyncio.run(main())
