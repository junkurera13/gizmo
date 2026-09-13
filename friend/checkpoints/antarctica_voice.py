"""Render Antarctica with the exact production Umbriel narration provider."""
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
OUTPUT = ROOT / "friend" / "gizmo_friend" / "static" / "demo-antarctica-gizmo.wav"
REPLY = (
    "Antarctica is the icy continent at the very bottom of Earth. On a globe, it wraps around "
    "the South Pole. Most of it is covered by a huge sheet of ice, with bright glaciers, tall "
    "mountains, and deep blue cracks. Along the coast, you can see floating icebergs and penguins, "
    "while the middle is a cold, windy white desert."
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
        with wave.open(str(OUTPUT), "wb") as target:
            target.setparams((1, 2, 24_000, 0, "NONE", "not compressed"))
            target.writeframes(pcm)
        print(
            f"published {OUTPUT.name} ({len(pcm) / 48_000:.2f}s, "
            f"{AGENT_VOICE}, {narration.model})"
        )
    finally:
        await voice.close()


if __name__ == "__main__":
    asyncio.run(main())
