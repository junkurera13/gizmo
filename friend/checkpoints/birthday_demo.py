"""Render the birthday reply with the same Umbriel voice used by Pompeii.

Run from the repository root after placing GEMINI_API_KEY in the ignored .env:
python friend/checkpoints/birthday_demo.py
"""
from __future__ import annotations

import asyncio
import os
import wave
from pathlib import Path

from dotenv import load_dotenv

from gizmo_friend.brain.narration import narration_provider_from_env
from gizmo_friend.oddity.demo_voice import DEMO_NARRATION_STYLE
from gizmo_friend.voice import AGENT_VOICE

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "friend" / "gizmo_friend" / "static" / "demo-birthday-gizmo.wav"
REPLY = (
    "Eleven more days. That's close enough to start getting excited. "
    "Your birthday will be here before you know it."
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
        with wave.open(str(OUTPUT), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(24_000)
            output.writeframes(narration.pcm)
        print(f"published {OUTPUT.name} ({narration.duration_seconds:.1f}s, {AGENT_VOICE})")
    finally:
        await voice.close()


if __name__ == "__main__":
    asyncio.run(main())
