"""Render the Pompeii Oddity demo through the real Cinema pipeline.

Authors a deterministic three-beat kid-safe plan, synthesizes the narration
with the production voice, uploads it, opens a live Director session, records
the streamed film to MP4, then splits per-beat clips and narration into
friend/gizmo_friend/static/demo-pompeii-*.

Run from the repository: .venv/bin/python friend/checkpoints/pompeii_demo.py
Requires FAL_KEY and the narration provider key (same env as the brain).
Costs one Director session (~40 seconds of generation).
"""
from __future__ import annotations

import asyncio
import json
import math
import subprocess
import tempfile
from pathlib import Path

import imageio_ffmpeg
from dotenv import load_dotenv

from gizmo_friend.cinema.plan import FilmBeat, FilmMaker, FilmPlan
from gizmo_friend.cinema.stream import DirectorStream

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "friend" / "gizmo_friend" / "static"
FPS = 24

PLAN = FilmPlan(
    title="The City Under the Ash",
    thread="What the buried city looked like when it was found.",
    relation="new",
    beats=[
        FilmBeat(
            narration=(
                "Almost two thousand years ago, the city of Pompeii sat at the "
                "foot of a mountain called Vesuvius, and one day it erupted "
                "without warning."
            ),
            action=(
                "A sunny flat-vector Roman city with domed roofs, market stalls "
                "and little trees spreads below a tall green mountain; a small "
                "grey puff appears at the peak and grows."
            ),
        ),
        FilmBeat(
            narration=(
                "The mountain blasted ash and rock high into the sky, and a "
                "giant grey cloud raced down its sides faster than anyone "
                "could run."
            ),
            action=(
                "The sky darkens to dusk-grey; a huge billowing cloud with a "
                "warm orange core rolls down the mountain over the city while "
                "soft ash flakes fall like snow."
            ),
        ),
        FilmBeat(
            narration=(
                "The ash buried Pompeii so completely that it stayed hidden "
                "for centuries, and when diggers uncovered it, the houses, "
                "streets and paintings were still there."
            ),
            action=(
                "A cross-section cutaway shows the city sealed under grey ash "
                "mounds; then archaeologists in straw hats brush away ash to "
                "reveal a colorful mosaic fountain and painted red walls."
            ),
        ),
    ],
)


async def record_film(stream: DirectorStream, seconds: float, path: Path):
    await asyncio.wait_for(stream.video_ready.wait(), 30)
    track = stream.relay.subscribe(stream.tracks["video"])
    images = []
    first_time = None
    next_frame = 0
    target = math.ceil(seconds * FPS)
    try:
        async with asyncio.timeout(seconds + 30):
            while next_frame < target:
                frame = await track.recv()
                if first_time is None:
                    first_time = frame.time
                timestamp = frame.time - first_time
                if timestamp + 0.001 < next_frame / FPS:
                    continue
                image = frame.to_image()
                while (
                    next_frame / FPS <= timestamp + 0.001 and next_frame < target
                ):
                    images.append(image)
                    next_frame += 1
    finally:
        track.stop()
    if not images:
        raise RuntimeError("Director sent no frames")
    size = images[0].size
    writer = imageio_ffmpeg.write_frames(
        str(path), size, fps=FPS, codec="libx264", pix_fmt_out="yuv420p",
        ffmpeg_timeout=30,
    )
    next(writer)
    try:
        for image in images:
            writer.send(image.tobytes())
    finally:
        writer.close()
    print(f"recorded {len(images)} frames at {size[0]}x{size[1]}")


async def main():
    load_dotenv(ROOT / ".env")
    maker = FilmMaker()
    stream = DirectorStream(os.environ["FAL_KEY"], lambda event: asyncio.sleep(0))
    try:
        prepared = await maker.synthesize(PLAN)
        print(f"narration: {prepared.duration:.1f}s, timings: {prepared.timings}")
        audio_url = await maker.upload_audio(prepared.wav)
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            (work / "full.wav").write_bytes(prepared.wav)
            await stream.connect()
            stream.send(
                {
                    "type": "configure",
                    "protocol_version": 1,
                    "prompt_version": 1,
                    "resolution": "480p",
                    "aspect_ratio": "16:9",
                    "memory": 12,
                    "prompt": PLAN.direction()
                    + "\nAudio timeline in seconds: "
                    + json.dumps(prepared.timings),
                    "audio_url": audio_url,
                }
            )
            await asyncio.wait_for(stream.first_frame.wait(), 45)
            await record_film(stream, prepared.duration + 0.5, work / "full.mp4")
            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
            for index, timing in enumerate(prepared.timings, start=1):
                start, end = timing["start"], timing["end"]
                subprocess.run(
                    [ffmpeg, "-y", "-ss", str(start), "-to", str(end),
                     "-i", str(work / "full.mp4"), "-c:v", "libx264",
                     "-pix_fmt", "yuv420p", "-an",
                     str(STATIC / f"demo-pompeii-{index}.mp4")],
                    check=True, capture_output=True,
                )
                subprocess.run(
                    [ffmpeg, "-y", "-ss", str(start), "-to", str(end),
                     "-i", str(work / "full.wav"), "-c:a", "pcm_s16le",
                     str(STATIC / f"demo-pompeii-{index}.wav")],
                    check=True, capture_output=True,
                )
                print(f"beat {index}: {start:.1f}-{end:.1f}s written")
    finally:
        await stream.close()
        await maker.close()


if __name__ == "__main__":
    import os

    asyncio.run(main())
