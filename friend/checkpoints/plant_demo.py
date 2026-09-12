"""Render the plant-camera reply in Gizmo's production Umbriel voice.

Run from the repository root after placing GEMINI_API_KEY in the ignored .env:
python friend/checkpoints/plant_demo.py
"""
from __future__ import annotations

import asyncio
import os
import wave
from array import array
from pathlib import Path

from dotenv import load_dotenv

from gizmo_friend.brain.narration import narration_provider_from_env
from gizmo_friend.voice import AGENT_VOICE

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "friend" / "gizmo_friend" / "static" / "demo-plant-gizmo.wav"
REPLY = "Brown spots and yellow edges mean this leaf needs more shade."
PLANT_NARRATION_STYLE = (
    "Read the following verbatim in the configured character voice. Use a warm, natural, friendly "
    "pace of about 150 words per minute. Start promptly, use no dramatic pauses, and finish cleanly. "
    "Do not add words."
)


def trim_silence(pcm: bytes, *, sample_rate: int = 24_000) -> bytes:
    """Remove generated head/tail silence without changing the spoken delivery."""
    samples = array("h")
    samples.frombytes(pcm)
    chunk = sample_rate // 100
    levels = [
        sum(abs(value) for value in samples[index:index + chunk]) / chunk
        for index in range(0, len(samples), chunk)
    ]
    audible = [index for index, level in enumerate(levels) if level > 250]
    if not audible:
        return pcm
    padding = sample_rate // 100
    start = max(0, audible[0] * chunk - padding)
    end = min(len(samples), (audible[-1] + 1) * chunk + padding)
    return samples[start:end].tobytes()


async def main() -> None:
    load_dotenv(ROOT / ".env")
    if not os.environ.get("GEMINI_API_KEY", "").strip():
        raise RuntimeError("GEMINI_API_KEY is missing from the repository .env")
    voice = narration_provider_from_env(voice=AGENT_VOICE, style=PLANT_NARRATION_STYLE)
    try:
        narration = await voice.narrate(REPLY)
        if narration is None:
            raise RuntimeError("The Umbriel narration did not arrive")
        pcm = trim_silence(narration.pcm)
        with wave.open(str(OUTPUT), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(24_000)
            output.writeframes(pcm)
        duration = len(pcm) / (2 * 24_000)
        print(f"published {OUTPUT.name} ({duration:.1f}s, {AGENT_VOICE})")
    finally:
        await voice.close()


if __name__ == "__main__":
    asyncio.run(main())
