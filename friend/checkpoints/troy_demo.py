"""Render the Troy Oddity demo in the established illustrated Cinema style."""
from __future__ import annotations

import asyncio
import os
import wave
from pathlib import Path

from dotenv import load_dotenv

from checkpoints.pompeii_demo import record_film
from gizmo_friend.cinema.plan import FilmMaker
from gizmo_friend.cinema.stream import DirectorStream


ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "friend" / "gizmo_friend" / "static"

STORY_AUDIO = STATIC / "demo-troy-gizmo.wav"
STORY_VIDEO = STATIC / "demo-troy-story.mp4"
FOLLOWUP_AUDIO = STATIC / "demo-troy-followup-gizmo.wav"
FOLLOWUP_VIDEO = STATIC / "demo-troy-followup.mp4"

STORY_PROMPT = """
Create a continuous 16:9 children's educational animation about the famous
story of Troy, synchronized closely to the supplied narration. Match the
established Pompeii and Antarctica demo style: polished flat-vector storybook
illustration, rounded simplified shapes, layered paper-cut depth, warm
terracotta and gold against rich sea blues, soft cinematic lighting, gentle
parallax, smooth deliberate camera moves, and clean motivated transitions.
This must be a genuinely animated film with changing shots and moving subjects,
not a pan or zoom across still artwork. Keep character designs and the wooden
horse consistent between every shot. No photorealism, 3D-rendered realism,
captions, labels, logos, modern objects, frightening faces, injuries, fighting,
weapons in action, fire, or violence.

NON-NEGOTIABLE WOODEN HORSE DESIGN: the horse is an inanimate carved wooden
statue, never a living animal. Its four straight wooden legs are permanently
bolted to one broad rectangular timber carrier platform. Four round wooden
wheels are attached to the carrier platform, like a heavy parade cart. The
horse's legs, knees, hooves, head, mouth, eyes, and tail remain completely rigid
in every frame. It never walks, steps, trots, blinks, breathes, or moves any body
part. When transported, people pull ropes attached to the carrier; only the
carrier rolls forward and its four wheels rotate.

Visual timeline:
- 0–7.5 seconds: establish ancient Troy as a colorful walled coastal city. A
  distant Greek camp lies outside while tiny calm figures move between tents;
  show history-book scale without battle or danger.
- 7.5–15.2 seconds: Greek ships visibly sail away across the blue sea toward
  the horizon. Reveal a huge handcrafted wooden horse left alone on the quiet
  shore, rigidly mounted on its broad four-wheeled timber carrier, as flags and
  sails move gently in the breeze. The statue itself is perfectly motionless.
- 15.2–20.7 seconds: in a new daylight shot, cheerful Trojan townspeople roll
  the same rigid horse and its carrier through the opening city gates. People
  pull the carrier with ropes, its four wheels turn, and the crowd walks
  naturally; absolutely no part of the wooden horse moves.
- 20.7–24.3 seconds: transition to a clear storybook cutaway of the horse.
  Several Greek soldiers are visibly crouched inside the wooden body, waiting
  quietly. Keep it gentle and non-threatening.
- 24.3–30.8 seconds: night falls over Troy. The hidden soldiers carefully climb
  down from a hatch in the rigid horse, which remains bolted to its wheeled
  carrier, and open the large gates while Greek ships appear far out on the
  moonlit water. Show the action clearly without depicting an attack.
- 30.8–39.5 seconds: pull back into an illustrated parchment-story motif, then
  dissolve to calm archaeological ruins and pottery fragments suggesting that
  historians still investigate the story. End on a composed, fully formed shot
  with subtle movement rather than a fade to black.
""".strip()

FOLLOWUP_PROMPT = """
Create a continuous 16:9 illustrated continuation of the Troy film,
synchronized to the supplied answer. Use exactly the same polished flat-vector
storybook style, palette, wooden-horse design, ancient city, and gentle motion
as the main film. This must contain real character and environmental movement,
not a moving camera over one still image. No text, labels, captions,
photorealism, violence, weapons in action, or frightening imagery.

Begin with Trojan townspeople examining the enormous wooden horse on a peaceful
sunlit shore. The horse is a completely rigid carved statue with four straight
wooden legs permanently bolted to a broad rectangular timber carrier; four
round wooden wheels belong to the carrier. No part of the statue ever moves.
The people notice the empty Greek camp and look out across the quiet
sea, where the last tiny Greek sails visibly disappear beyond the horizon.
They brighten, decorate the horse with a simple victory garland, then begin
pulling the carrier with ropes toward Troy's open gates. End with the carrier
rolling forward and only its four wheels turning while the rigid horse and calm
empty horizon remain visible. The horse never walks, steps, bends, or animates.
""".strip()


def duration(path: Path) -> float:
    with wave.open(str(path)) as source:
        return source.getnframes() / source.getframerate()


async def render(maker: FilmMaker, audio: Path, output: Path, prompt: str) -> None:
    stream = DirectorStream(os.environ["FAL_KEY"], lambda event: asyncio.sleep(0))
    try:
        audio_url = await maker.upload_audio(audio.read_bytes())
        await stream.connect()
        stream.send({
            "type": "configure",
            "protocol_version": 1,
            "prompt_version": 1,
            "resolution": "480p",
            "aspect_ratio": "16:9",
            "memory": 12,
            "prompt": prompt,
            "audio_url": audio_url,
        })
        await asyncio.wait_for(stream.first_frame.wait(), 45)
        await record_film(stream, duration(audio) + 0.35, output)
        print(f"published {output.name} ({duration(audio) + 0.35:.2f}s)")
    finally:
        await stream.close()


async def main() -> None:
    load_dotenv(ROOT / ".env")
    if not os.environ.get("FAL_KEY", "").strip():
        raise RuntimeError("FAL_KEY is missing from the repository .env")
    maker = FilmMaker()
    try:
        await render(maker, STORY_AUDIO, STORY_VIDEO, STORY_PROMPT)
        await render(maker, FOLLOWUP_AUDIO, FOLLOWUP_VIDEO, FOLLOWUP_PROMPT)
    finally:
        await maker.close()


if __name__ == "__main__":
    asyncio.run(main())
