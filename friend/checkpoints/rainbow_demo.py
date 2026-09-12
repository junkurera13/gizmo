"""Render the two Gizmo replies for the interruptible rainbow demo."""
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
STATIC = ROOT / "friend" / "gizmo_friend" / "static"
REPLIES = {
    "demo-rainbow-gizmo-intro.wav": (
        "Sunlight enters a raindrop and bends.",
        "It reflects off the back of the drop, then bends again as it comes out.",
        "That spreading light makes a rainbow.",
    ),
    "demo-rainbow-gizmo-split.wav": (
        "White sunlight is actually many colors traveling together.",
        "Each color bends by a slightly different amount.",
        "So the colors spread apart like a fan opening, from red through violet.",
    ),
}
SENTENCE_PAUSE_MS = 950


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
        for filename, sentences in REPLIES.items():
            rendered: list[bytes] = []
            for sentence in sentences:
                narration = await voice.narrate(sentence)
                if narration is None:
                    raise RuntimeError(f"The Gizmo narration did not arrive for {filename}")
                rendered.append(trim_silence(narration.pcm))
            pause = b"\0\0" * (24_000 * SENTENCE_PAUSE_MS // 1000)
            pcm = pause.join(rendered) + pause
            output_path = STATIC / filename
            with wave.open(str(output_path), "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(24_000)
                output.writeframes(pcm)
            duration = len(pcm) / (2 * 24_000)
            print(f"published {filename} ({duration:.1f}s, {AGENT_VOICE})")
    finally:
        await voice.close()


if __name__ == "__main__":
    asyncio.run(main())
