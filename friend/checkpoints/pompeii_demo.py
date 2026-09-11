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
import io
import json
import math
import subprocess
import wave
from pathlib import Path

import imageio_ffmpeg
from dotenv import load_dotenv

from gizmo_friend.cinema.plan import FilmBeat, FilmMaker, FilmPlan, PreparedFilm
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


# Silence before each beat's words lets the scene establish first and hides
# Director's habit of starting the next visual slightly before its line.
LEAD_SECONDS = 0.6
# A calmer read than the brisk explainer pace suits a demo loop.
DEMO_STYLE = (
    "Read the following verbatim as a clear, curious explainer speaking to one "
    "interested listener. Use a gentle, unhurried conversational pace, about "
    "140–150 words per minute. Sound warm and matter-of-fact. Keep pitch "
    "movement restrained, consonants crisp, and pauses clean at full stops. "
    "Start promptly and finish cleanly. Do not add words."
)


async def synthesize_with_leads(maker: FilmMaker, plan: FilmPlan) -> PreparedFilm:
    voices = await asyncio.gather(
        *(maker.voice.narrate(beat.narration) for beat in plan.beats)
    )
    if any(voice is None for voice in voices):
        raise RuntimeError("The narration did not arrive.")
    pad = b"\0" * int(LEAD_SECONDS * 48000)
    pcm = bytearray()
    timings = []
    for beat, voice in zip(plan.beats, voices):
        pcm.extend(pad)
        start = len(pcm) / 48000
        pcm.extend(voice.pcm)
        timings.append(
            {
                "start": start,
                "end": len(pcm) / 48000,
                "narration": beat.narration,
                "action": beat.action,
            }
        )
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24000)
        audio.writeframes(bytes(pcm))
    return PreparedFilm(plan, "", len(pcm) / 48000, buffer.getvalue(), timings)


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


SAVED = ROOT / "data" / "show-checkpoints" / "pompeii-demo"


def scene_cuts(video: Path, regions: list[tuple[float, float]]) -> list[float]:
    """Strongest frame change inside each search window = the scene transition.

    Director starts the next picture a beat before its line, so narration
    boundaries alone cannot place the cuts. The real transitions are found in
    the recorded film within a few seconds of each speech gap.
    """
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    frame_size = 96 * 54
    probe = subprocess.Popen(
        [ffmpeg, "-i", str(video), "-vf", "scale=96:54", "-pix_fmt", "gray",
         "-f", "rawvideo", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )
    diffs = []
    prev = None
    index = 0
    while True:
        raw = probe.stdout.read(frame_size)
        if len(raw) < frame_size:
            break
        frame = bytes(raw)
        if prev is not None:
            total = sum(abs(a - b) for a, b in zip(frame, prev))
            diffs.append((index / FPS, total / len(frame)))
        prev = frame
        index += 1
    probe.stdout.close()
    probe.wait()
    cuts = []
    for lo, hi in regions:
        window = [d for d in diffs if lo <= d[0] <= hi]
        if not window:
            raise RuntimeError(f"no frames between {lo:.1f}s and {hi:.1f}s")
        cuts.append(max(window, key=lambda d: d[1])[0])
    return cuts


def cut_clips():
    """Split the saved film into per-beat clips at the detected scene changes."""
    timings = json.loads((SAVED / "timings.json").read_text())
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    regions = [
        (timings[index]["end"] - 1.0, timings[index + 1]["start"] + 1.5)
        for index in range(len(timings) - 1)
    ]
    transitions = scene_cuts(SAVED / "full.mp4", regions)
    print(f"scene transitions at {[f'{t:.2f}' for t in transitions]}")
    video_bounds = [0.0, *transitions, timings[-1]["end"] + 0.3]
    audio_starts = [0.0] + [timing["end"] for timing in timings[:-1]]
    for index, timing in enumerate(timings):
        v_start, v_end = video_bounds[index], video_bounds[index + 1]
        a_start, a_end = audio_starts[index], timing["end"]
        subprocess.run(
            [ffmpeg, "-y", "-ss", f"{v_start}", "-to", f"{v_end}",
             "-i", str(SAVED / "full.mp4"), "-c:v", "libx264",
             "-pix_fmt", "yuv420p", "-an",
             str(STATIC / f"demo-pompeii-{index + 1}.mp4")],
            check=True, capture_output=True,
        )
        subprocess.run(
            [ffmpeg, "-y", "-ss", f"{a_start}", "-to", f"{a_end}",
             "-i", str(SAVED / "full.wav"), "-c:a", "pcm_s16le",
             str(STATIC / f"demo-pompeii-{index + 1}.wav")],
            check=True, capture_output=True,
        )
        print(
            f"beat {index + 1}: video {v_start:.1f}-{v_end:.1f}s, "
            f"audio {a_start:.1f}-{a_end:.1f}s"
        )


async def main():
    load_dotenv(ROOT / ".env")
    if "--cut-only" in sys.argv:
        cut_clips()
        return
    maker = FilmMaker()
    stream = DirectorStream(os.environ["FAL_KEY"], lambda event: asyncio.sleep(0))
    try:
        maker.voice.style = DEMO_STYLE
        prepared = await synthesize_with_leads(maker, PLAN)
        print(f"narration: {prepared.duration:.1f}s")
        audio_url = await maker.upload_audio(prepared.wav)
        SAVED.mkdir(parents=True, exist_ok=True)
        (SAVED / "full.wav").write_bytes(prepared.wav)
        (SAVED / "timings.json").write_text(json.dumps(prepared.timings))
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
        await record_film(stream, prepared.duration + 0.5, SAVED / "full.mp4")
        cut_clips()
    finally:
        await stream.close()
        await maker.close()


if __name__ == "__main__":
    import os
    import sys

    asyncio.run(main())
