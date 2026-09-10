"""Opt-in live story check with two fresh scenes. Spends image credits.

Run from the repository: .venv/bin/python friend/checkpoints/story_scenes.py
Generated stills, speech, and transcripts are saved in data/show-checkpoints/.
Friend does not grow short clips; moving chapters play Cinema.
"""
from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import sys
import tempfile
from datetime import UTC, datetime
from types import SimpleNamespace

from dotenv import load_dotenv

from gizmo_friend.brain.images import ImageProvider, image_provider_from_env
from gizmo_friend.brain.memory import NullMemoryProvider
from gizmo_friend.brain.reasoning import NullReasoningProvider
from gizmo_friend.session import GizmoSession
from gizmo_friend.states import State

sys.path.insert(0, str(Path(__file__).resolve().parent))
from story_continuity import RecordingDirector, ROOT, run_turn


PROMPTS = [
    "Tell me a story about a fox who's scared of dragons.",
    "Wait. He's actually scared of bells.",
    "They should escape in a submarine.",
    "Then what?",
]


class RecordingImages(ImageProvider):
    def __init__(self, inner, output: Path):
        self.inner = inner
        self.output = output
        self.calls = []

    async def conjure(self, subject, *, kind="scene", character="", reference=None):
        still = await self.inner.conjure(subject, kind=kind, character=character, reference=reference)
        record = {"subject": subject, "kind": kind, "character": character, "reference_used": reference is not None, "ok": still is not None}
        record["reference_sha256"] = hashlib.sha256(reference).hexdigest() if reference else None
        if still is not None:
            path = self.output / f"still-{len(self.calls) + 1}.jpg"
            path.write_bytes(still.jpeg)
            record.update(
                path=str(path),
                latency_seconds=round(still.latency_seconds, 3),
                model=still.model,
                width=still.width,
                height=still.height,
            )
        self.calls.append(record)
        return still

    async def close(self):
        await self.inner.close()


def _glass_timing(events):
    still_at = next((event["seconds"] for event in events if event.get("type") == "glass" and event.get("still") and not event.get("clip")), None)
    clip_at = next((event["seconds"] for event in events if event.get("type") == "glass" and event.get("clip")), None)
    listening_at = next((event["seconds"] for event in events if event.get("type") == "state" and event.get("state") == "listening"), None)
    return {
        "still_seconds": still_at,
        "clip_seconds": clip_at,
        "listening_seconds": listening_at,
        "still_during_speech": bool(still_at is not None and listening_at is not None and still_at < listening_at),
        "clip_during_speech": bool(clip_at is not None and listening_at is not None and clip_at < listening_at),
    }


async def main():
    load_dotenv(ROOT / ".env")
    output = ROOT / "data/show-checkpoints" / datetime.now(UTC).strftime("%Y-%m-%d-kid-story-%H%M%S")
    output.mkdir(parents=True)
    images = RecordingImages(image_provider_from_env(), output)
    clips = SimpleNamespace(calls=[])
    director = RecordingDirector(os.environ["FAL_KEY"])
    result = {
        "media": "fresh Gemini stills; moving chapters play Cinema, not Fal clips",
        "turns": [],
    }
    with tempfile.TemporaryDirectory() as temporary:
        friend = GizmoSession(
            Path(temporary), user_id="story-scenes-checkpoint",
            gemini_key=os.environ["GEMINI_API_KEY"],
            memory_provider=NullMemoryProvider(), reasoning_provider=NullReasoningProvider(),
            image_provider=images, visual_director=director,
            idle_sleep_s=0, show_idle_s=0,
        )
        friend.machine.state = State.LISTENING
        friend._touch()
        queue = friend.subscribe()
        try:
            await friend._ensure_connected()
            for number, prompt in enumerate(PROMPTS, 1):
                turn = await run_turn(
                    friend, queue, director, images, clips, prompt, output, number,
                    timeout_s=90,
                )
                turn["glass"] = _glass_timing(turn["events"])
                result["turns"].append(turn)
                result["image_generation_requests"] = len(images.calls)
                result["video_generation_requests"] = len(clips.calls)
                (output / "results.json").write_text(json.dumps(result, indent=2) + "\n")
                print(json.dumps({
                    "turn": number,
                    "narration": turn["narration"],
                    "director": [call["decision"] for call in turn["director"]],
                    "images": turn["images"],
                    "clips": turn["clips"],
                    "same_show": turn["same_show"],
                    "glass": turn["glass"],
                }), flush=True)
        finally:
            await friend.close()
            print(f"Evidence: {output}", flush=True)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
