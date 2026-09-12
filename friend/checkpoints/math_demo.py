"""Render the math-check demo reply in Gizmo's production Umbriel voice."""
from __future__ import annotations

import asyncio
import os
import wave
from array import array
from pathlib import Path

from dotenv import load_dotenv

from gizmo_friend.brain.narration import narration_provider_from_env
from gizmo_friend.oddity.demo_voice import DEMO_NARRATION_STYLE
from gizmo_friend.voice import AGENT_VOICE

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "friend" / "gizmo_friend" / "static" / "demo-math-gizmo.wav"
REPLY = (
    "Nice work—you were only one away! Twenty-seven plus sixteen is forty-three, not "
    "forty-two. Look at the ones: move three from the six to the seven to make a new ten, "
    "with three left. Now we have four tens and three ones, which makes forty-three. "
    "Great job checking your answer!"
)


def trim_silence(pcm: bytes, *, sample_rate: int = 24_000) -> bytes:
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
    voice = narration_provider_from_env(voice=AGENT_VOICE, style=DEMO_NARRATION_STYLE)
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
