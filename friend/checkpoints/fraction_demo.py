"""Render the fraction-check reply in Gizmo's production Umbriel voice."""
from __future__ import annotations

import asyncio
import os
import wave
from pathlib import Path

from dotenv import load_dotenv

from checkpoints.plant_demo import trim_silence
from gizmo_friend.brain.narration import narration_provider_from_env
from gizmo_friend.oddity.demo_voice import DEMO_NARRATION_STYLE
from gizmo_friend.voice import AGENT_VOICE

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "friend" / "gizmo_friend" / "static" / "demo-math-fraction-gizmo.wav"
REPLY = (
    "Almost! You counted the two blue parts correctly, so two goes on top. "
    "But the circle is split into four equal parts, so four goes on the bottom. "
    "That is two-fourths, which is the same as one-half. Nice job checking!"
)


async def main() -> None:
    load_dotenv(ROOT / ".env")
    if not os.environ.get("GEMINI_API_KEY", "").strip():
        raise RuntimeError("GEMINI_API_KEY is missing from the repository .env")
    voice = narration_provider_from_env(voice=AGENT_VOICE, style=DEMO_NARRATION_STYLE)
    try:
        narration = await voice.narrate(REPLY)
        if narration is None:
            raise RuntimeError("The Umbriel narration did not arrive")
        pcm = trim_silence(narration.pcm)
        with wave.open(str(OUTPUT), "wb") as output:
            output.setparams((1, 2, 24_000, 0, "NONE", "not compressed"))
            output.writeframes(pcm)
        print(
            f"published {OUTPUT.name} ({len(pcm) / 48_000:.2f}s, "
            f"{AGENT_VOICE}, {narration.model})"
        )
    finally:
        await voice.close()


if __name__ == "__main__":
    asyncio.run(main())
