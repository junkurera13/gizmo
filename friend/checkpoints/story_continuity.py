"""Opt-in live voice/director check with saved media only. No image/video calls.

Run from the repository: .venv/bin/python friend/checkpoints/story_continuity.py
Evidence and synthetic-story audio are saved in data/show-checkpoints/.
"""
from __future__ import annotations

import asyncio
import base64
from dataclasses import asdict
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import wave

from dotenv import load_dotenv

from gizmo_friend.body_protocol import TextLine
from gizmo_friend.brain.clips import ClipProvider, ConjuredClip
from gizmo_friend.brain.images import ConjuredStill, ImageProvider
from gizmo_friend.brain.memory import NullMemoryProvider
from gizmo_friend.brain.reasoning import NullReasoningProvider
from gizmo_friend.brain.visual_director import GeminiVisualDirector
from gizmo_friend.session import GizmoSession
from gizmo_friend.states import State


ROOT = Path(__file__).resolve().parents[2]
SAVED = ROOT / "data/show-checkpoints/2026-09-03-checkpoint-1"
CLIP = ROOT / "data/show-checkpoints/2026-09-03-checkpoint-10/trilobite-static-fixture.mp4"
PROMPTS = [
    "Tell me a story about a fox who's scared of dragons.",
    "Wait. He's actually scared of bells.",
    "Then what?",
    "They should escape in a submarine.",
    "Then what?",
    "What is six times seven?",
]


class ReplayImages(ImageProvider):
    def __init__(self):
        self.calls = []

    async def conjure(self, subject, *, kind="scene", character="", reference=None):
        lower = subject.casefold()
        filename = "06-wave.jpg" if any(word in lower for word in ("ocean", "submarine", "underwater", "seafloor", "seabed")) else "05-castle.jpg"
        path = SAVED / filename
        self.calls.append({"subject": subject, "fixture": str(path)})
        return ConjuredStill(
            subject=subject, jpeg=path.read_bytes(), prompt="saved routing fixture, not a newly rendered story scene",
            model="replay", width=512, height=384, source_width=512, source_height=384,
            latency_seconds=0,
        )


class ReplayClips(ClipProvider):
    def __init__(self):
        self.calls = []

    async def animate(self, still, motion):
        self.calls.append({"motion": motion, "fixture": str(CLIP)})
        return ConjuredClip(
            motion=motion, mp4=CLIP.read_bytes(), prompt="saved static transport fixture, not new story motion",
            model="replay", request_id=f"replay-{len(self.calls)}",
            source_image_sha256=hashlib.sha256(still).hexdigest(), latency_seconds=0,
            expanded_prompt=None, timings={},
        )


class RecordingDirector(GeminiVisualDirector):
    def __init__(self, api_key):
        super().__init__(api_key)
        self.calls = []

    async def decide(self, utterance, **context):
        started = time.monotonic()
        decision = await super().decide(utterance, **context)
        self.calls.append({
            "utterance": utterance,
            "narration": context.get("narration", ""),
            "narration_complete": context.get("narration_complete", True),
            "current_story_setting": context.get("current_story_setting", ""),
            "recent_dialogue": [asdict(turn) for turn in context.get("recent_dialogue", ())],
            "current_subject": context.get("current_subject", ""),
            "current_character": context.get("current_character", ""),
            "decision": asdict(decision),
            "seconds": round(time.monotonic() - started, 3),
        })
        return decision


async def run_turn(friend, queue, director, images, clips, prompt, output, number, timeout_s=45):
    while not queue.empty():
        queue.get_nowait()
    prior_calls = len(director.calls)
    prior_images = len(images.calls)
    prior_clips = len(clips.calls)
    before = friend.current_show.id if friend.current_show else None
    started = time.monotonic()
    events = []
    pcm = bytearray()

    def record(event):
        summary = {"seconds": round(time.monotonic() - started, 3), **event}
        encoded = summary.pop("pcm", None)
        if encoded:
            raw = base64.b64decode(encoded)
            pcm.extend(raw)
            summary["pcm_bytes"] = len(raw)
        events.append(summary)

    # Consume continuously, including while media jobs finish after speech.
    # These are server-observed event times, not physical display timestamps.
    speech_done = asyncio.Event()

    async def collect():
        while True:
            event = await queue.get()
            record(event)
            if event.get("type") == "state" and event.get("state") == "listening":
                speech_done.set()

    collector = asyncio.create_task(collect())
    try:
        async with asyncio.timeout(timeout_s):
            await friend.handle(TextLine(text=prompt))
            await speech_done.wait()
            if friend._director_task:
                await friend._director_task
            tasks = tuple(friend._show_tasks | friend._clip_tasks)
            if tasks:
                await asyncio.gather(*tasks)
            # Still completion can start a clip task after the first snapshot.
            if friend._clip_tasks:
                await asyncio.gather(*tuple(friend._clip_tasks))
            await asyncio.sleep(0)  # Let the collector consume final emissions.
    finally:
        collector.cancel()
        await asyncio.gather(collector, return_exceptions=True)
    while not queue.empty():
        record(queue.get_nowait())
    audio_path = output / f"turn-{number}.wav"
    with wave.open(str(audio_path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24000)
        audio.writeframes(pcm)
    after = friend.current_show.id if friend.current_show else None
    return {
        "prompt": prompt,
        "narration": " ".join(event.get("text", "") for event in events if event.get("type") == "transcript" and event.get("role") == "gizmo"),
        "director": director.calls[prior_calls:],
        "images": images.calls[prior_images:], "clips": clips.calls[prior_clips:],
        "show_before": before, "show_after": after, "same_show": bool(before and before == after),
        "audio_seconds": round(len(pcm) / 48000, 3), "audio_file": str(audio_path),
        "events": events,
    }


async def main():
    load_dotenv(ROOT / ".env")
    # Explicitly injected replay/null providers prevent accidental media or memory calls.
    output = ROOT / "data/show-checkpoints" / (datetime.now(UTC).strftime("%Y-%m-%d-story-continuity-%H%M%S"))
    output.mkdir(parents=True)
    result = {"media": "saved replay fixtures only; no fresh scene or motion fidelity claim",
              "image_generation_requests": 0, "video_generation_requests": 0, "turns": []}
    images, clips = ReplayImages(), ReplayClips()
    director = RecordingDirector(os.environ["GEMINI_API_KEY"])
    with tempfile.TemporaryDirectory() as temporary:
        friend = GizmoSession(
            Path(temporary), user_id="story-checkpoint", gemini_key=os.environ["GEMINI_API_KEY"],
            memory_provider=NullMemoryProvider(), reasoning_provider=NullReasoningProvider(),
            image_provider=images, clip_provider=clips, visual_director=director,
            idle_sleep_s=0, show_idle_s=0,
        )
        friend.machine.state = State.LISTENING
        friend._touch()
        queue = friend.subscribe()
        try:
            await friend._ensure_connected()
            for number, prompt in enumerate(PROMPTS, 1):
                turn = await run_turn(friend, queue, director, images, clips, prompt, output, number)
                result["turns"].append(turn)
                (output / "results.json").write_text(json.dumps(result, indent=2) + "\n")
                print(json.dumps({"turn": number, "narration": turn["narration"],
                                  "director": turn["director"], "same_show": turn["same_show"]}), flush=True)
        finally:
            await friend.close()
            print(f"Evidence: {output}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
